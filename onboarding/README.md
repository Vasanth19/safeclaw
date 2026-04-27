# SafeClaw — Onboarding Webapp

Customer-facing setup wizard. Lives at port 80/443 of a customer's Hostinger
VPS (behind Caddy) and provisions the SafeClaw stack in front of them with
SSE progress streaming.

## Stack

* Flask 3 (no framework on the frontend — vanilla JS)
* gunicorn for production, `python app.py` for dev
* In-memory SSE event registry (no Redis dependency — see Decisions)
* Docker CLI inside the container so the webapp can drive `docker compose`

## Local dev

```bash
# From this directory:
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Point the webapp at the SafeClaw repo root (one level up).
SAFECLAW_INSTALL_DIR=$(cd .. && pwd) python app.py
# -> http://localhost:8080
```

The `/api/provision` endpoint will fail to actually run docker commands when
launched outside the container (no docker socket access), but the form
rendering and validation paths all work fine for UI iteration.

## Container build

```bash
cd onboarding
docker build -t safeclaw/onboarding:test .
```

## Running standalone

```bash
docker run --rm -it \
  -p 8080:8080 \
  -v $(pwd)/..:/safeclaw \
  -v /var/run/docker.sock:/var/run/docker.sock \
  safeclaw/onboarding:test
```

## Routes

| Method | Path                   | What |
|--------|------------------------|------|
| GET    | `/`                    | Landing page |
| GET    | `/setup`               | 4-step form |
| GET    | `/help`                | Setup help (Slack walkthrough, troubleshooting) |
| GET    | `/progress/<id>`       | Live progress page |
| GET    | `/done/<id>`           | Success page after a provision |
| POST   | `/api/provision`       | Validates form + starts background install |
| GET    | `/api/progress/<id>`   | SSE stream of phase events |
| GET    | `/api/status/<id>`     | JSON snapshot — polling fallback |
| GET    | `/api/healthz`         | Liveness probe |

## Provision phases

```
validating  -> env_writing -> secrets -> compose_pull -> compose_up
            -> waiting_health -> bootstrap -> welcome -> done
```

Each phase emits a JSON event via SSE:

```json
{"phase": "compose_up", "status": "ok", "message": "Containers are up.", "ts": 1714237194.123}
```

`status` is one of: `start`, `progress`, `ok`, `warn`, `error`.

## Decisions

**Redis vs in-memory SSE: in-memory.** The SafeClaw onboarding webapp runs as
ONE process on ONE customer VPS, with at most a handful of concurrent installs
(typically 1). Adding Redis as a SaaS-on-VPS dependency just to ferry a few
JSON dicts between threads is overkill. The Dockerfile uses gunicorn with
`--threads 4` (NOT extra workers) to keep the in-memory event registry
correct.

If we ever want multi-worker SSE, swap `lib/progress.py` for a Flask-SSE +
Redis backend; the `Install` API is small.

**Validators hit real upstreams.** Each form field is checked against the
upstream API (Composio, Slack, Telegram, the LLM provider's
`/chat/completions`) BEFORE we kick off `docker compose`. Adds 5-10s
latency on submit but surfaces wrong tokens immediately rather than 90s
later from inside a container.

**Atomic .env writes.** `lib/env_writer.py` writes to a temp file in the
same dir, chmods 0600, then renames. No half-written .env, ever.

**Allowlist for env keys.** Only keys in `env_writer.ALLOWED_KEYS` are
accepted from the form. Defends against the form posting arbitrary
environment variables.

**No secrets in error messages.** Validator errors are written by hand
and never include API keys or tokens. Provisioner output is tailed to
the last 800 chars of stdout/stderr (which can include hints from
`docker compose`, never customer secrets, since secrets are in `.env`
not on the command line).

## Files

```
onboarding/
├── README.md
├── Dockerfile
├── requirements.txt
├── app.py                       Flask entry point + routes
├── lib/
│   ├── __init__.py
│   ├── progress.py              In-memory SSE event registry
│   ├── env_writer.py            Atomic .env writer (templated from .env.example)
│   ├── validator.py             Server-side credential validators
│   └── provisioner.py           Phase orchestrator (validate -> up -> bootstrap -> welcome)
├── templates/
│   ├── base.html
│   ├── landing.html
│   ├── setup.html               Multi-step form
│   ├── progress.html            SSE-driven live progress
│   ├── done.html
│   └── help.html                Slack walkthrough + troubleshooting
└── static/
    ├── style.css                SafeClaw dark theme, mobile-friendly
    └── setup.js                 Vanilla JS — step nav, validation, submit
```
