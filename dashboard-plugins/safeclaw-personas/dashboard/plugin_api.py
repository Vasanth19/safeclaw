"""SafeClaw Personas — dashboard plugin backend.

Mounted at /api/plugins/safeclaw-personas/ by the Hermes dashboard plugin system.

A *persona* is a voice: a system prompt + model + tone + skills + summon
phrases. It is bound to exactly one **trust boundary** — the SafeClaw Reader
or the SafeClaw Actor — and it INHERITS that agent's tool allowlist. A persona
can never declare its own tools. That is the entire security guarantee: a
persona changes how the assistant *speaks*, never what it is *allowed to touch*.

If a persona could grant itself tools, it could reunite the lethal trifecta
(private data + untrusted input + exfiltration) that SafeClaw's Reader/Actor
split exists to break. So every write path here strips/rejects a `tools` field.

Storage:  personas live as YAML files in SAFECLAW_PERSONAS_DIR
          (default: ~/.hermes/personas).
Tools:    inherited from the agent's `mcp_servers` block in
          SAFECLAW_CONFIG_DIR (default: the repo's config/ dir).
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import yaml
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

router = APIRouter()

# ── Trust boundaries ─────────────────────────────────────────────────────────
# These are the only two agents a persona may bind to. The descriptions are
# surfaced in the UI so the operator understands what each persona can do.
AGENTS: dict[str, dict[str, str]] = {
    "reader": {
        "label": "Reader",
        "config": "reader-hermes.yaml",
        "trust": "Reads untrusted input (email, Slack). Writes structured "
                 "observations only. Cannot send, draft, post, or delete.",
        "badge": "read-only",
    },
    "actor": {
        "label": "Actor",
        "config": "actor-hermes.yaml",
        "trust": "Drafts and sends on your behalf. Reads the brain + your "
                 "observations, never raw untrusted input. Every send is gated "
                 "by your approval.",
        "badge": "draft + send",
    },
}

# Fields a client is allowed to set on a persona. `agent` is settable on create
# but is the binding that determines inherited tools. `tools` is NOT here — by
# design. Any inbound `tools` key is rejected, not silently dropped.
EDITABLE_FIELDS = {
    "name", "job", "model", "behavior", "skills", "summon_phrases", "avatar",
}
ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,48}[a-z0-9]$")


def _personas_dir() -> Path:
    d = Path(os.environ.get(
        "SAFECLAW_PERSONAS_DIR",
        Path.home() / ".hermes" / "personas",
    )).expanduser()
    d.mkdir(parents=True, exist_ok=True)
    return d


def _config_dir() -> Path:
    # Default to the repo config/ dir two levels up from this plugin, but let
    # deployments override (e.g. the path mounted into the Hermes container).
    default = Path(__file__).resolve().parents[3] / "config"
    return Path(os.environ.get("SAFECLAW_CONFIG_DIR", default)).expanduser()


def _inherited_tools(agent: str) -> list[str]:
    """Resolve an agent's tool allowlist from its SafeClaw config.

    The allowlist is the set of `mcp_servers` the agent binds at boot. This is
    the ground truth the persona inherits and cannot change.
    """
    meta = AGENTS.get(agent)
    if not meta:
        return []
    cfg_path = _config_dir() / meta["config"]
    if not cfg_path.exists():
        return []
    try:
        cfg = yaml.safe_load(cfg_path.read_text()) or {}
    except yaml.YAMLError:
        return []
    servers = cfg.get("mcp_servers") or {}
    return sorted(servers.keys())


def _persona_path(persona_id: str) -> Path:
    if not ID_RE.match(persona_id):
        raise HTTPException(400, f"invalid persona id: {persona_id!r}")
    return _personas_dir() / f"{persona_id}.yaml"


def _load(persona_id: str) -> dict[str, Any]:
    p = _persona_path(persona_id)
    if not p.exists():
        raise HTTPException(404, f"persona not found: {persona_id}")
    data = yaml.safe_load(p.read_text()) or {}
    data["id"] = persona_id
    return data


def _hydrate(data: dict[str, Any]) -> dict[str, Any]:
    """Attach the read-only, inherited security context for display."""
    agent = data.get("agent")
    meta = AGENTS.get(agent, {})
    return {
        **data,
        "agent": agent,
        "agent_label": meta.get("label", agent),
        "agent_trust": meta.get("trust", ""),
        "agent_badge": meta.get("badge", ""),
        "inherited_tools": _inherited_tools(agent) if agent else [],
        "tools_locked": True,  # always — UI renders this as a hard lock
    }


def _reject_tools(payload: dict[str, Any]) -> None:
    """The single most important line of defense in this plugin."""
    if "tools" in payload or "mcp_servers" in payload:
        raise HTTPException(
            422,
            "A persona cannot declare its own tools. Tools are inherited from "
            "the bound agent (Reader or Actor) and are immutable. Remove the "
            "'tools'/'mcp_servers' field. If this persona genuinely needs "
            "different capabilities, it is a new trust boundary, not a persona "
            "— change the agent config and re-validate the security split.",
        )


# ── Schemas ────────────────────────────────────────────────────────────────
class PersonaModel(BaseModel):
    provider: str = "anthropic"
    name: str = "claude-opus-4.7"


class PersonaBehavior(BaseModel):
    tone: str = ""
    system_prompt: str = ""


class PersonaCreate(BaseModel):
    id: str
    name: str
    agent: str
    job: str = ""
    model: PersonaModel = Field(default_factory=PersonaModel)
    behavior: PersonaBehavior = Field(default_factory=PersonaBehavior)
    skills: list[str] = Field(default_factory=list)
    summon_phrases: list[str] = Field(default_factory=list)


class PersonaPatch(BaseModel):
    name: str | None = None
    job: str | None = None
    model: PersonaModel | None = None
    behavior: PersonaBehavior | None = None
    skills: list[str] | None = None
    summon_phrases: list[str] | None = None


# ── Routes ───────────────────────────────────────────────────────────────────
@router.get("/agents")
async def list_agents():
    """The two trust boundaries and the tools each one grants its personas."""
    return {
        "agents": [
            {
                "id": aid,
                "label": meta["label"],
                "trust": meta["trust"],
                "badge": meta["badge"],
                "tools": _inherited_tools(aid),
            }
            for aid, meta in AGENTS.items()
        ]
    }


@router.get("/personas")
async def list_personas():
    out = []
    for f in sorted(_personas_dir().glob("*.yaml")):
        data = yaml.safe_load(f.read_text()) or {}
        data["id"] = f.stem
        out.append(_hydrate(data))
    return {"personas": out, "dir": str(_personas_dir())}


@router.get("/personas/{persona_id}")
async def get_persona(persona_id: str):
    return _hydrate(_load(persona_id))


@router.post("/personas")
async def create_persona(body: PersonaCreate):
    _reject_tools(body.model_dump())
    if body.agent not in AGENTS:
        raise HTTPException(422, f"agent must be one of {list(AGENTS)}")
    path = _persona_path(body.id)
    if path.exists():
        raise HTTPException(409, f"persona already exists: {body.id}")
    record = body.model_dump()
    record.pop("id", None)  # id is the filename, not stored in body
    path.write_text(yaml.safe_dump(record, sort_keys=False, allow_unicode=True))
    return _hydrate(_load(body.id))


@router.put("/personas/{persona_id}")
async def update_persona(persona_id: str, patch: PersonaPatch):
    _reject_tools(patch.model_dump(exclude_unset=True))
    current = _load(persona_id)
    incoming = patch.model_dump(exclude_unset=True)
    for k, v in incoming.items():
        if k in EDITABLE_FIELDS:
            current[k] = v
    # `agent` binding is deliberately NOT patchable here — re-binding a persona
    # to a different trust boundary silently changes its capabilities, so it
    # must be an explicit delete + recreate.
    stored = {k: v for k, v in current.items() if k != "id"}
    _persona_path(persona_id).write_text(
        yaml.safe_dump(stored, sort_keys=False, allow_unicode=True)
    )
    return _hydrate(_load(persona_id))


@router.delete("/personas/{persona_id}")
async def delete_persona(persona_id: str):
    p = _persona_path(persona_id)
    if not p.exists():
        raise HTTPException(404, f"persona not found: {persona_id}")
    p.unlink()
    return {"deleted": persona_id}
