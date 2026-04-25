# SafeClaw Brain — Human-Readable Layer

This folder is the human-editable side of the SafeClaw Brain. Everything here is
markdown so you can read it, diff it, and own it — no app required.

## What lives here

| Path | Purpose |
| --- | --- |
| `user.soul.md.template` | Starter template for your Soul file. Copy to `user.soul.md` and fill in. |
| `user.soul.md` | Your actual Soul (gitignored — this is the one the brain reads). |
| `entities/` | One markdown file per important entity (people, companies, deals). Optional. |

## How it flows

1. **You write** → edit `user.soul.md` in your editor of choice.
2. **The brain reads** → a future file watcher will sync changes into
   `user_profile.soul_md` on postgres-obs. For now, bootstrap-brain.sh does a
   one-shot load.
3. **Agents read** → `brain_get_soul` (MCP tool on brain-api) returns the JSON
   profile + the markdown body. Both reader and actor have access.

## Layers recap

The Brain has five layers, mirrored between this folder and postgres-obs:

1. **Soul** — identity, entities controlled, markets, style (this folder + `user_profile`).
2. **Preferences** — extracted rules (`preferences` table, proposed by reflector).
3. **Relationships** — entity graph (`entities` + `relationships` + `facts`).
4. **Style** — writing samples (`style_samples`, populated by bootstrap scrape).
5. **Rhythms** — when you work / send / meet (`rhythms`, computed from observations).

Only layer 1 has a human-edited surface here. The others are mostly DB-resident
because they're derived from observation streams.

## Gitignore note

`user.soul.md` is gitignored — it's your real identity and stays on your disk
and in your Postgres. The template is safe to commit.
