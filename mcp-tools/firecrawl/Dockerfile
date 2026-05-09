FROM node:20-alpine

WORKDIR /app

# Install Firecrawl's official MCP server. Pinned major version.
RUN npm install -g firecrawl-mcp@^1

# Container idles forever. Hermes spawns the MCP per-session via:
#   docker exec -i safeclaw-firecrawl-mcp npx firecrawl-mcp
# FIRECRAWL_API_KEY is read from the container environment (set by docker-compose).
CMD ["sh", "-c", "echo 'safeclaw-firecrawl-mcp ready (idle)'; tail -f /dev/null"]
