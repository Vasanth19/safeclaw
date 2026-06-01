# Public access layer (orgo)

orgo gives each computer only a password-gated **desktop** URL — it does **not**
expose app ports to a public HTTPS URL (verified against docs.orgo.ai). To give
each client a clean `https://safeclaw-<name>.<domain>` for self-serve setup +
dashboard, we add two pieces that run **inside** the computer:

```
Internet → https://safeclaw-<name>.<domain>
  → cloudflared  (named tunnel; dials OUT to Cloudflare — no inbound ports)
  → Caddy :8443  (basic-auth / bcrypt — the security gate)
  → Hermes dashboard 127.0.0.1:9119  (UI + plugin APIs + chat + setup tab)
```

The dashboard stays bound to **loopback**. Only the authenticated Caddy is
reachable through the tunnel — defense in depth.

## Files

| File | Purpose |
|------|---------|
| `Caddyfile.example` | basic-auth → reverse proxy to the loopback dashboard |
| `cloudflared-config.yml.example` | named-tunnel ingress (hostname → Caddy) |

## One-time per client (operator)

```bash
# 1. create the tunnel (token mode is simplest)
cloudflared tunnel create safeclaw-acme           # prints a UUID + token

# 2. DNS: safeclaw-acme.<domain>  CNAME  <uuid>.cfargotunnel.com

# 3. credentials → client.env
#    PUBLIC_HOSTNAME=safeclaw-acme.<domain>
#    CLOUDFLARE_TUNNEL_TOKEN=<token>
#    DASHBOARD_AUTH_USER=acme
#    DASHBOARD_AUTH_PASSWORD_HASH=$(caddy hash-password --plaintext '<pw>')
```

## Start (on the box — provision-client.py does this)

```bash
set -a; . orgo/client.env; set +a
envsubst < orgo/access/Caddyfile.example > /etc/caddy/Caddyfile
caddy start --config /etc/caddy/Caddyfile
cloudflared tunnel --no-autoupdate run --token "$CLOUDFLARE_TUNNEL_TOKEN" &
```

Client opens `https://safeclaw-acme.<domain>` → logs in → **Setup** /
**Connections** tabs to upload tokens; everything auto-configures (see
`orgo/setup/apply.py`).

## Stronger auth (optional)

Swap Caddy basic-auth for **Cloudflare Access** (edge SSO / email-OTP, no
password to share) — add an Access policy on the hostname and drop the
`basic_auth` block. Recommended for production client-facing deployments.
