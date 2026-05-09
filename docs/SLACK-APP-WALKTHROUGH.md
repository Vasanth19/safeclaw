# Slack App Walkthrough — Creating Your SafeClaw Bot

This is the 10-step guide for creating the Slack app that powers your
SafeClaw assistant. It's the doc linked from Step 3 ("Slack") of the setup
form, and from section 2.2 of
[`CUSTOMER-ONBOARDING.md`](../CUSTOMER-ONBOARDING.md).

Plan ~8 minutes. You'll come out the other side with four strings to paste
into the setup form:

- `xoxb-...` — Bot User OAuth Token
- `xapp-...` — App-Level Token
- `T...` — Workspace ID
- `U...` — Your Slack user ID

> **Heads up — two different tokens.** Slack has a Bot Token (`xoxb-`) and
> an App-Level Token (`xapp-`). They are not interchangeable. SafeClaw needs
> both, in different fields. We'll create them in steps 4 and 8 below.

---

## Step 1 — Create the app

Go to [`https://api.slack.com/apps`](https://api.slack.com/apps) and click
**Create New App**. Pick **From scratch** (not from a manifest).

[screenshot: 01-create-app.png]

> If you've never used the Slack developer site before, you'll be asked to
> sign in with your workspace. Use the workspace where you want SafeClaw
> installed.

---

## Step 2 — Name it and pick the workspace

Two fields:

- **App Name** — something like `Carol's Assistant` or `Acme Bot`. This is
  what shows up in Slack's app directory and as the username when the bot
  posts.
- **Workspace** — the Slack workspace to install into. Must be a workspace
  where you're an admin or have permission to install apps.

Click **Create App**.

[screenshot: 02-name-workspace.png]

You'll land on the app's "Basic Information" page. Keep this tab open —
you'll come back for the App-Level Token in step 4.

---

## Step 3 — Bot Token Scopes

Left sidebar → **OAuth & Permissions**. Scroll down to **Scopes** →
**Bot Token Scopes**.

Click **Add an OAuth Scope** and add **all** of the following. Order
doesn't matter, but missing any one will break a feature.

```
app_mentions:read
channels:history
channels:read
chat:write
chat:write.public
commands
groups:history
groups:read
im:history
im:read
im:write
mpim:history
mpim:read
reactions:read
reactions:write
users:read
users:read.email
```

[screenshot: 03-scopes.png]

What each one is for, in plain English:

| Scope                  | Why SafeClaw needs it                                          |
| ---------------------- | -------------------------------------------------------------- |
| `app_mentions:read`    | Hear when someone @-mentions the bot.                          |
| `channels:history`     | Read public-channel message history (for context).             |
| `channels:read`        | List public channels.                                          |
| `chat:write`           | Send messages.                                                 |
| `chat:write.public`    | Post in channels the bot isn't a member of (for approvals).    |
| `commands`             | Register slash commands (`/safeclaw-help`).                    |
| `groups:history`       | Read private-channel messages it's been invited to.            |
| `groups:read`          | List private channels.                                         |
| `im:history`           | Read DMs sent to the bot.                                      |
| `im:read`              | List DM conversations.                                         |
| `im:write`             | Open a DM with you (for the welcome message and approvals).    |
| `mpim:history`         | Read multi-person DMs the bot is in.                           |
| `mpim:read`            | List multi-person DMs.                                         |
| `reactions:read`       | See your ✅ / ❌ reactions on draft cards.                      |
| `reactions:write`      | Add its own reactions to acknowledge.                          |
| `users:read`           | Resolve user IDs to names.                                     |
| `users:read.email`     | Match Slack users to Gmail addresses.                          |

> **Don't add Slack User scopes.** SafeClaw is bot-token only. User scopes
> would let it act as you in Slack, which we deliberately don't want.

---

## Step 4 — Enable Socket Mode and create the App-Level Token

Left sidebar → **Socket Mode**. Toggle **Enable Socket Mode** on.

It'll prompt you to create an App-Level Token. Give it any name (`socket`
is fine) and add the scope `connections:write`.

[screenshot: 04-socket-mode.png]

Slack shows you a token starting with `xapp-`. **Copy it now and stash it
somewhere safe** — Slack won't show it again. (You can regenerate later if
you lose it, but it's a hassle.)

This is the **App-Level Token** field on the SafeClaw setup form.

> **Why Socket Mode?** Socket Mode lets the bot connect outbound to Slack
> over a websocket, so we don't need to expose an inbound webhook URL on
> your VPS. It also means Slack events arrive instantly rather than through
> a queued HTTP retry loop. SafeClaw uses Socket Mode by default.

> **App-Level Token vs Bot Token — they are different.**
> The App-Level Token (`xapp-`) is a workspace-level credential that lets
> the app open the websocket. The Bot Token (`xoxb-`) is what the bot uses
> to call Slack APIs (post messages, read channels, etc). You need both.

---

## Step 5 — Event Subscriptions

Left sidebar → **Event Subscriptions**. Toggle **Enable Events** on.

> You may see a "Request URL" field. **Leave it blank** — Socket Mode
> bypasses the request-URL flow. If Slack complains, double-check that
> Socket Mode is on (step 4).

Scroll down to **Subscribe to bot events** and add these five:

```
app_mention
message.channels
message.groups
message.im
message.mpim
```

[screenshot: 05-event-subscriptions.png]

What they each do:

| Event              | When it fires                                              |
| ------------------ | ---------------------------------------------------------- |
| `app_mention`      | Someone @-mentions the bot.                                |
| `message.channels` | Any message in a public channel the bot is a member of.    |
| `message.groups`   | Any message in a private channel the bot is in.            |
| `message.im`       | Any DM to the bot.                                         |
| `message.mpim`     | Any message in a multi-person DM the bot is in.            |

Click **Save Changes** at the bottom of the page. (Slack is picky about
this — it won't apply until you click save.)

---

## Step 6 — Slash commands (optional but recommended)

Left sidebar → **Slash Commands** → **Create New Command**.

Create two:

**Command 1**

| Field           | Value                                                            |
| --------------- | ---------------------------------------------------------------- |
| Command         | `/safeclaw-help`                                                 |
| Request URL     | Leave blank (Socket Mode handles it)                             |
| Short Desc      | `Show what SafeClaw can do`                                      |
| Usage Hint      | (blank)                                                          |

**Command 2**

| Field           | Value                                                            |
| --------------- | ---------------------------------------------------------------- |
| Command         | `/safeclaw-status`                                               |
| Request URL     | Leave blank                                                      |
| Short Desc      | `Show pending drafts and recent activity`                        |
| Usage Hint      | (blank)                                                          |

[screenshot: 06-slash-commands.png]

You can skip this step entirely — the bot still works through @-mentions
and DMs. The slash commands are just shortcuts.

---

## Step 7 — App Home

Left sidebar → **App Home**. Two things to enable:

1. Toggle **Show Tabs → Messages Tab** on.
2. Check **Allow users to send Slash commands and messages from the
   messages tab**.

[screenshot: 07-app-home.png]

This is what makes the bot appear under "Apps" in your Slack sidebar so you
can DM it directly. Without this, you'd have to invite it to a channel
every time.

---

## Step 8 — Install to Workspace and grab the Bot Token

Left sidebar → **Install App** (top of the sidebar) → **Install to
Workspace**. Slack will show the permissions screen — verify the scopes
listed match step 3, then click **Allow**.

[screenshot: 08-install-app.png]

After installing, you'll see **Bot User OAuth Token** at the top of the
page, starting with `xoxb-`. Copy it.

This is the **Bot User OAuth Token** field on the SafeClaw setup form.

> **Reinstall after scope changes.** If you go back later and add or remove
> scopes from step 3, you have to come back here and click **Reinstall to
> Workspace**, otherwise the new scopes don't take effect.

---

## Step 9 — Invite the bot to channels

Open Slack. In each channel where you want the bot to listen and respond,
type:

```
/invite @your-bot-name
```

(Replace `your-bot-name` with whatever you named the app in step 2.)

You don't have to invite it everywhere. A common starting point:

- `#general` — so the bot can answer team questions
- A DM with yourself (just message it directly)
- One or two project channels

> **The bot only sees what it's invited to.** If you didn't invite it to
> `#exec-only`, it can't read messages there. Slack's permission model is
> the gate — SafeClaw doesn't override it.

---

## Step 10 — Copy the IDs you'll need on the form

Three IDs go on the setup form: workspace, your user, and (later)
channels.

### Workspace ID

In Slack, click your workspace name (top-left) → **Settings &
administration** → **Workspace settings**. The URL bar now shows something
like `https://yourworkspace.slack.com/admin/settings`. The Workspace ID
is on that page under "Workspace ID" — starts with `T`.

[screenshot: 10a-workspace-id.png]

Alternative: in any Slack web URL like
`https://app.slack.com/client/T01ABCD2EF/C03GHIJ4KL`, the `T...` segment is
your workspace ID.

### Your user ID (the boss)

In Slack, click your own name/avatar (top-right) → **Profile** → **⋯
(more)** → **Copy member ID**. Starts with `U`.

[screenshot: 10b-user-id.png]

This is the user that gets approval rights. Pick **your** user — not your
team's. SafeClaw uses this ID, not your name or email, to enforce who can
approve sends.

### Channel IDs (only needed later, for routing rules)

Right-click a channel in Slack → **Copy link**. The URL ends in `/Cxxxxx`.
The `C...` is the channel ID. You'll only need this if you're setting up
custom routing rules ("forward escalations from #urgent to my DM" etc).
Skip for the first install.

---

## Recap — what you should have now

Four strings ready to paste into Step 3 of the SafeClaw setup form:

| Field                       | Looks like           | Where it came from                  |
| --------------------------- | -------------------- | ----------------------------------- |
| Bot User OAuth Token        | `xoxb-1234-...`      | Step 8 (Install App page)           |
| App-Level Token             | `xapp-1-...`         | Step 4 (Socket Mode)                |
| Workspace ID                | `T01ABCD2EF`         | Step 10 (Workspace settings)        |
| Your Slack user ID (boss)   | `U07XYZW8VW`         | Step 10 (Your profile → member ID)  |

Switch back to the SafeClaw setup tab, paste them in, and click Next.

---

## Troubleshooting

### "invalid_auth" when SafeClaw boots

You probably swapped the Bot Token and the App-Level Token. The Bot Token
goes in the `xoxb-` field; the App-Level Token in the `xapp-` field.

### The bot is online but never responds

Check that:

1. Socket Mode is enabled (step 4).
2. Event Subscriptions is on AND has the five bot events (step 5).
3. You clicked **Save Changes** at the bottom of the Event Subscriptions
   page — it doesn't auto-save.
4. The bot is invited to the channel where you're @-mentioning it.

### "missing_scope" error in Slack

You added a feature that needs a scope you don't have yet. Go back to step
3, add the missing scope, then go to step 8 and **reinstall** the app. The
reinstall is the bit people forget.

### The bot answers everyone, not just me

That's expected — anyone in a channel where the bot is invited can chat
with it. **Only the boss user (`U...` from step 10) can approve sends.**
The split is by design — see section 6 of
[`CUSTOMER-ONBOARDING.md`](../CUSTOMER-ONBOARDING.md) for details.

### I lost the App-Level Token

Go back to **Basic Information** → **App-Level Tokens** → click the token
name → **Regenerate**. You'll need to update the SafeClaw `.env` and
restart Hermes:

```bash
ssh root@yourname.safeclaw.com
cd /opt/safeclaw
nano .env   # update SLACK_APP_TOKEN=xapp-...
docker compose restart hermes-actor hermes-reader
```

---

## See also

- [`CUSTOMER-ONBOARDING.md`](../CUSTOMER-ONBOARDING.md) — the full new-user
  guide.
- Slack's official docs: [`https://api.slack.com/start`](https://api.slack.com/start).
- Socket Mode reference: [`https://api.slack.com/apis/connections/socket`](https://api.slack.com/apis/connections/socket).
