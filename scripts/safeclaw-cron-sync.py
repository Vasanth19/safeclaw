#!/usr/bin/env python3
"""
safeclaw-cron-sync.py — translate a SafeClaw Hermes config's ``schedules:``
block into real Hermes cron jobs.

WHY THIS EXISTS
---------------
SafeClaw's reader/actor configs declare scheduled automations under a top-level
``schedules:`` key (e.g. ``slack_ingest`` every 30 min). This Hermes version's
gateway/config loader does NOT read that key — it is silently ignored, so the
ingestion cron never registers and the brain stays at 0 pages.

This script bridges that gap. It is invoked at container start (from
``hermes-docker-init.sh``, running as the ``hermes`` user with
``HERMES_HOME=/opt/data``), reads the mounted config, and registers each
schedule as a Hermes cron job in ``$HERMES_HOME/cron/jobs.json`` — the real
job store the gateway daemon ticks every 60 s.

DECLARATIVE + IDEMPOTENT
------------------------
The config is the source of truth for config-sourced jobs. Every job this
script manages is tagged ``origin={"source": SYNC_SOURCE}``. On each run it:

  * creates a job for any ``schedules:`` entry that has no matching job
  * updates a managed job whose cron expr / prompt / settings drifted
  * prunes managed jobs whose schedule name is no longer in the config

Jobs created by the agent itself or by an operator (no sync marker) are never
touched, so this is safe to re-run on every boot.

SCHEDULE ENTRY SCHEMA (under ``schedules:``)
--------------------------------------------
    schedules:
      slack_ingest:
        cron: "*/30 * * * *"          # required — 5/6-field cron expression
        description: "..."            # used as the prompt if `prompt` absent
        prompt: "..."                 # optional explicit prompt override
        deliver: local                # optional (default: local)
        skills: [core]                # optional
        enabled_toolsets: [...]       # optional — restrict the agent's tools
        repeat: 5                     # optional — run N times then stop

FAIL-SAFE
---------
This runs as a best-effort startup step. A failure here must NOT block the
agent from booting, so per-entry errors are logged loudly to stderr and the
script still exits 0. It logs every action it takes so the boot log shows
exactly which jobs were created / updated / pruned.
"""

import os
import sys

# The Hermes install root — `cron.jobs`, `hermes_constants`, `hermes_time` and
# `croniter` all resolve from here. Set before importing cron.jobs.
HERMES_INSTALL_DIR = os.environ.get("HERMES_INSTALL_DIR", "/opt/hermes")
sys.path.insert(0, HERMES_INSTALL_DIR)

# Marker stamped on every job this script manages, so we can update/prune our
# own jobs without ever touching agent- or operator-created ones.
SYNC_SOURCE = "safeclaw-config-sync"


def log(msg: str) -> None:
    print(f"[safeclaw-cron-sync] {msg}", file=sys.stderr, flush=True)


def _coerce_prompt(name: str, spec: dict) -> str:
    """Resolve the prompt for a schedule entry (explicit `prompt` wins)."""
    prompt = spec.get("prompt") or spec.get("description") or ""
    return " ".join(str(prompt).split()).strip()


def main() -> int:
    config_path = sys.argv[1] if len(sys.argv) > 1 else "/opt/data/config.yaml"

    try:
        import yaml
    except ImportError:
        log("PyYAML not importable from this interpreter — cannot parse config; skipping")
        return 0

    if not os.path.isfile(config_path):
        log(f"config not found at {config_path} — nothing to sync")
        return 0

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
    except Exception as exc:  # noqa: BLE001 — never crash the container
        log(f"failed to read/parse {config_path}: {exc} — skipping")
        return 0

    if not isinstance(cfg, dict):
        log("config is not a mapping — skipping")
        return 0

    schedules = cfg.get("schedules") or {}
    if not isinstance(schedules, dict):
        log("`schedules:` is not a mapping — skipping")
        return 0
    # An empty `schedules:` block is valid: it means "no config-sourced jobs",
    # so we still proceed to prune any previously-synced jobs.
    if not schedules:
        log("`schedules:` is empty — will prune any previously-synced jobs")

    # Import the real Hermes cron store. Light deps (hermes_constants /
    # hermes_time / croniter); HERMES_HOME (set by the caller) decides where
    # jobs.json lives.
    try:
        from cron.jobs import (
            JOBS_FILE,
            create_job,
            list_jobs,
            remove_job,
            update_job,
        )
    except Exception as exc:  # noqa: BLE001
        log(f"could not import Hermes cron store ({exc}) — is HERMES_INSTALL_DIR correct? skipping")
        return 0

    log(f"using job store {JOBS_FILE}")

    # Index existing jobs by name; track which ones we manage.
    existing = list_jobs(include_disabled=True)
    by_name = {j.get("name"): j for j in existing}
    managed_names = {
        j.get("name")
        for j in existing
        if isinstance(j.get("origin"), dict) and j["origin"].get("source") == SYNC_SOURCE
    }

    desired_names = set()

    for name, spec in schedules.items():
        if not isinstance(spec, dict):
            log(f"schedule '{name}': not a mapping — skipping")
            continue

        cron_expr = spec.get("cron")
        prompt = _coerce_prompt(name, spec)
        if not cron_expr or not prompt:
            log(f"schedule '{name}': missing cron or prompt/description — skipping")
            continue

        desired_names.add(name)
        deliver = spec.get("deliver") or "local"
        skills = spec.get("skills")
        enabled_toolsets = spec.get("enabled_toolsets")
        repeat = spec.get("repeat")
        origin = {"source": SYNC_SOURCE}

        job = by_name.get(name)
        try:
            if job is None:
                created = create_job(
                    prompt=prompt,
                    schedule=str(cron_expr),
                    name=name,
                    deliver=deliver,
                    repeat=repeat,
                    skills=skills,
                    enabled_toolsets=enabled_toolsets,
                    origin=origin,
                )
                log(f"created '{name}' ({cron_expr}) -> next {created.get('next_run_at')}")
                continue

            # Only adopt/update jobs we manage; never overwrite an
            # agent/operator job that happens to share the name.
            if name not in managed_names:
                log(f"'{name}' exists but is not sync-managed — leaving it untouched")
                continue

            cur_expr = (job.get("schedule") or {}).get("expr")
            cur_prompt = job.get("prompt")
            cur_deliver = job.get("deliver")
            if cur_expr == str(cron_expr) and cur_prompt == prompt and cur_deliver == deliver:
                log(f"'{name}' already in sync — no change")
                continue

            update_job(
                job["id"],
                {
                    "schedule": str(cron_expr),
                    "prompt": prompt,
                    "deliver": deliver,
                },
            )
            log(f"updated '{name}' (cron/prompt/deliver drift reconciled)")
        except Exception as exc:  # noqa: BLE001 — one bad entry must not abort the rest
            log(f"schedule '{name}': error applying ({exc}) — skipping this entry")

    # Prune managed jobs whose schedule was removed/renamed in the config.
    for stale in managed_names - desired_names:
        job = by_name.get(stale)
        if not job:
            continue
        try:
            remove_job(job["id"])
            log(f"pruned '{stale}' (no longer in config)")
        except Exception as exc:  # noqa: BLE001
            log(f"failed to prune '{stale}' ({exc})")

    return 0


if __name__ == "__main__":
    sys.exit(main())
