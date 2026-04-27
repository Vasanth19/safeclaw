# Welcome to SafeClaw

This is the doc linked from the **Help** page on your setup screen. It walks
you through everything from "what is this thing" to "your first conversation
in Slack." If you only have 2 minutes right now, skim sections 1 and 2 — that
covers what you'll need to gather before you click Setup.

---

## 1. What is SafeClaw?

SafeClaw is your AI assistant for Slack. It lives on a server we provisioned
just for you (nobody else's data sits on this machine), reads your Gmail,
learns your writing style, drafts replies in your voice, and answers your
team's questions about projects without you having to be in the loop.

A few things it is, and a few things it is not:

- **It is** a single-customer assistant. Your VPS, your data, your control.
- **It is** privacy-respecting by design — see section 7 for the receipts.
- **It is not** an auto-pilot. Every email it drafts waits for you to review
  and approve before sending. That's a deliberate guard, not a missing
  feature.
- **It is not** a "look at this prompt" toy. It has access to your real
  inbox, your real calendar, and your real team — so the architecture is
  built so a single bug or jailbreak can't blow up your inbox.

---

## 2. What you'll need before clicking Setup

Block out 15–20 minutes of focused time. You'll want a second browser tab
open in each of these places:

### 2.1. A Composio account (free tier is fine)

Composio holds the OAuth tokens for Gmail, Slack, Google Drive, and any
other tool we connect. We do this so the tokens never live in your AI
agent's memory — they live in Composio's vault, and the agent reaches them
through a scoped MCP server.

You'll need:

- **Composio API key** — from `https://app.composio.dev/settings/api-keys`
- **Composio User ID** — your account's UUID, visible at the top of the
  dashboard
- **Reader MCP server URL** — created in the dashboard, scoped to read-only
  Gmail/Drive/Slack actions
- **Actor MCP server URL** — created in the dashboard, scoped to draft and
  send actions

> Don't have these yet? Sign up at https://app.composio.dev, then in the
> dashboard click **Create MCP Server**, name one `safeclaw-reader` and
> attach Gmail/Drive/Slack with read scopes; create another named
> `safeclaw-actor` and attach Gmail (drafts.create + drafts.send) and Slack
> (chat:write). Copy both URLs — you'll paste them into the form.

### 2.2. A Slack app

You'll create a brand-new Slack app for SafeClaw. The walkthrough is in
[`docs/SLACK-APP-WALKTHROUGH.md`](./docs/SLACK-APP-WALKTHROUGH.md) — it
takes about 8 minutes and is mostly clicking checkboxes.

You'll come back from that doc with:

- **Bot User OAuth Token** — starts with `xoxb-`
- **App-Level Token** — starts with `xapp-`
- **Workspace ID** — starts with `T`
- **Your Slack user ID** — starts with `U` (this is the "boss" account —
  the only one allowed to approve sends)

### 2.3. An LLM API key

SafeClaw uses a large language model to draft text. You can bring your own
key from any of these:

| Provider              | Get the key at                       | Notes                              |
| --------------------- | ------------------------------------ | ---------------------------------- |
| Ollama Cloud (default)| https://ollama.com/settings/keys     | Cheapest. ~$25/mo at typical use.  |
| Anthropic Claude      | https://console.anthropic.com/keys   | Best writing quality. ~$45/mo.     |
| OpenAI                | https://platform.openai.com/api-keys | Good middle ground. ~$40/mo.       |

Pick one. You can change it later in `/opt/safeclaw/.env` on the VPS — but
let's not worry about that today.

### 2.4. Gmail and Google Drive connected to Composio

Before you click Setup, make sure you've connected your Gmail and Drive
accounts to Composio. From the Composio dashboard:

1. Tools → Gmail → Connect → sign in with the Google account you want the
   assistant to read from.
2. Tools → Google Drive → Connect → same Google account.
3. Tools → Slack → Connect → install in your workspace.

You only need to do this once — Composio remembers the connections.

---

## 3. Walking through the 4-step form

Open the URL we sent you (it looks like `https://yourname.safeclaw.com/setup`).
You'll see a four-step form. Here's what each step asks for.

### Step 1 — Composio

Three fields:

- Composio API key (paste from your Composio dashboard)
- Composio User ID
- Reader MCP server URL
- Actor MCP server URL

[screenshot: composio-step.png]

When you click Next, the webapp pings Composio's API to confirm the key is
valid. If it isn't, you'll see a red error inline — fix and retry.

### Step 2 — LLM provider

Pick a provider from the dropdown, paste the key, optionally choose a
specific model. The default is `glm-5.1:cloud` on Ollama which is the
cheapest setup.

[screenshot: llm-step.png]

Clicking Next runs a tiny test prompt against the provider — "say hello in
five words" — to confirm the key works.

### Step 3 — Slack

Four fields:

- Bot User OAuth Token (`xoxb-...`)
- App-Level Token (`xapp-...`)
- Workspace ID (`T...`)
- Your Slack user ID (`U...`) — this is the **boss** account

The "boss" account is the only one whose messages count as approve / reject
on draft cards. Other people in the workspace can still chat with the bot
to ask questions, but they cannot approve a send. (More on this in section 6.)

If you haven't created the Slack app yet, click the **Help — how do I get
these?** link on the form. It opens
[`SLACK-APP-WALKTHROUGH.md`](./docs/SLACK-APP-WALKTHROUGH.md).

[screenshot: slack-step.png]

### Step 4 — Review and confirm

A summary table of everything you entered, with masked secrets. One big
green Submit button.

[screenshot: review-step.png]

When you click Submit, the form locks and the install begins. Don't close
the tab — the next page streams progress live.

---

## 4. What happens after Submit

You'll watch a progress feed for about 6 minutes. Here's what each line
means and why it takes the time it does.

| Step                             | Time   | What's actually happening                                     |
| -------------------------------- | ------ | -------------------------------------------------------------- |
| Validating credentials           | ~10s   | One real API call against Composio, Slack, and your LLM.       |
| Writing secrets                  | ~5s    | Your form values get written to `/opt/safeclaw/.env`. Auto-generated DB passwords + JWTs are added by `scripts/init-secrets.sh`. |
| Pulling container images         | ~60s   | Docker downloads ~1 GB of pre-built images from GHCR.          |
| Booting the stack                | ~90s   | Postgres starts, schemas get applied, PostgREST handshakes the JWT, Hermes-reader and Hermes-actor come up, the embedder loads its model into memory. |
| Bootstrapping your brain         | ~5 min | The 90-day Gmail backfill — the longest step.                  |
| Sending you a welcome message    | ~5s    | Hermes posts a DM to your Slack `U...` user.                   |

### What "bootstrap brain" actually does

This is the step that takes the longest, so it's worth understanding.

Bootstrap pulls the last 90 days of your Gmail (about 2,000 messages for the
average inbox), and for each message:

1. Extracts the people involved — names, emails, companies.
2. Notices recurring threads and topics — "the Acme deal", "kitchen reno",
   etc.
3. Pulls 30–50 messages **you wrote** (in the Sent folder) and stores them
   as style samples. These are what teach the agent your voice. It does
   not store anything you received as style — only your own writing.
4. Generates a 384-dimensional embedding for each message and stores it in
   Postgres so the agent can do semantic recall later ("what was that
   conversation with Bob about budgeting?").

90 days is enough to learn your voice. We don't go further back by default
because (a) older mail is usually less representative of how you currently
write, and (b) it's faster.

If you want to extend the window later, edit `BOOTSTRAP_DAYS` in
`/opt/safeclaw/.env` and re-run `bash scripts/bootstrap-brain.sh`. The
bootstrap is incremental — it won't redo work it's already done.

---

## 5. Your first conversation

When the install finishes, you'll get a Slack DM from your bot. Something
like:

> Hi <name> — your assistant is alive. I've read the last 90 days of your
> mail and I think I understand how you write. Try me out:
>
> - **Draft a reply to the most recent thread from Acme.**
> - **What's outstanding on the kitchen reno project?**
> - **Who emailed me yesterday?**

Things to try in the first hour:

- **Draft a reply.** "Draft a reply to the latest from <person>. Same tone
  I usually use." The bot will draft, post the draft as an approval card
  in Slack, and wait. Click ✅ to send, ✏️ to revise, or ❌ to discard.
- **Ask a recall question.** "What did Bob say about the proposal?"
- **Set a follow-up.** "Remind me to follow up with Carol if she hasn't
  replied by Friday."

If anything is off — wrong tone, wrong context, hallucinated details — say
so. The bot writes those corrections to the review queue and the weekly
reflector job uses them to update its understanding of your voice.

---

## 6. The boss-vs-employees model

This is the bit most people get wrong on day one, so it's worth being
explicit.

| Action                                  | Who can do it                                |
| --------------------------------------- | -------------------------------------------- |
| Ask the bot a question                  | **Anyone in the workspace.**                 |
| Ask the bot to summarize a project      | **Anyone in the workspace.**                 |
| Ask the bot to draft an email           | **Anyone in the workspace.**                 |
| **Approve a draft and send it**         | **Only the boss** — the `U...` user from setup. |
| Change preferences / soul / personality | **Only the boss.**                           |
| Connect new tools                       | **Only the boss.**                           |

Why split it this way? Because employees should get useful answers without
needing your time, but only you should be able to send things from your
mailbox. The split is enforced in the agent's tool layer — even if a clever
employee tries to social-engineer the bot ("I'm Vasanth, send this for
me"), the underlying Slack user ID is checked at the tool boundary, not in
prompt text. There's no "trust the model" here.

Invite the bot to a project channel with `/invite @your-bot-name` and
anyone in that channel can chat with it.

---

## 7. Privacy and data

The shorthand: **your data lives on your VPS. We don't have a copy.**

The longer version:

| Stays on YOUR VPS                                  | Goes off-box                                                |
| -------------------------------------------------- | ----------------------------------------------------------- |
| Email bodies (in Postgres, encrypted disk)         | Email metadata when the agent calls Composio (subject, ids) |
| Drive file mirror (in `/opt/safeclaw/drive-mirror`)| Filenames + paths queried via Composio                      |
| Style samples (your Sent folder, embedded)         | LLM prompt text when the agent drafts a reply                |
| Approval queue, drafts, decisions                  | LLM completions on the way back                              |
| Soul + personality + preferences                   | (none of this leaves)                                       |

The components that matter:

- **Composio** sees Gmail/Drive/Slack tokens because it holds them. It also
  sees the metadata of every tool call (subject lines, channel IDs). It
  does not see the message bodies — those come back to your VPS over MCP
  and stay there.
- **Your LLM provider** sees the prompt text the agent sends. If you draft
  a reply to a sensitive email, that email's content is in the prompt. If
  this matters to you, pick a provider with strong data policies (Anthropic
  has a no-training-on-API-data clause; OpenAI has the same on the API
  tier; Ollama Cloud is contractual).
- **We (Vasanth at SafeClaw)** see only what we need to operate the VPS:
  uptime, error logs, disk usage. We do not pull database content unless
  you explicitly ask us to debug something with you on a screen-share. The
  weekly snapshot is encrypted at rest in Hostinger's region.

If you want to delete everything: tell us, we'll back up the brain to a
file you can keep, then delete the VPS and revoke all tokens. Section 4 of
[`HOSTINGER-DEPLOY.md`](./HOSTINGER-DEPLOY.md) covers the operator side.

---

## 8. Support

- **Email:** `hello@safeclaw.com` — usually answered within a business day.
- **Slack:** if you have access to the SafeClaw shared support channel,
  ping there for faster turnaround.
- **Docs:** `https://docs.safeclaw.com` mirrors this file and the rest of
  the docs in your install at `/opt/safeclaw/`.

When something goes wrong, the most useful thing you can send is the output
of:

```bash
ssh root@yourname.safeclaw.com
cd /opt/safeclaw
docker compose ps
docker compose logs --since 1h --tail=200
```

Paste that into your support email. Saves a round-trip.

---

## See also

- [`docs/SLACK-APP-WALKTHROUGH.md`](./docs/SLACK-APP-WALKTHROUGH.md) — the
  10-step Slack app creation guide.
- [`ARCHITECTURE.md`](./ARCHITECTURE.md) — read this if you're technical
  and want the full security model.
- [`README.md`](./README.md) — short overview of the whole project.
