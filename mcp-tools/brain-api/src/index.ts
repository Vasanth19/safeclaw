/**
 * SafeClaw Brain API — MCP Server
 *
 * Exposes 4 tools over stdio transport:
 *   - brain_recall               (semantic search across observations + facts)
 *   - brain_write                (upsert entity + append fact)
 *   - brain_get_soul             (return Soul markdown + structured profile)
 *   - brain_list_relationships   (graph neighborhood for an entity)
 *
 * Required environment variables:
 *   DATABASE_URL   postgres connection string for postgres-obs
 *   EMBEDDER_URL   e.g. http://embedder:8000
 */

import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import {
  CallToolRequestSchema,
  ListToolsRequestSchema,
} from "@modelcontextprotocol/sdk/types.js";
import pg from "pg";
import { z } from "zod";

// ── Environment ───────────────────────────────────────────────────────────────

const DATABASE_URL = process.env["DATABASE_URL"];
const EMBEDDER_URL = process.env["EMBEDDER_URL"] ?? "http://embedder:8000";
const DEFAULT_USER_KEY = process.env["BRAIN_USER_KEY"] ?? "primary";

if (!DATABASE_URL) {
  process.stderr.write("FATAL: DATABASE_URL environment variable is required\n");
  process.exit(1);
}

// ── Postgres pool ────────────────────────────────────────────────────────────

const pool = new pg.Pool({
  connectionString: DATABASE_URL,
  max: 4,
  idleTimeoutMillis: 30_000,
});

pool.on("error", (err) => {
  process.stderr.write(`postgres pool error: ${err.message}\n`);
});

// ── Types ─────────────────────────────────────────────────────────────────────

interface ToolError {
  code: string;
  message: string;
  details: unknown;
  hint: string | null;
}

function toolResult(
  ok: boolean,
  status: number,
  data: unknown
): { content: Array<{ type: "text"; text: string }> } {
  return {
    content: [
      { type: "text", text: JSON.stringify({ ok, status, data }, null, 2) },
    ],
  };
}

function errorResult(
  status: number,
  error: ToolError
): ReturnType<typeof toolResult> {
  return toolResult(false, status, error);
}

function vectorLiteral(embedding: readonly number[]): string {
  // pgvector accepts '[0.12,0.34,...]'. Clamp precision for determinism.
  return `[${embedding.map((n) => Number(n).toFixed(6)).join(",")}]`;
}

// ── Embedder client ───────────────────────────────────────────────────────────

async function embedText(text: string): Promise<number[]> {
  let response: Response;
  try {
    response = await fetch(`${EMBEDDER_URL}/embed`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
    });
  } catch (err: unknown) {
    const message = err instanceof Error ? err.message : String(err);
    throw new Error(`embedder unreachable at ${EMBEDDER_URL}: ${message}`);
  }

  if (!response.ok) {
    const body = await response.text();
    throw new Error(`embedder returned ${response.status}: ${body.slice(0, 200)}`);
  }

  const data = (await response.json()) as { ok?: boolean; embedding?: unknown };
  if (data.ok !== true || !Array.isArray(data.embedding)) {
    throw new Error("embedder returned malformed payload");
  }
  return data.embedding.map((n) => Number(n));
}

// ── Input Schemas ─────────────────────────────────────────────────────────────

const RecallSchema = z.object({
  query: z.string().min(1).max(2000),
  kinds: z.array(z.enum(["observations", "facts"])).optional(),
  limit: z.number().int().min(1).max(50).optional().default(10),
});

const EntityKindEnum = z.enum(["person", "company", "property", "deal", "vehicle", "other"]);

const WriteSchema = z.object({
  entity_name: z.string().min(1).max(200),
  entity_kind: EntityKindEnum,
  fact: z.string().min(1).max(2000),
  source: z.string().min(1).max(500),
});

const GetSoulSchema = z.object({
  user_key: z.string().min(1).max(200).optional(),
});

const ListRelationshipsSchema = z.object({
  entity_name: z.string().min(1).max(200),
});

// ── Tool Implementations ──────────────────────────────────────────────────────

interface RecallRow {
  kind: "observation" | "fact";
  id: string;
  text: string;
  distance: number;
  metadata: Record<string, unknown>;
}

async function recall(rawInput: unknown): Promise<ReturnType<typeof toolResult>> {
  const parsed = RecallSchema.safeParse(rawInput);
  if (!parsed.success) {
    return errorResult(400, {
      code: "VALIDATION_ERROR",
      message: "Invalid input",
      details: parsed.error.flatten(),
      hint: null,
    });
  }

  const { query, limit } = parsed.data;
  const kinds = parsed.data.kinds ?? ["observations", "facts"];

  let embedding: number[];
  try {
    embedding = await embedText(query);
  } catch (err: unknown) {
    const message = err instanceof Error ? err.message : String(err);
    return errorResult(503, {
      code: "EMBEDDER_UNAVAILABLE",
      message,
      details: null,
      hint: "Verify the embedder container is running and EMBEDDER_URL is reachable.",
    });
  }

  const vec = vectorLiteral(embedding);
  const merged: RecallRow[] = [];
  const client = await pool.connect();
  try {
    if (kinds.includes("observations")) {
      const obs = await client.query<{
        id: string;
        subject: string | null;
        summary: string | null;
        sender: string | null;
        inbox: string | null;
        received_at: string | null;
        distance: string;
      }>(
        `SELECT o.id,
                o.subject,
                o.summary,
                o.sender,
                o.inbox,
                o.received_at,
                (e.embedding <=> $1::vector) AS distance
           FROM observation_embeddings e
           JOIN observations o ON o.id = e.observation_id
          ORDER BY e.embedding <=> $1::vector
          LIMIT $2`,
        [vec, limit]
      );
      for (const row of obs.rows) {
        merged.push({
          kind: "observation",
          id: row.id,
          text: [row.subject, row.summary].filter(Boolean).join(" — "),
          distance: Number(row.distance),
          metadata: {
            sender: row.sender,
            inbox: row.inbox,
            received_at: row.received_at,
          },
        });
      }
    }

    if (kinds.includes("facts")) {
      const facts = await client.query<{
        id: string;
        fact: string;
        source: string;
        confidence: number;
        entity_name: string;
        entity_kind: string;
        distance: string;
      }>(
        `SELECT f.id,
                f.fact,
                f.source,
                f.confidence,
                ent.name  AS entity_name,
                ent.kind  AS entity_kind,
                (e.embedding <=> $1::vector) AS distance
           FROM fact_embeddings e
           JOIN facts    f   ON f.id = e.fact_id
           JOIN entities ent ON ent.id = f.entity_id
          WHERE f.superseded_by IS NULL
          ORDER BY e.embedding <=> $1::vector
          LIMIT $2`,
        [vec, limit]
      );
      for (const row of facts.rows) {
        merged.push({
          kind: "fact",
          id: row.id,
          text: row.fact,
          distance: Number(row.distance),
          metadata: {
            source: row.source,
            confidence: Number(row.confidence),
            entity_name: row.entity_name,
            entity_kind: row.entity_kind,
          },
        });
      }
    }
  } finally {
    client.release();
  }

  merged.sort((a, b) => a.distance - b.distance);
  const deduped: RecallRow[] = [];
  const seen = new Set<string>();
  for (const row of merged) {
    const key = `${row.kind}:${row.id}`;
    if (seen.has(key)) continue;
    seen.add(key);
    deduped.push(row);
    if (deduped.length >= limit) break;
  }

  return toolResult(true, 200, { query, count: deduped.length, results: deduped });
}

async function write(rawInput: unknown): Promise<ReturnType<typeof toolResult>> {
  const parsed = WriteSchema.safeParse(rawInput);
  if (!parsed.success) {
    return errorResult(400, {
      code: "VALIDATION_ERROR",
      message: "Invalid input",
      details: parsed.error.flatten(),
      hint: null,
    });
  }

  const { entity_name, entity_kind, fact, source } = parsed.data;
  const normalizedName = entity_name.trim();
  if (normalizedName.length === 0) {
    return errorResult(400, {
      code: "VALIDATION_ERROR",
      message: "entity_name cannot be whitespace",
      details: null,
      hint: null,
    });
  }

  const client = await pool.connect();
  try {
    await client.query("BEGIN");

    const existing = await client.query<{ id: string }>(
      `SELECT id FROM entities WHERE kind = $1 AND lower(name) = lower($2) LIMIT 1`,
      [entity_kind, normalizedName]
    );

    let entityId: string;
    if (existing.rows.length > 0 && existing.rows[0]) {
      entityId = existing.rows[0].id;
      await client.query(
        `UPDATE entities SET last_seen_at = now() WHERE id = $1`,
        [entityId]
      );
    } else {
      const insert = await client.query<{ id: string }>(
        `INSERT INTO entities (kind, name) VALUES ($1, $2) RETURNING id`,
        [entity_kind, normalizedName]
      );
      if (!insert.rows[0]) {
        throw new Error("INSERT into entities returned no row");
      }
      entityId = insert.rows[0].id;
    }

    const factRow = await client.query<{ id: string; created_at: string }>(
      `INSERT INTO facts (entity_id, fact, source) VALUES ($1, $2, $3)
         RETURNING id, created_at`,
      [entityId, fact, source]
    );

    await client.query("COMMIT");

    return toolResult(true, 200, {
      entity_id: entityId,
      fact_id: factRow.rows[0]?.id,
      created_at: factRow.rows[0]?.created_at,
    });
  } catch (err: unknown) {
    await client.query("ROLLBACK").catch(() => undefined);
    const message = err instanceof Error ? err.message : String(err);
    return errorResult(500, {
      code: "DB_ERROR",
      message,
      details: null,
      hint: "Check postgres-obs connectivity and brain schema migration.",
    });
  } finally {
    client.release();
  }
}

async function getSoul(
  rawInput: unknown
): Promise<ReturnType<typeof toolResult>> {
  const parsed = GetSoulSchema.safeParse(rawInput);
  if (!parsed.success) {
    return errorResult(400, {
      code: "VALIDATION_ERROR",
      message: "Invalid input",
      details: parsed.error.flatten(),
      hint: null,
    });
  }

  const userKey = parsed.data.user_key ?? DEFAULT_USER_KEY;
  const client = await pool.connect();
  try {
    const result = await client.query<{
      user_key: string;
      display_name: string | null;
      role: string | null;
      location: string | null;
      entities: unknown;
      markets: string[] | null;
      working_hours: string | null;
      signature_style: string | null;
      soul_md: string | null;
      version: number;
      updated_at: string;
    }>(
      `SELECT user_key, display_name, role, location, entities, markets,
              working_hours, signature_style, soul_md, version, updated_at
         FROM user_profile
        WHERE user_key = $1
        LIMIT 1`,
      [userKey]
    );

    if (result.rows.length === 0) {
      return toolResult(true, 200, {
        user_key: userKey,
        exists: false,
        message: "No Soul profile yet. Run scripts/bootstrap-brain.sh or insert manually.",
      });
    }

    const row = result.rows[0];
    return toolResult(true, 200, { exists: true, profile: row });
  } catch (err: unknown) {
    const message = err instanceof Error ? err.message : String(err);
    return errorResult(500, {
      code: "DB_ERROR",
      message,
      details: null,
      hint: null,
    });
  } finally {
    client.release();
  }
}

async function listRelationships(
  rawInput: unknown
): Promise<ReturnType<typeof toolResult>> {
  const parsed = ListRelationshipsSchema.safeParse(rawInput);
  if (!parsed.success) {
    return errorResult(400, {
      code: "VALIDATION_ERROR",
      message: "Invalid input",
      details: parsed.error.flatten(),
      hint: null,
    });
  }

  const { entity_name } = parsed.data;
  const client = await pool.connect();
  try {
    const entityRows = await client.query<{
      id: string;
      name: string;
      kind: string;
    }>(
      `SELECT id, name, kind FROM entities
        WHERE lower(name) = lower($1)
           OR $1 = ANY(COALESCE(aliases, ARRAY[]::text[]))
        ORDER BY last_seen_at DESC
        LIMIT 1`,
      [entity_name]
    );

    if (entityRows.rows.length === 0 || !entityRows.rows[0]) {
      return toolResult(true, 404, {
        found: false,
        message: `No entity named '${entity_name}'`,
      });
    }

    const entity = entityRows.rows[0];

    const outgoing = await client.query<{
      id: string;
      kind: string;
      strength: number;
      to_name: string;
      to_kind: string;
      last_contact_at: string | null;
      notes: string | null;
    }>(
      `SELECT r.id, r.kind, r.strength, r.last_contact_at, r.notes,
              e2.name AS to_name, e2.kind AS to_kind
         FROM relationships r
         JOIN entities e2 ON e2.id = r.to_entity
        WHERE r.from_entity = $1
        ORDER BY r.strength DESC NULLS LAST`,
      [entity.id]
    );

    const incoming = await client.query<{
      id: string;
      kind: string;
      strength: number;
      from_name: string;
      from_kind: string;
      last_contact_at: string | null;
      notes: string | null;
    }>(
      `SELECT r.id, r.kind, r.strength, r.last_contact_at, r.notes,
              e1.name AS from_name, e1.kind AS from_kind
         FROM relationships r
         JOIN entities e1 ON e1.id = r.from_entity
        WHERE r.to_entity = $1
        ORDER BY r.strength DESC NULLS LAST`,
      [entity.id]
    );

    return toolResult(true, 200, {
      found: true,
      entity,
      outgoing: outgoing.rows,
      incoming: incoming.rows,
    });
  } catch (err: unknown) {
    const message = err instanceof Error ? err.message : String(err);
    return errorResult(500, {
      code: "DB_ERROR",
      message,
      details: null,
      hint: null,
    });
  } finally {
    client.release();
  }
}

// ── MCP Server ────────────────────────────────────────────────────────────────

const server = new Server(
  { name: "safeclaw-brain-api", version: "1.0.0" },
  { capabilities: { tools: {} } }
);

server.setRequestHandler(ListToolsRequestSchema, () => ({
  tools: [
    {
      name: "brain_recall",
      description:
        "Semantic search across SafeClaw brain memory (observations + facts). " +
        "Returns the most similar entries ranked by cosine distance.",
      inputSchema: {
        type: "object",
        properties: {
          query: { type: "string", description: "Natural-language query (max 2000 chars)" },
          kinds: {
            type: "array",
            items: { type: "string", enum: ["observations", "facts"] },
            description: "Which memory types to search (default: both)",
          },
          limit: {
            type: "integer",
            minimum: 1,
            maximum: 50,
            description: "Max results to return (default 10)",
          },
        },
        required: ["query"],
      },
    },
    {
      name: "brain_write",
      description:
        "Upsert an entity by (kind, name) and append a fact about it. " +
        "Source must be non-empty (e.g. 'email:<message_id>', 'manual:vasanth').",
      inputSchema: {
        type: "object",
        properties: {
          entity_name: { type: "string", description: "Entity display name" },
          entity_kind: {
            type: "string",
            enum: ["person", "company", "property", "deal", "vehicle", "other"],
          },
          fact: { type: "string", description: "The fact to record" },
          source: {
            type: "string",
            description: "Provenance string (non-empty), e.g. 'email:<id>' or 'manual:<user>'",
          },
        },
        required: ["entity_name", "entity_kind", "fact", "source"],
      },
    },
    {
      name: "brain_get_soul",
      description:
        "Return the user's Soul (profile JSON + soul markdown). Defaults to BRAIN_USER_KEY.",
      inputSchema: {
        type: "object",
        properties: {
          user_key: {
            type: "string",
            description: "Which profile to return (default: 'primary')",
          },
        },
        required: [],
      },
    },
    {
      name: "brain_list_relationships",
      description:
        "Return the graph neighborhood for an entity: all outgoing + incoming edges " +
        "with relationship kind + strength.",
      inputSchema: {
        type: "object",
        properties: {
          entity_name: { type: "string", description: "Entity display name or alias" },
        },
        required: ["entity_name"],
      },
    },
  ],
}));

server.setRequestHandler(CallToolRequestSchema, async (request) => {
  const { name, arguments: args } = request.params;

  switch (name) {
    case "brain_recall":
      return recall(args);
    case "brain_write":
      return write(args);
    case "brain_get_soul":
      return getSoul(args);
    case "brain_list_relationships":
      return listRelationships(args);
    default:
      return errorResult(404, {
        code: "TOOL_NOT_FOUND",
        message: `Unknown tool: ${name}`,
        details: null,
        hint:
          "Available tools: brain_recall, brain_write, brain_get_soul, brain_list_relationships",
      });
  }
});

// ── Startup ───────────────────────────────────────────────────────────────────

const transport = new StdioServerTransport();
await server.connect(transport);
process.stderr.write("safeclaw-brain-api MCP server running on stdio\n");
