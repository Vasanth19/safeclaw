/**
 * SafeClaw Tasks API — MCP Server
 *
 * Exposes 4 tools over stdio transport that wrap PostgREST endpoints for the
 * safeclaw_tasks database. hermes-actor calls these tools; it never constructs
 * raw HTTP calls to PostgREST or SQL queries directly.
 *
 * Required environment variables:
 *   POSTGREST_URL      — e.g. http://postgrest:3000
 *   TASKS_AGENT_JWT    — pre-signed JWT with role=tasks_agent
 */

import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import {
  CallToolRequestSchema,
  ListToolsRequestSchema,
} from "@modelcontextprotocol/sdk/types.js";
import { z } from "zod";

// ── Environment ───────────────────────────────────────────────────────────────

const POSTGREST_URL = process.env["POSTGREST_URL"];
const TASKS_AGENT_JWT = process.env["TASKS_AGENT_JWT"];

if (!POSTGREST_URL) {
  process.stderr.write("FATAL: POSTGREST_URL environment variable is required\n");
  process.exit(1);
}

if (!TASKS_AGENT_JWT) {
  process.stderr.write("FATAL: TASKS_AGENT_JWT environment variable is required\n");
  process.exit(1);
}

// ── Types ─────────────────────────────────────────────────────────────────────

interface PostgRESTError {
  code: string;
  message: string;
  details: string | null;
  hint: string | null;
}

interface Task {
  id: string;
  title: string;
  description: string | null;
  status: string;
  priority: string;
  due_at: string | null;
  created_at: string;
  created_by: string;
  assigned_to: string | null;
}

interface Comment {
  id: string;
  task_id: string;
  author: string;
  body: string;
  created_at: string;
}

interface StatusTransition {
  id: string;
  task_id: string;
  from_status: string | null;
  to_status: string;
  actor: string;
  reason: string | null;
  transitioned_at: string;
}

// ── PostgREST HTTP Client ─────────────────────────────────────────────────────

async function pgFetch<T>(
  path: string,
  options: {
    method?: string;
    body?: unknown;
    headers?: Record<string, string>;
  } = {}
): Promise<{ ok: boolean; status: number; data: T | PostgRESTError }> {
  const method = options.method ?? "GET";
  const headers: Record<string, string> = {
    Authorization: `Bearer ${TASKS_AGENT_JWT}`,
    "Content-Type": "application/json",
    Accept: "application/json",
    // Return a single object (not array) on POST with Prefer: return=representation
    ...(method === "POST" || method === "PATCH"
      ? { Prefer: "return=representation" }
      : {}),
    ...options.headers,
  };

  const url = `${POSTGREST_URL}${path}`;

  let response: Response;
  try {
    response = await fetch(url, {
      method,
      headers,
      body: options.body !== undefined ? JSON.stringify(options.body) : undefined,
    });
  } catch (err: unknown) {
    const message = err instanceof Error ? err.message : String(err);
    return {
      ok: false,
      status: 0,
      data: {
        code: "NETWORK_ERROR",
        message: `Failed to reach PostgREST at ${url}: ${message}`,
        details: null,
        hint: "Verify POSTGREST_URL and that the postgrest container is healthy.",
      },
    };
  }

  let data: unknown;
  const text = await response.text();
  try {
    data = text.length > 0 ? JSON.parse(text) : null;
  } catch {
    data = { code: "PARSE_ERROR", message: text, details: null, hint: null };
  }

  // PostgREST returns arrays; unwrap single-item arrays for POST/PATCH with Prefer header.
  if (
    response.ok &&
    Array.isArray(data) &&
    (method === "POST" || method === "PATCH")
  ) {
    data = data[0] ?? null;
  }

  return { ok: response.ok, status: response.status, data: data as T | PostgRESTError };
}

function toolResult(
  ok: boolean,
  status: number,
  data: unknown
): { content: Array<{ type: "text"; text: string }> } {
  return {
    content: [
      {
        type: "text",
        text: JSON.stringify({ ok, status, data }, null, 2),
      },
    ],
  };
}

// ── Input Schemas (Zod) ───────────────────────────────────────────────────────

const CreateTaskSchema = z.object({
  title: z.string().min(1).max(500),
  description: z.string().max(5000).optional(),
  priority: z.enum(["low", "medium", "high", "urgent"]).optional().default("medium"),
  due_at: z
    .string()
    .regex(/^\d{4}-\d{2}-\d{2}(T\d{2}:\d{2}(:\d{2})?(\.\d+)?(Z|[+-]\d{2}:\d{2})?)?$/, {
      message: "due_at must be an ISO 8601 date or datetime string",
    })
    .optional(),
  assigned_to: z.string().max(200).optional(),
});

const AddCommentSchema = z.object({
  task_id: z.string().uuid({ message: "task_id must be a valid UUID" }),
  body: z.string().min(1).max(5000),
});

const UpdateStatusSchema = z.object({
  task_id: z.string().uuid({ message: "task_id must be a valid UUID" }),
  to_status: z.enum(["in_progress", "blocked", "done", "cancelled"]),
  reason: z.string().max(1000).optional(),
});

const ListMyOpenSchema = z.object({
  assigned_to: z.string().max(200).optional(),
  priority: z.enum(["low", "medium", "high", "urgent"]).optional(),
});

// ── Tool Implementations ──────────────────────────────────────────────────────

async function createTask(
  rawInput: unknown
): Promise<ReturnType<typeof toolResult>> {
  const parsed = CreateTaskSchema.safeParse(rawInput);
  if (!parsed.success) {
    return toolResult(false, 400, {
      code: "VALIDATION_ERROR",
      message: "Invalid input",
      details: parsed.error.flatten(),
      hint: null,
    });
  }

  const input = parsed.data;
  const payload: Record<string, unknown> = {
    title: input.title,
    priority: input.priority,
    created_by: "safeclaw-actor",
  };
  if (input.description !== undefined) payload["description"] = input.description;
  if (input.due_at !== undefined) payload["due_at"] = input.due_at;
  if (input.assigned_to !== undefined) payload["assigned_to"] = input.assigned_to;

  const result = await pgFetch<Task>("/tasks", { method: "POST", body: payload });
  return toolResult(result.ok, result.status, result.data);
}

async function addComment(
  rawInput: unknown
): Promise<ReturnType<typeof toolResult>> {
  const parsed = AddCommentSchema.safeParse(rawInput);
  if (!parsed.success) {
    return toolResult(false, 400, {
      code: "VALIDATION_ERROR",
      message: "Invalid input",
      details: parsed.error.flatten(),
      hint: null,
    });
  }

  const input = parsed.data;
  const payload: Record<string, unknown> = {
    task_id: input.task_id,
    author: "safeclaw-actor",
    body: input.body,
  };

  const result = await pgFetch<Comment>("/comments", { method: "POST", body: payload });
  return toolResult(result.ok, result.status, result.data);
}

async function updateStatus(
  rawInput: unknown
): Promise<ReturnType<typeof toolResult>> {
  const parsed = UpdateStatusSchema.safeParse(rawInput);
  if (!parsed.success) {
    return toolResult(false, 400, {
      code: "VALIDATION_ERROR",
      message: "Invalid input",
      details: parsed.error.flatten(),
      hint: null,
    });
  }

  const input = parsed.data;

  // 1. Fetch current task to record from_status in the transition log.
  const current = await pgFetch<Task[]>(`/tasks?id=eq.${input.task_id}&select=id,status`);
  if (!current.ok) {
    return toolResult(current.ok, current.status, current.data);
  }

  const tasks = current.data as Task[];
  const fromStatus: string | null = tasks.length > 0 ? (tasks[0]?.status ?? null) : null;

  // 2. Update status on the task row.
  const patchResult = await pgFetch<Task>(
    `/tasks?id=eq.${input.task_id}`,
    { method: "PATCH", body: { status: input.to_status } }
  );
  if (!patchResult.ok) {
    return toolResult(patchResult.ok, patchResult.status, patchResult.data);
  }

  // 3. Insert audit row into status_transitions.
  const transitionPayload: Record<string, unknown> = {
    task_id: input.task_id,
    from_status: fromStatus,
    to_status: input.to_status,
    actor: "safeclaw-actor",
  };
  if (input.reason !== undefined) transitionPayload["reason"] = input.reason;

  const transitionResult = await pgFetch<StatusTransition>("/status_transitions", {
    method: "POST",
    body: transitionPayload,
  });

  return toolResult(
    transitionResult.ok,
    transitionResult.status,
    {
      task: patchResult.data,
      transition: transitionResult.data,
    }
  );
}

async function listMyOpen(
  rawInput: unknown
): Promise<ReturnType<typeof toolResult>> {
  const parsed = ListMyOpenSchema.safeParse(rawInput);
  if (!parsed.success) {
    return toolResult(false, 400, {
      code: "VALIDATION_ERROR",
      message: "Invalid input",
      details: parsed.error.flatten(),
      hint: null,
    });
  }

  const input = parsed.data;

  // Build query string — always exclude terminal statuses.
  const params = new URLSearchParams();
  params.append("status", "neq.done");
  // PostgREST AND filters: use multiple params with same key for column,
  // or use the `and` operator. Here we chain with the select order.
  params.append("status", "neq.cancelled");
  params.append("order", "due_at.asc.nullslast,priority.desc");

  if (input.assigned_to !== undefined) {
    params.append("assigned_to", `eq.${input.assigned_to}`);
  }

  if (input.priority !== undefined) {
    params.append("priority", `eq.${input.priority}`);
  }

  // Note: PostgREST does not support multiple values for the same column key via
  // URLSearchParams by default. Use the `not.in` syntax instead for status exclusion.
  const queryString = `/tasks?status=not.in.(done,cancelled)${
    input.assigned_to !== undefined ? `&assigned_to=eq.${encodeURIComponent(input.assigned_to)}` : ""
  }${
    input.priority !== undefined ? `&priority=eq.${encodeURIComponent(input.priority)}` : ""
  }&order=due_at.asc.nullslast,priority.desc`;

  const result = await pgFetch<Task[]>(queryString);
  return toolResult(result.ok, result.status, result.data);
}

// ── MCP Server ────────────────────────────────────────────────────────────────

const server = new Server(
  { name: "safeclaw-tasks-api", version: "1.0.0" },
  { capabilities: { tools: {} } }
);

server.setRequestHandler(ListToolsRequestSchema, () => ({
  tools: [
    {
      name: "create_task",
      description:
        "Create a new task in the SafeClaw task database. Returns the created task row.",
      inputSchema: {
        type: "object",
        properties: {
          title: { type: "string", description: "Task title (required, max 500 chars)" },
          description: { type: "string", description: "Detailed description (optional, max 5000 chars)" },
          priority: {
            type: "string",
            enum: ["low", "medium", "high", "urgent"],
            description: "Task priority. Defaults to medium.",
          },
          due_at: {
            type: "string",
            description: "ISO 8601 due date/datetime. E.g. 2025-06-15 or 2025-06-15T14:00:00Z",
          },
          assigned_to: { type: "string", description: "Assignee name or identifier (optional)" },
        },
        required: ["title"],
      },
    },
    {
      name: "add_comment",
      description:
        "Add a comment to an existing task. Returns the created comment row.",
      inputSchema: {
        type: "object",
        properties: {
          task_id: { type: "string", description: "UUID of the task to comment on" },
          body: { type: "string", description: "Comment text (max 5000 chars)" },
        },
        required: ["task_id", "body"],
      },
    },
    {
      name: "update_status",
      description:
        "Update a task's status and record the transition in the audit log. " +
        "Valid transitions: open→in_progress, in_progress→blocked, blocked→in_progress, any→done, any→cancelled.",
      inputSchema: {
        type: "object",
        properties: {
          task_id: { type: "string", description: "UUID of the task to update" },
          to_status: {
            type: "string",
            enum: ["in_progress", "blocked", "done", "cancelled"],
            description: "Target status",
          },
          reason: { type: "string", description: "Optional reason for the transition" },
        },
        required: ["task_id", "to_status"],
      },
    },
    {
      name: "list_my_open",
      description:
        "List open tasks (excludes done and cancelled). Optionally filter by assigned_to and priority.",
      inputSchema: {
        type: "object",
        properties: {
          assigned_to: { type: "string", description: "Filter by assignee name/ID (optional)" },
          priority: {
            type: "string",
            enum: ["low", "medium", "high", "urgent"],
            description: "Filter by priority (optional)",
          },
        },
        required: [],
      },
    },
  ],
}));

server.setRequestHandler(CallToolRequestSchema, async (request) => {
  const { name, arguments: args } = request.params;

  switch (name) {
    case "create_task":
      return createTask(args);
    case "add_comment":
      return addComment(args);
    case "update_status":
      return updateStatus(args);
    case "list_my_open":
      return listMyOpen(args);
    default:
      return toolResult(false, 404, {
        code: "TOOL_NOT_FOUND",
        message: `Unknown tool: ${name}`,
        details: null,
        hint: "Available tools: create_task, add_comment, update_status, list_my_open",
      });
  }
});

// ── Startup ───────────────────────────────────────────────────────────────────

const transport = new StdioServerTransport();
await server.connect(transport);
process.stderr.write("safeclaw-tasks-api MCP server running on stdio\n");
