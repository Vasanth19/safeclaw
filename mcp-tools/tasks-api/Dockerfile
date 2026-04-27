# SafeClaw tasks-api MCP server.
# Built from the standard Node/TS pattern. Two-stage to keep the runtime image
# small (no devDependencies in the final layer).

FROM node:20-alpine AS builder
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm install
COPY tsconfig.json ./
COPY src/ ./src/
RUN npm run build
RUN npm prune --omit=dev

FROM node:20-alpine
WORKDIR /app
ENV NODE_ENV=production
COPY --from=builder /app/node_modules ./node_modules
COPY --from=builder /app/dist ./dist
COPY --from=builder /app/package.json ./

ENV SAFECLAW_IMAGE_VARIANT=tasks-api
ENV SAFECLAW_IMAGE_VERSION=1.0

CMD ["node", "dist/index.js"]
