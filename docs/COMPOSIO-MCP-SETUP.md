# Composio MCP setup — per customer (operator runbook)

Audience: the operator provisioning a new SafeClaw customer. The customer
never touches this — you do all of it on their behalf, on your machine,
*before* you SSH to the VPS.

Time budget: ~5 minutes once you've done it once.

The output of this whole exercise is **four strings**, which you paste into
the `COMPOSIO_*` env vars when you run `scripts/provision-vps.sh`:

| Var | Looks like |
|-----|------------|
| `COMPOSIO_API_KEY`         | `ak_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx` |
| `COMPOSIO_USER_ID`         | `usr_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx` (or an opaque ID) |
| `COMPOSIO_READER_MCP_URL`  | `https://backend.composio.dev/v3/mcp/<id>/mcp?user_id=<uid>` |
| `COMPOSIO_ACTOR_MCP_URL`   | `https://backend.composio.dev/v3/mcp/<id>/mcp?user_id=<uid>` |

Save them somewhere you can paste from. A `.env`-style scratch file in a
per-customer directory is the cleanest approach — see step 1.

---

## 1. Create a per-customer scratch dir

```bash
mkdir -p ~/safeclaw-customers/<customer-slug>
cd       ~/safeclaw-customers/<customer-slug>
```

Everything in this section runs from that directory. Treat it like a
notebook — keep the four output values in `composio.env` (or whatever) so
you can re-paste later if you re-provision.

---

## 2. `composio dev init`

Install the Composio CLI if you haven't already:

```bash
npm i -g composio-cli@latest
composio --version
```

Initialize the per-customer dev context:

```bash
composio dev init
```

This prompts you for a few things and writes `.composio/` in the current
directory. The most important output is your **API key** — it's also
visible at <https://app.composio.dev/settings/api-keys>.

Capture the values:

```bash
COMPOSIO_API_KEY=$(grep -E '^COMPOSIO_API_KEY=' .composio/.env | cut -d= -f2-)
COMPOSIO_USER_ID=$(grep -E '^COMPOSIO_USER_ID=' .composio/.env | cut -d= -f2-)
echo "$COMPOSIO_API_KEY"
echo "$COMPOSIO_USER_ID"
```

If `composio dev init` doesn't write a `COMPOSIO_USER_ID` directly,
generate or claim one in the dashboard:

1. <https://app.composio.dev> → **Users** → **Add user**.
2. Pick a stable identifier — the customer's email or a UUID. Whatever you
   use here, **save it as `COMPOSIO_USER_ID`** — it embeds into both MCP
   URLs below and into `.env` on the VPS.

---

## 3. Connect the customer's third-party accounts

In <https://app.composio.dev>, with the customer's `user_id` selected:

1. **Tools → Gmail → Connect** — sign in with the customer's Google account.
2. **Tools → Google Calendar → Connect** — same Google account.
3. **Tools → Google Drive → Connect** — same Google account.
4. **Tools → Slack → Connect** — install in their workspace (skip if
   you're using a separately-installed Slack bot via xoxb token, which is
   what the SafeClaw form expects).

Each connection is a one-shot OAuth flow on Composio's side. Composio
holds the tokens and refreshes them. SafeClaw never sees them.

---

## 4. Create the **Reader** MCP server

This is the read-only boundary. The reader Hermes agent can ONLY do these
things — no drafts, no sends, no writes anywhere.

1. Composio dashboard → **MCP Servers** → **Create new**.
2. Name: `safeclaw-reader-<customer-slug>`.
3. User: pick the user_id from step 2.
4. Allowed tools — exactly these four:
   - `GMAIL_FETCH_EMAILS`
   - `GMAIL_FETCH_MESSAGE_BY_THREAD_ID`
   - `GOOGLECALENDAR_FIND_EVENT`
   - `GOOGLEDRIVE_FIND_FILE`
5. Save. Copy the URL — it ends with `/mcp?user_id=<your-user-id>`.

Save it as `COMPOSIO_READER_MCP_URL`.

> Why exactly these four? They're the minimum set that lets the reader
> agent do its job (intake + recall) while keeping the read/write boundary
> clean. Adding more read-only tools is fine; adding any *write* tool here
> defeats the boundary. Don't.

---

## 5. Create the **Actor** MCP server

This is the write side. The actor Hermes agent CAN draft and send through
these — but it explicitly cannot read raw inboxes (that's the reader's
job).

1. Composio dashboard → **MCP Servers** → **Create new**.
2. Name: `safeclaw-actor-<customer-slug>`.
3. User: same user_id as the reader.
4. Allowed tools — exactly these ten:
   - `GMAIL_CREATE_DRAFT`
   - `GMAIL_SEND_DRAFT`
   - `GMAIL_REPLY_TO_THREAD`
   - `GMAIL_MODIFY_LABELS`
   - `GMAIL_CREATE_LABEL`
   - `GOOGLECALENDAR_CREATE_EVENT`
   - `GOOGLECALENDAR_UPDATE_EVENT`
   - `GOOGLECALENDAR_DELETE_EVENT`
   - `GOOGLEDRIVE_CREATE_FILE`
   - `GOOGLEDRIVE_UPDATE_FILE`
5. Save. Copy the URL.

Save it as `COMPOSIO_ACTOR_MCP_URL`.

> The split between Reader and Actor is the security boundary that lets us
> say "a bug in the actor agent cannot exfiltrate the inbox" with a
> straight face. Keep it disciplined.

---

## 6. Write the four values to a per-customer scratch file

```bash
cat > ~/safeclaw-customers/<customer-slug>/composio.env <<EOF
COMPOSIO_API_KEY=${COMPOSIO_API_KEY}
COMPOSIO_USER_ID=${COMPOSIO_USER_ID}
COMPOSIO_READER_MCP_URL='<paste reader URL from step 4>'
COMPOSIO_ACTOR_MCP_URL='<paste actor URL from step 5>'
EOF

chmod 600 ~/safeclaw-customers/<customer-slug>/composio.env
```

These four values go straight into `provision-vps.sh` next.

---

## 7. Hand off to `provision-vps.sh`

SSH to the customer's VPS and source the scratch file before running the
provisioner:

```bash
# On the VPS, after curl-ing provision-vps.sh into /tmp:
set -a
. ./composio.env  # or paste values directly into the env-prefix below
set +a

bash /tmp/provision-vps.sh customer1.safeclaw.com hello@safeclaw.com
```

The script will print:

```
[5/11] Preloading Composio credentials into .env (operator-supplied)
  ✓ .env preloaded with Composio credentials (mode 600)
```

If you forget any of the four, you'll see this instead:

```
  ⚠ COMPOSIO_* env vars not set — webapp will refuse to provision.
```

…in which case re-run with all four set. The webapp's first phase is a
hard preload check; missing keys = an immediate user-facing error pointing
at this doc.

---

## 8. Verify on the VPS

After `provision-vps.sh` finishes:

```bash
ssh root@<customer-domain>
sudo grep '^COMPOSIO_' /opt/safeclaw/.env
```

You should see four lines, each non-empty, no `__FILL_IN__` placeholders.

If you want to spot-check the MCP URLs work, from the VPS:

```bash
curl -fsS -X POST "$COMPOSIO_READER_MCP_URL" \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}' \
  | head -c 400
```

A `result.tools` array of length 4 (Reader) or 10 (Actor) means the URL
+ user_id are wired up right.

---

## Common gotchas

- **`user_id` mismatch.** The user_id in the MCP URL must match the
  user_id you connected Gmail/Drive/Slack under. If they differ,
  `tools/list` returns an empty array and SafeClaw's preload check passes
  but every actual tool call returns "user not authorized."
- **Adding tools after creation.** Composio doesn't always reload the
  MCP server live — if you add a tool and Hermes can't see it, recreate
  the MCP server, copy the new URL, and re-run `provision-vps.sh` (it
  will overwrite the four values in `.env` idempotently).
- **API key expiry.** Composio expires unused keys after ~30 days. If
  the customer's been on a bench for a month and you're re-provisioning,
  regenerate the key first.
- **Reader gets a write tool by accident.** The whole point of the split
  is that a reader-side bug cannot send mail. If you add `GMAIL_SEND_*`
  to the Reader, you've just collapsed the boundary. Don't.

---

## See also

- [`HOSTINGER-DEPLOY.md`](../HOSTINGER-DEPLOY.md) — the full operator runbook.
- [`ARCHITECTURE.md`](../ARCHITECTURE.md) — why the read/write split exists.
- [`SLACK-APP-WALKTHROUGH.md`](./SLACK-APP-WALKTHROUGH.md) — the customer
  side of the bot setup.
