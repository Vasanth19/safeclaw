# SafeClaw Personas — dashboard plugin

A Hermes dashboard plugin that turns SafeClaw's Reader/Actor agents into a
**personas**. A persona is a *voice* — a system prompt, model,
tone, skills, and summon phrases — bound to exactly one trust boundary.

## The one rule that makes this sellable as "secure"

> A persona changes how SafeClaw **speaks**, never what it is allowed to **touch**.

Each persona declares an `agent` (`reader` or `actor`) and **inherits that
agent's tool allowlist**. It can never declare its own `tools`. The backend
(`dashboard/plugin_api.py`) rejects any write that includes a `tools` or
`mcp_servers` field with HTTP 422. This preserves the broken-trifecta defense:
a persona can't reunite private-data + untrusted-input + exfiltration, because
it can't grant itself capabilities its boundary doesn't already have.

If a "persona" genuinely needs different capabilities, it is **not a persona —
it's a new trust boundary**. Change the agent config (`config/*-hermes.yaml`)
and re-validate the security split.

## Layout

```
safeclaw-personas/
├── dashboard/
│   ├── manifest.json     plugin manifest (tab at /personas)
│   ├── plugin_api.py     FastAPI router → /api/plugins/safeclaw-personas/
│   └── dist/index.js     UI bundle (plain IIFE on the Hermes Plugin SDK)
└── seed-personas/        example personas (one Reader, one Actor)
```

## Install (native Hermes)

Hermes discovers user plugins in `~/.hermes/plugins/<name>/`. Symlink this
plugin in (keeps the repo as the source of truth):

```bash
ln -s "$PWD/dashboard-plugins/safeclaw-personas" ~/.hermes/plugins/safeclaw-personas
# Seed the two example personas:
mkdir -p ~/.hermes/personas
cp dashboard-plugins/safeclaw-personas/seed-personas/*.yaml ~/.hermes/personas/
```

Then restart the Hermes web dashboard. A **Personas** tab appears after Skills.

## Configuration (env)

| Var | Default | Purpose |
|-----|---------|---------|
| `SAFECLAW_PERSONAS_DIR` | `~/.hermes/personas` | where persona YAMLs live |
| `SAFECLAW_CONFIG_DIR` | repo `config/` | where `reader-hermes.yaml` / `actor-hermes.yaml` live (source of inherited tools) |

## API

| Method | Path | Notes |
|--------|------|-------|
| GET | `/agents` | the two trust boundaries + their tool allowlists |
| GET | `/personas` | all personas, each hydrated with inherited (locked) tools |
| GET | `/personas/{id}` | one persona |
| POST | `/personas` | create — **422 if a `tools` field is present** |
| PUT | `/personas/{id}` | patch voice fields only (agent binding is not patchable) |
| DELETE | `/personas/{id}` | remove |
