# SafeClaw skill library

Hand-authored, version-controlled Hermes skills. A skill is a markdown
`SKILL.md` (YAML frontmatter + procedure) — **no code**. Hermes loads the
frontmatter cheaply and pulls the full body only when relevant.

```
skills/
└── <skill-name>/
    └── SKILL.md      name, description, requires_toolsets, procedure, pitfalls
```

## Trust-boundary discipline

Each skill states which **boundary** it belongs to:

- **Reader** skills use only read tools (`mcp_slack_native_*` read ops,
  `mcp_safeclaw_brain_*`). No upload, no send.
- **Actor** skills may draft/upload (`mcp_drive_api_*`, Gmail *draft*). Never
  raw send.

A skill never grants a tool the bound agent lacks — capabilities come from the
agent config (`config/{reader,actor}-hermes.yaml`), surfaced and managed via the
**Connections** dashboard plugin. A skill just orchestrates tools the boundary
already has.

## Install (native Hermes)

Hermes discovers skills under `~/.hermes/skills/<category>/<name>/`. Symlink the
library in at provision time:

```bash
mkdir -p ~/.hermes/skills/integrations
for d in skills/*/; do
  ln -s "$PWD/$d" ~/.hermes/skills/integrations/"$(basename "$d")"
done
```

## Skills

| Skill | Boundary | What it does |
|-------|----------|--------------|
| `slack-to-gdrive` | Actor | download Slack attachments → file into Google Drive by project |
| `email-to-brain` | Reader | ingest important Gmail into the brain as deduped summary pages |
| `calendar-to-brain` | Reader | pull Google Calendar through Composio into gbrain daily files |
