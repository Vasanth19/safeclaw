# Composio MCP setup — 5-minute walkthrough

Audience: **you, the SafeClaw customer**, getting ready to fill in Step 2
of the setup form. This is the same content as the in-form
`/help#composio` page; keep this open in a tab while you run through the
form.

Time budget: ~5 minutes once you've done it once.

The output of this whole exercise is **four strings** which you paste
into Step 2 of the SafeClaw setup form:

| Field | Looks like |
|-------|-----------|
| `COMPOSIO_API_KEY`         | `ak_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx` |
| `COMPOSIO_USER_ID`         | the user_id you connected Gmail / Drive / Slack under |
| `COMPOSIO_READER_MCP_URL`  | `https://backend.composio.dev/v3/mcp/<id>/mcp?user_id=<uid>` |
| `COMPOSIO_ACTOR_MCP_URL`   | `https://backend.composio.dev/v3/mcp/<id>/mcp?user_id=<uid>` |

Why Composio? It holds your Gmail / Drive / Slack OAuth tokens so SafeClaw
never has to. You sign in to Composio with your Google account once,
Composio refreshes the tokens for you, and SafeClaw just calls Composio's
MCP servers when it needs to read mail or send drafts. The OAuth tokens
never touch your VPS.

---

## 1. Sign up at Composio

Open <https://app.composio.dev> and sign up. The free tier is plenty for
getting started.

---

## 2. (Optional) `composio dev init` for the API key

Install the Composio CLI if you haven't already:

```bash
npm i -g composio-cli@latest
composio --version
```

In any local directory on your machine, run:

```bash
composio dev init
```

This writes `.env.local` with your `ak_` API key. The same key is also
visible at <https://app.composio.dev/settings/api-keys>.

Save it as your **`COMPOSIO_API_KEY`** — starts with `ak_`.

> If you skip the CLI, just grab the key from the dashboard at
> `app.composio.dev/settings/api-keys`. Either path lands on the same
> string.

---

## 3. Connect Gmail, Drive, and Slack

In <https://app.composio.dev>:

1. **Tools → Gmail → + Add Connection** — sign in with your Google
   account, complete the OAuth flow.
2. **Tools → Google Drive → + Add Connection** — same Google account.
3. **Tools → Slack → + Add Connection** — install in your workspace.
   (You can skip this if you only want the Slack `xoxb-` token route, but
   most customers connect both.)

When you connect the first one, Composio either uses an existing
`user_id` or creates a new one. Whatever it shows you in the dashboard,
**save it as your `COMPOSIO_USER_ID`** — and use the SAME `user_id` for
all three connections so a single MCP server can reach all of them.

> If `composio dev init` wrote a `COMPOSIO_USER_ID` for you, use that
> one. Otherwise pick a stable identifier (your email or a UUID) and use
> it consistently.

---

## 4. Create the **Reader** MCP server

This is the read-only boundary. The reader Hermes agent can ONLY do these
things — no drafts, no sends, no writes anywhere.

1. Composio dashboard → **MCP Servers** → **Create new**.
2. Name: `safeclaw-reader`.
3. User: pick your `user_id` from step 3.
4. Allowed tools — exactly these three:
   - `GMAIL_FETCH_EMAILS`
   - `GMAIL_LIST_THREADS`
   - `GMAIL_GET_PROFILE`
5. Save. Copy the URL Composio shows you.

**Critical:** Composio's dashboard shows the BASE URL only. You have to
append `/mcp?user_id=<your_user_id>` yourself before pasting it into the
SafeClaw form. The final URL looks like:

```
https://backend.composio.dev/v3/mcp/<mcp-id>/mcp?user_id=<your-user-id>
```

Save it as **`COMPOSIO_READER_MCP_URL`**.

> Why exactly these three tools? They're the minimum set the reader agent
> needs to do its job (intake + recall) while keeping the read/write
> boundary clean. Adding more read-only tools later is fine; adding any
> *write* tool here defeats the boundary. Don't.

---

## 5. Create the **Actor** MCP server

This is the write side. The actor Hermes agent CAN draft and send through
these — but it explicitly cannot read raw inboxes (that's the reader's
job).

1. Composio dashboard → **MCP Servers** → **Create new**.
2. Name: `safeclaw-actor`.
3. User: same `user_id` as the reader.
4. Allowed tools — exactly these seven:
   - `GMAIL_CREATE_EMAIL_DRAFT`
   - `GMAIL_REPLY_TO_THREAD`
   - `SLACK_SEND_MESSAGE`
   - `GOOGLEDRIVE_FIND_FILE`
   - `GOOGLEDRIVE_MOVE_FILE`
   - `GOOGLEDRIVE_UPLOAD_FILE`
   - `GOOGLEDRIVE_CREATE_FOLDER`
5. Save. Copy the URL.

Same rule as before: append `/mcp?user_id=<your_user_id>` to the base URL
before pasting.

Save it as **`COMPOSIO_ACTOR_MCP_URL`**.

> The split between Reader and Actor is the security boundary that lets
> SafeClaw say "a bug in the actor agent cannot exfiltrate the inbox"
> with a straight face. Keep it disciplined.

---

## 6. Paste the four values into Step 2 of the setup form

Open the SafeClaw setup URL (something like
`https://yourname.safeclaw.com/setup`), navigate to **Step 2**, and
paste:

| Form field                  | What you saved             |
|-----------------------------|----------------------------|
| Composio API key            | `COMPOSIO_API_KEY` (step 2) |
| Composio user ID            | `COMPOSIO_USER_ID` (step 3) |
| Reader MCP URL              | `COMPOSIO_READER_MCP_URL` (step 4) |
| Actor MCP URL               | `COMPOSIO_ACTOR_MCP_URL` (step 5) |

Click Next. The webapp validates:

- The API key with one cheap call to `backend.composio.dev/api/v3/toolkits`.
- Each MCP URL by POSTing a `tools/list` JSON-RPC request and checking the
  response has a non-empty tools array.

If something's off, you'll get a per-field error to fix before any
containers boot — no wasted install time.

---

## 7. (Optional) Verify on your own

Want to spot-check the URLs work before pasting? From any terminal:

```bash
curl -fsS -X POST "$COMPOSIO_READER_MCP_URL" \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}' \
  | head -c 400
```

A `result.tools` array of length 3 (Reader) or 7 (Actor) means the URL
+ user_id are wired up right.

---

## Common gotchas

- **`user_id` mismatch.** The user_id in the MCP URL must match the
  user_id you connected Gmail/Drive/Slack under. If they differ,
  `tools/list` returns an empty array and Step 2 will error with
  "no tools — is the user authorized?".
- **Forgot the `/mcp?user_id=` suffix.** The dashboard shows the base
  URL only. Always append the suffix yourself.
- **API key expiry.** Composio expires unused keys after ~30 days. If
  you've been on the bench and the key stops working, regenerate it at
  `app.composio.dev/settings/api-keys`.
- **Reader gets a write tool by accident.** The whole point of the split
  is that a reader-side bug cannot send mail. If you add a write tool
  (e.g. `GMAIL_CREATE_EMAIL_DRAFT`) to the Reader, you've collapsed the
  boundary. Don't.
- **Tools added after MCP creation aren't visible.** Composio doesn't
  always reload the MCP server live. If you add a tool and Hermes can't
  see it, recreate the MCP server, copy the new URL, and re-submit Step
  2 of the form.

---

## See also

- [`CUSTOMER-ONBOARDING.md`](../CUSTOMER-ONBOARDING.md) — the full
  customer onboarding guide (you're partway through it).
- [`SLACK-APP-WALKTHROUGH.md`](./SLACK-APP-WALKTHROUGH.md) — the Slack
  app creation guide (next step after Composio).
- [`ARCHITECTURE.md`](../ARCHITECTURE.md) — why the read/write split
  exists, if you want the deeper rationale.
