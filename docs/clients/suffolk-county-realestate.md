# Suffolk County Real Estate — Client VPS

## Server Access

| Field | Value |
|-------|-------|
| SSH alias | `suffolk-vps` |
| Host | `76.13.188.248` |
| User | `root` |
| SSH key | `~/.ssh/id_ed25519` (after key-copy setup) |
| Credentials | MemPalace `wing_secrets/vps` |

## Project

- **Stack:** SafeClaw AI Assistant (`ai-assistant` repo)
- **GitHub:** https://github.com/Vasanth19/safeclaw.git
- **Deploy path:** `/root/ai-assistant`
- **Compose:** `docker compose up -d`

## Deploy Flow

```bash
# First time
ssh suffolk-vps
git clone https://github.com/Vasanth19/safeclaw.git ai-assistant
cd ai-assistant
cp .env.example .env   # fill secrets
docker compose up -d

# Updates
ssh suffolk-vps 'cd /root/ai-assistant && git pull && docker compose build onboarding && docker compose up -d --no-deps onboarding'
```

## Notes

- Onboarding UI exposed on port 8080 behind Caddy/HTTPS
- See `DEPLOY-RUNBOOK.md` for full first-time setup guide
