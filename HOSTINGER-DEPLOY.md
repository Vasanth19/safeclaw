# HOSTINGER-DEPLOY.md — SafeClaw Operator Runbook

This is the operator runbook for shipping SafeClaw as a managed service on
Hostinger VPS instances. Audience: Vasanth and any future ops engineer.

If you are a customer who just signed up, you do not need this doc — you
need [`CUSTOMER-ONBOARDING.md`](./CUSTOMER-ONBOARDING.md).

---

## Table of contents

1. [Buying the VPS](#1-buying-the-vps)
2. [Provisioning a customer end-to-end](#2-provisioning-a-customer-end-to-end)
3. [DNS configuration](#3-dns-configuration)
4. [Customer offboarding](#4-customer-offboarding)
5. [Maintenance — daily / weekly / monthly](#5-maintenance--daily--weekly--monthly)
6. [Cost analysis per customer](#6-cost-analysis-per-customer)
7. [Troubleshooting common VPS issues](#7-troubleshooting-common-vps-issues)

---

## 1. Buying the VPS

### Plan recommendation

SafeClaw runs four Postgres clusters, two Hermes agents, an embedder, two MCP
servers, and a Caddy reverse proxy on the same host. The embedder is CPU-only
and the agents idle around ~300 MB each.

| Plan       | vCPU | RAM   | SSD    | Price (intro) | Verdict                            |
| ---------- | ---- | ----- | ------ | ------------- | ---------------------------------- |
| KVM-1      | 1    | 4 GB  | 50 GB  | ~$5/mo        | Too tight — embedder + 2 Hermes choke |
| **KVM-2**  | 2    | 8 GB  | 100 GB | ~$8/mo        | **Default. Use this for every customer.** |
| KVM-4      | 4    | 16 GB | 200 GB | ~$15/mo       | Use only for heavy mailbox volumes (>500 emails/day) |
| KVM-8      | 8    | 32 GB | 400 GB | ~$30/mo       | Multi-mailbox enterprise tier      |

> Hostinger renames the tiers occasionally. The number that matters is **at
> least 2 vCPU, 4 GB RAM, and 80 GB SSD**. KVM-2 (8 GB) gives breathing room.

### Region

Pick the region closest to the customer's office. SafeClaw is latency-sensitive
on three hot paths:

- Slack socket-mode → Hermes-actor (typing indicator, draft latency)
- Hermes → Composio MCP servers (every tool call is a round-trip)
- Hermes → LLM provider (Ollama Cloud / Anthropic / OpenAI)

Hostinger has US East, US Central, UK, NL, IN, BR, SG. Pick the one in the same
continent as the customer.

### What to enable at purchase time

- **OS:** Ubuntu 22.04 LTS (or 24.04 LTS — the script supports both).
- **SSH key:** add yours under hPanel → SSH Keys before provisioning. Do not
  enable password auth.
- **Snapshots:** Hostinger gives one weekly snapshot free per VPS. Turn it on.
- **Backups (paid add-on):** $1.50/mo for daily backups. Worth it for any
  paying customer.
- **Hostname:** match the customer subdomain, e.g. `customer1`. Optional but
  helps when you SSH into multiple boxes.

---

## 2. Provisioning a customer end-to-end

The full flow from "they paid" to "their bot says hello in Slack" is six
steps. Budget 25 minutes total — most of it waiting on DNS propagation and
the customer filling in the form.

### 2.1. Spin up the VPS

1. hPanel → Servers → New VPS → KVM-2, Ubuntu 22.04, region near customer.
2. Set hostname to the customer slug (e.g. `customer1`).
3. Attach your SSH key.
4. Submit. Hostinger boots the box in ~60 seconds.
5. Note the public IPv4 address — you'll need it for the DNS record.

### 2.2. Point a subdomain at the VPS

We use one subdomain per customer under the `safeclaw.com` apex. Pick a slug
that's easy to type — first name, company shortcode, or a number.

In your DNS provider for `safeclaw.com`:

| Record type | Name                   | Value         | TTL  |
| ----------- | ---------------------- | ------------- | ---- |
| A           | `customer1`            | `<vps-ipv4>`  | 300  |

Wait for propagation. From your laptop:

```bash
dig +short customer1.safeclaw.com
# Should print the VPS IPv4. If empty, wait another 60s and retry.
```

> **Do not run the provision script before DNS resolves.** Caddy's first
> Let's Encrypt issuance will fail and rate-limit you for an hour.

See section 3 for full DNS guidance.

### 2.3. SSH in and run `provision-vps.sh`

```bash
ssh root@customer1.safeclaw.com
# (first connection — accept the host key)

# The script lives in the SafeClaw repo. Easiest: curl the bootstrap one-liner.
curl -fsSL https://raw.githubusercontent.com/Vasanth19/safeclaw/main/scripts/provision-vps.sh \
  -o /tmp/provision-vps.sh
bash /tmp/provision-vps.sh customer1.safeclaw.com hello@safeclaw.com
```

The script is idempotent — if anything fails partway, fix the cause and
re-run with the same arguments.

Total runtime on a fresh KVM-2: ~6–8 minutes. Most of it is `apt upgrade` and
`docker compose pull`.

When it finishes you'll see:

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  SafeClaw VPS provisioned for customer1.safeclaw.com
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Send this URL to the customer:
    https://customer1.safeclaw.com/setup
  ...
```

### 2.4. Email the customer

Send the customer the setup URL and a link to
[`CUSTOMER-ONBOARDING.md`](./CUSTOMER-ONBOARDING.md). A canned template:

```
Subject: Your SafeClaw assistant is ready for setup

Hi <name>,

Your dedicated VPS is provisioned and waiting. Click the link below and walk
through the 4-step setup form. It takes 15–20 minutes if you have your
Composio, Slack, and LLM keys handy.

  https://customer1.safeclaw.com/setup

Step-by-step guide:
  https://docs.safeclaw.com/onboarding (mirrors CUSTOMER-ONBOARDING.md)

Need a hand creating the Slack app? The walkthrough is at:
  https://docs.safeclaw.com/slack-app (mirrors docs/SLACK-APP-WALKTHROUGH.md)

Reply to this email if anything's unclear.

— Vasanth
```

### 2.5. Watch the customer submit

When the customer clicks Submit on the form, the onboarding webapp:

1. Validates every credential (Composio reachable, Slack tokens valid, LLM
   responds).
2. Writes the populated `.env` and runs `scripts/init-secrets.sh`.
3. Boots the rest of the stack via `docker compose up -d`.
4. Runs `scripts/bootstrap-brain.sh` (90-day Gmail backfill — ~5 min).
5. Posts a welcome message to the customer's Slack DM.

You can tail their session in real time:

```bash
ssh root@customer1.safeclaw.com
cd /opt/safeclaw
docker compose logs -f onboarding
```

### 2.6. Confirm green and close the loop

```bash
cd /opt/safeclaw
bash scripts/verify-stack.sh --phase 1
docker compose ps
```

All services should be `running (healthy)` except `tasks-api-mcp` and
`brain-api-mcp` which run with `restart: "no"` and are intentionally idle
until Hermes execs into them.

---

## 3. DNS configuration

### Apex setup (one-time, already done)

The `safeclaw.com` zone lives in our DNS provider. Point its NS records at
the provider, set up a CAA record permitting Let's Encrypt:

| Record type | Name | Value                                       | TTL |
| ----------- | ---- | ------------------------------------------- | --- |
| CAA         | `@`  | `0 issue "letsencrypt.org"`                 | 300 |
| CAA         | `@`  | `0 iodef "mailto:hello@safeclaw.com"`       | 300 |

### Per-customer subdomain (every new install)

| Record type | Name        | Value          | TTL |
| ----------- | ----------- | -------------- | --- |
| A           | `<slug>`    | `<vps-ipv4>`   | 300 |

That is the only record needed. No AAAA unless the customer requested IPv6.
No CNAME — Caddy needs to terminate TLS directly on the A record.

### Propagation

300s TTL usually means full propagation in 1–3 minutes. Verify before
running `provision-vps.sh`:

```bash
# From your laptop, not the VPS
dig +short customer1.safeclaw.com
dig +short customer1.safeclaw.com @8.8.8.8
dig +short customer1.safeclaw.com @1.1.1.1
```

All three should return the VPS IPv4. If only some do, wait.

### Wildcard alternative (advanced)

For high-volume operation you can point `*.safeclaw.com` at a single
load-balancer IP and have it route by SNI. Not recommended in v1 — direct
A records are simpler and Let's Encrypt rate-limits are easier to reason
about.

---

## 4. Customer offboarding

When a customer cancels, follow this order. Steps 1–3 must happen before
step 4 — there's no undelete.

### 4.1. Back up their data

```bash
ssh root@customer1.safeclaw.com
cd /opt/safeclaw

# Dump both Postgres clusters and the brain volume.
mkdir -p /tmp/customer1-final-backup
docker compose exec -T postgres-obs \
  pg_dump -U "$POSTGRES_OBS_USER" "$POSTGRES_OBS_DB" \
  > /tmp/customer1-final-backup/obs.sql
docker compose exec -T postgres-tasks \
  pg_dump -U "$POSTGRES_TASKS_USER" "$POSTGRES_TASKS_DB" \
  > /tmp/customer1-final-backup/tasks.sql
tar -czf /tmp/customer1-final-backup/brain.tar.gz brain/

# Pull off-box.
exit
scp -r root@customer1.safeclaw.com:/tmp/customer1-final-backup \
  ~/safeclaw-archives/customer1/
```

Encrypt the archive at rest (`age` or `gpg`) — the brain contains private
emails.

### 4.2. Disconnect Composio integrations

In the Composio dashboard for the customer's user-id:

1. Revoke the Gmail, Drive, Slack, and any other OAuth connections.
2. Delete the Reader and Actor MCP servers.
3. Delete the user record itself if no other product uses it.

This severs Composio's access to the customer's mailbox immediately. Do this
**before** killing the VPS — once the VPS is gone, you can't roll back if the
revoke hits a snag.

### 4.3. Revoke Slack tokens

In `https://api.slack.com/apps`, open the customer's app and either:

- Delete the app outright (clean), or
- Reinstall to revoke the bot/app tokens (keeps audit trail).

### 4.4. Terminate the VPS

```bash
# From hPanel: Servers → customer1 → Manage → Delete
```

Confirm twice. Hostinger zero-fills the disk before reissue. Final invoice
prorates to the day of deletion.

### 4.5. Remove the DNS record

Delete the A record for `customer1.safeclaw.com` from your DNS provider.
Otherwise you have a dangling record pointing at someone else's reissued
VPS — a real concern for cert reissue and phishing.

### 4.6. Update the customer registry

If you're tracking customers in a spreadsheet or Notion: mark the row as
churned, dated, with reason. Future-you will want this.

---

## 5. Maintenance — daily / weekly / monthly

### Daily (automated, no human action)

These are baked in. Verify they're running with `systemctl list-timers` on
each VPS:

| Job                           | Cadence  | Where it lives                         |
| ----------------------------- | -------- | -------------------------------------- |
| Postgres `pg_dump` backups    | 02:00    | host cron → `/var/backups/safeclaw/`   |
| `docker system prune -af`     | 03:00    | systemd timer                          |
| Caddy log rotate              | rolling  | Caddy built-in (`roll_size 10mb`)      |

### Weekly (5 min per customer)

Block out a Monday morning slot. Per VPS:

```bash
ssh root@<customer>.safeclaw.com
cd /opt/safeclaw
df -h | grep -E '/$|/var'   # disk usage; alert if >75%
docker compose ps           # all services healthy
docker compose logs --since 7d hermes-actor | grep -i error | tail
bash scripts/verify-stack.sh --phase 1
```

If `docker system df` shows >5 GB of dangling volumes, run
`docker volume prune -f` (we keep the named volumes by default).

### Monthly (15–30 min total)

1. **Pull image updates.** When the SafeClaw team ships a new release:

   ```bash
   ssh root@<customer>.safeclaw.com
   cd /opt/safeclaw
   git pull
   docker compose pull
   docker compose up -d
   bash scripts/verify-stack.sh --phase 1
   ```

2. **Hermes upstream upgrade** (if pinned tag changed in
   `vendor/hermes-agent`). Rebuild image: `docker compose build hermes-reader`
   then restart hermes-reader and hermes-actor.

3. **Composio toolkit version check.** Composio occasionally adds new tool
   slugs. If an action you use shows up as deprecated in the dashboard,
   migrate before the deprecation date.

4. **Review the security tenets.** Once a quarter, run
   `bash scripts/verify-stack.sh --phase egress` to confirm the iptables
   allowlist still matches `ARCHITECTURE.md`. Any drift = ticket.

5. **Snapshot test restore.** Pick one customer at random, restore their
   weekly snapshot to a throwaway VPS, run `verify-stack.sh`. Either it
   passes or your backups are theatre.

---

## 6. Cost analysis per customer

All numbers are per customer per month, US dollars, as of 2026-04.

### Direct hosting

| Line item                              | Cost          |
| -------------------------------------- | ------------- |
| Hostinger KVM-2 VPS                    | $8.00         |
| Hostinger daily backups add-on         | $1.50         |
| DNS (amortized — your provider)        | ~$0.10        |
| **Subtotal — hosting**                 | **$9.60**     |

### Third-party API costs

These are passed through to the customer if they bring their own keys (BYOK).
If we resell from a master account, mark them up.

| Provider                       | Typical use            | Cost       |
| ------------------------------ | ---------------------- | ---------- |
| Composio (free tier)           | <2k tool calls / mo    | $0         |
| Composio (Pro)                 | 2–10k tool calls       | $20–$50    |
| Ollama Cloud (glm-5.1)         | ~1M tokens/day average | $25        |
| Anthropic Claude Sonnet 4.x    | same volume            | ~$45       |
| OpenAI gpt-4o                  | same volume            | ~$40       |
| Slack (free workspace)         | unlimited bots         | $0         |
| Let's Encrypt cert             | always                 | $0         |
| **Subtotal — APIs (BYOK)**     |                        | **$0**     |
| **Subtotal — APIs (resale)**   |                        | **$45–$95** |

### Operator overhead

Don't forget your time:

| Activity                  | Frequency   | Cost equivalent |
| ------------------------- | ----------- | --------------- |
| Provisioning (one-off)    | once        | ~30 min @ $150/h = $75 (amortize over 12 mo = $6.25/mo) |
| Weekly check (5 min)      | weekly      | ~20 min/mo @ $150/h = $50 |
| Monthly upgrade + tests   | monthly     | ~30 min @ $150/h = $75    |
| Customer support reactive | variable    | budget $25/mo             |
| **Subtotal — labor**      |             | **~$155**                  |

### Putting it together

| Tier                          | Cost to us | Recommended price | Margin |
| ----------------------------- | ---------- | ----------------- | ------ |
| BYOK (customer's keys)        | ~$165      | **$499/mo**       | 3.0x   |
| Managed APIs (Ollama Cloud)   | ~$190      | **$799/mo**       | 4.2x   |
| Managed APIs (Claude)         | ~$210      | **$899/mo**       | 4.3x   |

These numbers assume the customer fits in KVM-2. If they need KVM-4 (>500
emails/day) bump the hosting line by $7 and the price by $100/mo to keep the
margin proportional.

---

## 7. Troubleshooting common VPS issues

### 7.1. Caddy SSL renewal failures

**Symptoms:** `journalctl -u caddy` shows `obtain: ... server returned 4xx`.
Customer reports browser warning.

**Diagnose:**

```bash
journalctl -u caddy -n 200 | grep -E 'error|certificate'
dig +short customer1.safeclaw.com
```

**Fix:** The most common cause is the A record being pointed elsewhere, or
Hostinger blocking outbound port 80 from the VPS (Let's Encrypt HTTP-01
challenge needs both 80 inbound and outbound 80 to acme-v02.api.letsencrypt.org).
Verify `ufw status` shows 80/tcp ALLOW IN. If you're rate-limited, wait 1
hour — duplicate-cert limit is 5 per 7 days per registered domain.

### 7.2. Docker disk fill

**Symptoms:** Services stop, `docker compose ps` shows `Exited (137)`,
`df -h /` shows 100% on `/var/lib/docker`.

**Diagnose:**

```bash
docker system df
du -sh /var/lib/docker/* | sort -rh | head
```

**Fix:**

```bash
docker system prune -af --volumes  # blows away dangling images + unused volumes
# If that's not enough:
docker compose down
docker volume rm $(docker volume ls -q | grep -v safeclaw_)  # keep ours
docker compose up -d
```

If it keeps filling, the culprit is usually unbounded JSON logs. Add to
`/etc/docker/daemon.json`:

```json
{
  "log-driver": "json-file",
  "log-opts": { "max-size": "50m", "max-file": "3" }
}
```

Then `systemctl restart docker && docker compose up -d`.

### 7.3. Hostinger console firewall

Hostinger has a separate firewall in hPanel that runs **in addition** to
ufw. If the customer reports `https://...` hangs but `ssh` works, check
hPanel → Servers → Firewall and confirm 80, 443 are allowed.

### 7.4. Snapshot limits

Hostinger free tier gives 1 snapshot. Taking a new one overwrites the old.
If you're about to do something risky (image upgrade, schema migration),
take the snapshot first, do the work, then either keep or rotate.

### 7.5. Onboarding webapp can't reach Composio

**Symptom:** Customer hits Submit, gets "Composio API not reachable".

**Fix:** From the VPS:

```bash
docker compose exec onboarding curl -fsS https://api.composio.dev/v1/health
```

If that fails, your Hostinger region may be on the wrong side of a transient
Composio outage. Move the customer to a different region (yes, this means
re-provisioning) or wait it out and ask the customer to re-submit.

### 7.6. "Hermes is silent" — bot in Slack but never replies

```bash
docker compose logs --since 1h hermes-reader | tail -50
docker compose logs --since 1h hermes-actor  | tail -50
```

Most common cause: the customer's Ollama Cloud / LLM provider key is wrong
or out of credit. Check the `HERMES_LLM_API_KEY` line in `/opt/safeclaw/.env`.
If the key is right, run:

```bash
docker compose exec hermes-reader curl -fsS \
  -H "Authorization: Bearer $HERMES_LLM_API_KEY" \
  https://api.ollama.com/v1/models | head
```

If that fails, the customer needs to top up their LLM account.

### 7.7. Out of memory — OOM killer claiming containers

**Symptom:** `dmesg | grep -i oom` shows `Out of memory: Killed process ...`.

**Fix:** Either upgrade to KVM-4, or lower Hermes context size. Quick check:

```bash
free -h
docker stats --no-stream
```

If `embedder` is sitting at >2 GB resident, restart it — sentence-transformers
sometimes leaks slowly. Long-term fix: pin the model to a smaller dim.

---

## See also

- [`CUSTOMER-ONBOARDING.md`](./CUSTOMER-ONBOARDING.md) — what we send the
  customer.
- [`docs/SLACK-APP-WALKTHROUGH.md`](./docs/SLACK-APP-WALKTHROUGH.md) — what
  the customer follows when creating their Slack app.
- [`ARCHITECTURE.md`](./ARCHITECTURE.md) — how the security tenets actually
  work.
- [`DEPLOY-RUNBOOK.md`](./DEPLOY-RUNBOOK.md) — the older single-tenant
  runbook (still authoritative for the egress allowlist).
