# Client OAuth onboarding pages

This folder is the source of truth for the client-facing OAuth setup pages that an admin Hermes agent should create during an Orgo client install.

## Current template

`matt-hoover/` is the first concrete implementation and should be treated as the working template for future clients.

The template pattern is:

1. A static `index.html` with one card per service the client must approve.
2. A server-side Netlify function at `netlify/functions/connect.js` that creates a fresh Composio connected-account link when a card is clicked.
3. No one-time Composio link URLs committed to git.
4. No Composio API keys, OAuth tokens, or client secrets committed to git.

## Admin-agent install behavior

When the admin agent is pointed at a new Orgo installation, it should create these onboarding artifacts as part of provisioning:

1. Create or update the client registry entry.
2. Create an onboarding folder under `admin/client-onboarding/<client_slug>/`.
3. Copy the Matt Hoover structure as the starter template.
4. Replace client-specific labels, slugs, Composio `user_id` values, aliases, and service cards.
5. Include only services that match the client's actual account type.
6. Deploy the onboarding page with a server-side `COMPOSIO_API_KEY` environment variable.
7. Give the employee the hosted page URL for client delivery.
8. Record connected-account status back into the client registry after the human completes OAuth.

## Human-in-the-loop Composio steps

Some Composio setup cannot be safely or reliably automated without a human/operator checkpoint. The admin agent should pause and ask an employee/admin to confirm when any of these are needed:

- Creating or selecting the correct Composio project for the client.
- Choosing account-specific OAuth/auth configs.
- Approving Google OAuth consent screens.
- Confirming which client accounts are personal vs. business/workspace accounts.
- Verifying connected accounts after the client clicks OAuth links.
- Creating Reader/Actor MCP URLs and storing their secret references.

The client should only click hosted OAuth links. They should not need developer dashboard access.

## WhatsApp note

Personal WhatsApp is intentionally excluded from the Matt Hoover onboarding page. The available Composio connector is for WhatsApp Business, so only add WhatsApp when the client actually operates a WhatsApp Business account.

## Future client checklist

For each new client page:

- Update the displayed client name.
- Use `client:<client_slug>:<service>` user IDs.
- Use `<client_slug>-<service>` aliases.
- Remove unsupported services before deploying.
- Keep generated link URLs out of git.
- Set `COMPOSIO_API_KEY` only in the deployment host environment.
- Run `node --check netlify/functions/connect.js` before pushing.
