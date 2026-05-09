FROM node:20-alpine

WORKDIR /app

# Install the official Anthropic-maintained Brave Search MCP server.
# Pinned major version — bump deliberately, not on `npm install` whim.
RUN npm install -g @modelcontextprotocol/server-brave-search@^0.6

# Container idles forever. Hermes spawns the MCP per-session via:
#   docker exec -i safeclaw-brave-search-mcp npx @modelcontextprotocol/server-brave-search
# BRAVE_API_KEY is read from the container environment (set by docker-compose).
CMD ["sh", "-c", "echo 'safeclaw-brave-search-mcp ready (idle)'; tail -f /dev/null"]
