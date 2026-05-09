#!/usr/bin/env bash
# prune-skills.sh — strip Hermes' bundled skill packs down to the SafeClaw allowlist.
#
# Runs at image build time inside /opt/hermes/skills/. The Hermes runtime calls
# tools/skills_sync.py at container startup, which discovers SKILL.md files
# under that tree. Anything we delete here will not be synced into the user's
# data volume, so it never inflates session_meta.
#
# Net effect: ~74 skill packs → ~15-20 skill packs.
# Targeted savings: session_meta drops from ~55 KB → ~10 KB per turn.

set -euo pipefail

SKILLS_DIR="${1:-/opt/hermes/skills}"

if [ ! -d "$SKILLS_DIR" ]; then
    echo "prune-skills: $SKILLS_DIR does not exist — nothing to prune." >&2
    exit 0
fi

cd "$SKILLS_DIR"

echo "prune-skills: starting prune in $SKILLS_DIR"
before_count="$(find . -name SKILL.md -not -path '*/.git/*' | wc -l | tr -d ' ')"
before_size="$(du -sk . | awk '{print $1}')"

# ─── Top-level categories to delete entirely ────────────────────────────────
# Each of these is rm -rf'd as a whole. Anything we want to keep from these
# trees needs an explicit re-add below (none currently).
TOP_LEVEL_DELETE=(
    apple
    autonomous-ai-agents
    creative
    diagramming
    dogfood
    domain
    feeds
    gaming
    gifs
    index-cache
    inference-sh
    media
    mlops
    red-teaming
    smart-home
)

for dir in "${TOP_LEVEL_DELETE[@]}"; do
    if [ -d "$dir" ]; then
        echo "  rm -rf skills/$dir"
        rm -rf "./$dir"
    fi
done

# ─── Targeted removals inside otherwise-kept categories ─────────────────────
# research/ is mostly noise (arxiv, polymarket, blogwatcher, llm-wiki). Keep
# only the research-paper-writing pack which is generic-useful.
RESEARCH_DELETE=(
    research/arxiv
    research/blogwatcher
    research/llm-wiki
    research/polymarket
)
for dir in "${RESEARCH_DELETE[@]}"; do
    if [ -d "$dir" ]; then
        echo "  rm -rf skills/$dir"
        rm -rf "./$dir"
    fi
done

# Also drop the now-orphan research/ tree if everything inside got removed
# AND no SKILL.md is left at any depth.
if [ -d research ] && [ -z "$(find research -name SKILL.md -not -path '*/.git/*' 2>/dev/null)" ]; then
    echo "  rm -rf skills/research (empty after prune)"
    rm -rf ./research
fi

# ─── Defensive: nothing else gets dropped ───────────────────────────────────
# We deliberately keep:
#   data-science/        (jupyter-live-kernel — selectively useful)
#   devops/              (webhook-subscriptions)
#   email/               (himalaya — gmail/imap helpers)
#   github/              (full pack — code review, PR workflow, repo mgmt)
#   mcp/native-mcp/      (THE Composio MCP integration)
#   note-taking/obsidian (brain folder is Obsidian format)
#   productivity/        (calendar, google-workspace, notion, linear, maps, pdf, ocr, ppt)
#   social-media/xurl    (per spec — analyze social media)
#   software-development (TDD, plans, debugging — power users)

after_count="$(find . -name SKILL.md -not -path '*/.git/*' | wc -l | tr -d ' ')"
after_size="$(du -sk . | awk '{print $1}')"

echo "prune-skills: SKILL.md count: ${before_count} → ${after_count}"
echo "prune-skills: skills/ size: ${before_size} KB → ${after_size} KB"
echo "prune-skills: done."
