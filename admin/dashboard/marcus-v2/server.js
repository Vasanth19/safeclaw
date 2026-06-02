/**
 * dashboard/server.js — Marcus v2 dashboard server (Hono).
 *
 * Endpoints:
 *   GET /            — SPA dashboard HTML
 *   GET /api/health  — uptime, version, active agents, memory stats
 *   GET /api/memories
 *   GET /api/conversations
 *   GET /api/tasks
 *   GET /api/audit
 *   GET /api/priorities
 *   GET /api/stats
 *   GET /api/events  — SSE real-time stream
 *
 * Auth: token required on all /api/* routes via ?token= or Authorization header.
 *
 * Export: startDashboard() → starts the server on DASHBOARD_PORT.
 */

import { Hono } from 'hono';
import { serve } from '@hono/node-server';
import { supabase } from '../lib/supabase.js';
import { DASHBOARD_PORT, DASHBOARD_TOKEN } from '../config.js';
import { getDashboardHtml } from './dashboard-html.js';
import { getInboxSummary } from '../lib/integrations/gmail.js';
import { getTodayEvents } from '../lib/integrations/calendar.js';
import { getSlackSummary } from '../lib/integrations/slack.js';
import { getOpenTasks } from '../lib/integrations/clickup.js';
import { getBrainStats, searchBrain, thinkBrain } from '../lib/integrations/brain.js';
import { getFleet } from '../lib/integrations/fleet.js';

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const VERSION = '2.0.0';
const BOOT_TIME = Date.now();

// ---------------------------------------------------------------------------
// Hono app
// ---------------------------------------------------------------------------

const app = new Hono();

// ---------------------------------------------------------------------------
// Auth middleware for /api/*
// ---------------------------------------------------------------------------

function getToken(c) {
  // Check Authorization header first
  const authHeader = c.req.header('Authorization') || '';
  if (authHeader.startsWith('Bearer ')) {
    return authHeader.slice(7).trim();
  }
  // Fall back to query param
  return c.req.query('token') || '';
}

function authMiddleware(c, next) {
  if (!DASHBOARD_TOKEN) {
    // No token configured — open access (dev mode)
    return next();
  }
  const token = getToken(c);
  if (!token || token !== DASHBOARD_TOKEN) {
    return c.json({ error: 'unauthorized' }, 401);
  }
  return next();
}

// Apply auth to all /api/* routes
app.use('/api/*', authMiddleware);

// ---------------------------------------------------------------------------
// GET /healthz — unauthed liveness probe (for Railway/Netlify/k8s)
// ---------------------------------------------------------------------------
app.get('/healthz', (c) => {
  return c.json({
    ok: true,
    service: 'marcus-dashboard',
    version: VERSION,
    uptimeSeconds: Math.floor((Date.now() - BOOT_TIME) / 1000),
    ts: new Date().toISOString(),
  });
});

// ---------------------------------------------------------------------------
// GET / — Dashboard HTML
// ---------------------------------------------------------------------------

app.get('/', (c) => {
  return c.html(getDashboardHtml());
});

// ---------------------------------------------------------------------------
// GET /api/health
// ---------------------------------------------------------------------------

app.get('/api/health', async (c) => {
  let memoryStats = null;

  try {
    const { count } = await supabase
      .from('marcus_memories_v2')
      .select('*', { count: 'exact', head: true })
      .is('superseded_by', null);

    memoryStats = { totalMemories: count ?? 0 };
  } catch {
    // Non-fatal
  }

  return c.json({
    ok: true,
    service: 'marcus-dashboard',
    version: VERSION,
    uptimeSeconds: Math.floor((Date.now() - BOOT_TIME) / 1000),
    activeSessions: 0, // dashboard doesn't track sessions
    memoryStats,
    ts: new Date().toISOString(),
  });
});

// ---------------------------------------------------------------------------
// GET /api/memories
// Query: limit (default 50), offset, search
// ---------------------------------------------------------------------------

app.get('/api/memories', async (c) => {
  const limit = Math.min(parseInt(c.req.query('limit') || '50', 10), 200);
  const offset = parseInt(c.req.query('offset') || '0', 10);
  const search = c.req.query('search') || '';

  try {
    let query = supabase
      .from('marcus_memories_v2')
      .select('id, agent_id, summary, entities, topics, importance, salience, superseded_by, created_at')
      .is('superseded_by', null)
      .order('created_at', { ascending: false })
      .range(offset, offset + limit - 1);

    if (search) {
      query = query.textSearch('summary', search, { type: 'websearch' });
    }

    const { data, error } = await query;

    if (error) {
      console.error('[dashboard] memories query failed:', error.message);
      return c.json({ error: error.message }, 500);
    }

    return c.json(data ?? []);
  } catch (err) {
    console.error('[dashboard] memories error:', err.message);
    return c.json({ error: err.message }, 500);
  }
});

// ---------------------------------------------------------------------------
// GET /api/conversations
// Query: limit (default 50), offset
// ---------------------------------------------------------------------------

app.get('/api/conversations', async (c) => {
  const limit = Math.min(parseInt(c.req.query('limit') || '50', 10), 200);
  const offset = parseInt(c.req.query('offset') || '0', 10);

  try {
    const { data, error } = await supabase
      .from('marcus_conversations')
      .select('id, vapi_call_id, caller_number, direction, started_at, ended_at, duration_seconds, summary, agent_version, created_at')
      .order('created_at', { ascending: false })
      .range(offset, offset + limit - 1);

    if (error) {
      console.error('[dashboard] conversations query failed:', error.message);
      return c.json({ error: error.message }, 500);
    }

    return c.json(data ?? []);
  } catch (err) {
    console.error('[dashboard] conversations error:', err.message);
    return c.json({ error: err.message }, 500);
  }
});

// ---------------------------------------------------------------------------
// GET /api/tasks
// Returns both scheduled tasks and missions.
// ---------------------------------------------------------------------------

app.get('/api/tasks', async (c) => {
  try {
    const [tasksResult, missionsResult] = await Promise.all([
      supabase
        .from('marcus_scheduled_tasks')
        .select('id, name, schedule, next_run, last_run, status, last_result, created_at')
        .order('next_run', { ascending: true }),
      supabase
        .from('marcus_missions')
        .select('id, title, prompt, priority, assigned_agent, status, result, completed_at, created_at')
        .order('priority', { ascending: true })
        .order('created_at', { ascending: false }),
    ]);

    return c.json({
      scheduledTasks: tasksResult.data ?? [],
      missions: missionsResult.data ?? [],
    });
  } catch (err) {
    console.error('[dashboard] tasks error:', err.message);
    return c.json({ error: err.message }, 500);
  }
});

// ---------------------------------------------------------------------------
// GET /api/audit
// Query: limit (default 50), offset, action, blocked
// ---------------------------------------------------------------------------

app.get('/api/audit', async (c) => {
  const limit = Math.min(parseInt(c.req.query('limit') || '50', 10), 500);
  const offset = parseInt(c.req.query('offset') || '0', 10);
  const action = c.req.query('action') || '';
  const blocked = c.req.query('blocked');

  try {
    let query = supabase
      .from('marcus_audit_log')
      .select('id, agent_id, action, detail, blocked, created_at')
      .order('created_at', { ascending: false })
      .range(offset, offset + limit - 1);

    if (action) {
      query = query.eq('action', action);
    }

    if (blocked === 'true') {
      query = query.eq('blocked', true);
    }

    const { data, error } = await query;

    if (error) {
      console.error('[dashboard] audit query failed:', error.message);
      return c.json({ error: error.message }, 500);
    }

    return c.json(data ?? []);
  } catch (err) {
    console.error('[dashboard] audit error:', err.message);
    return c.json({ error: err.message }, 500);
  }
});

// ---------------------------------------------------------------------------
// GET /api/priorities — "what actually has to get done now and coming up"
//
// Two planes merged into one ranked list:
//   1. DREAM rows — Hermes's nightly dreaming phase writes reasoned, ranked
//      priorities into the marcus_priorities table (source='brain'|'manual').
//      These carry rationale and may cite a ClickUp task. See
//      dashboard/PRIORITIES_HANDOFF.md for the producer contract.
//   2. LIVE ClickUp — open tasks assigned to Jake, pulled at request time so
//      due/overdue is always fresh and brand-new tasks surface before the next
//      nightly dream. ClickUp tasks already cited by a dream row are merged,
//      not duplicated.
//
// Returns: { priorities: [...normalized...], lastDreamedAt, clickupOk,
//            generatedAt }. Each priority is bucketed into now|week|upcoming|done.
// ---------------------------------------------------------------------------

function priorityBucket(it, nowMs, todayEndMs, weekEndMs) {
  if (it.completed_at || it.status === 'done' || it.status === 'completed') return 'done';
  if (it.due != null) {
    if (it.due <= todayEndMs) return 'now'; // overdue or due today
    if (it.due <= weekEndMs) return 'week';
    return 'upcoming';
  }
  // No due date — fall back to the dream row's scope.
  if (it.scope === 'day') return 'now';
  if (it.scope === 'week') return 'week';
  return 'upcoming';
}

app.get('/api/priorities', async (c) => {
  const nowMs = Date.now();

  const [dreamRows, clickup] = await Promise.all([
    (async () => {
      try {
        const { data, error } = await supabase
          .from('marcus_priorities')
          .select('*')
          .not('status', 'in', '("dropped","superseded")')
          .order('committed_at', { ascending: false });
        if (error) {
          if (error.message.includes('does not exist') || error.code === '42P01') return [];
          throw error;
        }
        return data ?? [];
      } catch (err) {
        console.error('[dashboard] priorities dream query failed:', err.message);
        return [];
      }
    })(),
    safeCall(() => getOpenTasks()),
  ]);

  const items = [];
  const citedTaskIds = new Set();
  const citedUrls = new Set();
  let lastDreamedAt = null;

  // --- Normalize dream rows -------------------------------------------------
  for (const p of dreamRows) {
    const source = p.source || 'manual';
    const taskId = p.clickup_task_id != null ? String(p.clickup_task_id) : null;
    if (taskId) citedTaskIds.add(taskId);
    if (p.url) citedUrls.add(p.url);
    if (source === 'brain') {
      const at = p.committed_at || p.created_at;
      if (at && (!lastDreamedAt || at > lastDreamedAt)) lastDreamedAt = at;
    }
    items.push({
      id: p.id,
      text: p.content || p.text || p.title || '—',
      scope: p.scope || 'ongoing',
      status: p.status || 'active',
      source,
      due: p.due ? new Date(p.due).getTime() : null,
      url: p.url || null,
      rationale: p.rationale || null,
      owner: p.owner || null,
      committed_at: p.committed_at || p.created_at || null,
      completed_at: p.completed_at || null,
    });
  }

  // --- Merge live ClickUp tasks not already cited by a dream row ------------
  if (clickup.ok && Array.isArray(clickup.data?.tasks)) {
    for (const t of clickup.data.tasks) {
      if (citedTaskIds.has(String(t.id))) continue;
      if (t.url && citedUrls.has(t.url)) continue;
      items.push({
        id: 'cu-' + t.id,
        text: t.name || '(untitled task)',
        scope: 'week',
        status: 'active',
        source: 'clickup',
        due: t.due || null,
        url: t.url || null,
        rationale: t.list ? `ClickUp · ${t.list}` : 'ClickUp',
        owner: null,
        committed_at: null,
        completed_at: null,
      });
    }
  }

  // --- Bucket + rank --------------------------------------------------------
  const todayEnd = new Date();
  todayEnd.setHours(23, 59, 59, 999);
  const todayEndMs = todayEnd.getTime();
  const weekEndMs = nowMs + 7 * 24 * 60 * 60 * 1000;

  for (const it of items) it.bucket = priorityBucket(it, nowMs, todayEndMs, weekEndMs);

  // Overdue/soonest first; brain-reasoned items win ties over raw ClickUp.
  items.sort((a, b) => {
    const ad = a.due ?? Number.MAX_SAFE_INTEGER;
    const bd = b.due ?? Number.MAX_SAFE_INTEGER;
    if (ad !== bd) return ad - bd;
    const rank = (s) => (s === 'brain' ? 0 : s === 'manual' ? 1 : 2);
    return rank(a.source) - rank(b.source);
  });

  return c.json({
    priorities: items,
    lastDreamedAt,
    clickupOk: clickup.ok,
    generatedAt: new Date().toISOString(),
  });
});

// ---------------------------------------------------------------------------
// GET /api/stats — aggregate dashboard stats
// ---------------------------------------------------------------------------

app.get('/api/stats', async (c) => {
  const todayStart = new Date();
  todayStart.setHours(0, 0, 0, 0);
  const todayIso = todayStart.toISOString();

  try {
    const [memoriesResult, convsResult, activeTasksResult, blockedResult] = await Promise.all([
      // Total active memories
      supabase
        .from('marcus_memories_v2')
        .select('*', { count: 'exact', head: true })
        .is('superseded_by', null),

      // Conversations started today
      supabase
        .from('marcus_conversations')
        .select('*', { count: 'exact', head: true })
        .gte('created_at', todayIso),

      // Active scheduled tasks + queued missions
      Promise.all([
        supabase
          .from('marcus_scheduled_tasks')
          .select('*', { count: 'exact', head: true })
          .eq('status', 'active'),
        supabase
          .from('marcus_missions')
          .select('*', { count: 'exact', head: true })
          .in('status', ['queued', 'running']),
      ]),

      // Total blocked audit events
      supabase
        .from('marcus_audit_log')
        .select('*', { count: 'exact', head: true })
        .eq('blocked', true),
    ]);

    const [scheduledCount, missionCount] = activeTasksResult;

    return c.json({
      totalMemories: memoriesResult.count ?? 0,
      conversationsToday: convsResult.count ?? 0,
      activeTasks: (scheduledCount.count ?? 0) + (missionCount.count ?? 0),
      blockedAttempts: blockedResult.count ?? 0,
    });
  } catch (err) {
    console.error('[dashboard] stats error:', err.message);
    return c.json({ error: err.message }, 500);
  }
});

// ---------------------------------------------------------------------------
// Integrations: Gmail, Calendar, Slack, ClickUp
// Each wraps its fetch in safeCall() so a missing token returns
// { ok: false, error } instead of a 500. The "Today" endpoint runs all
// four in parallel.
// ---------------------------------------------------------------------------

async function safeCall(fn) {
  try {
    const data = await fn();
    return { ok: true, data };
  } catch (err) {
    return { ok: false, error: err.message };
  }
}

app.get('/api/integrations/gmail', async (c) => {
  return c.json(await safeCall(() => getInboxSummary({ limit: 10 })));
});

app.get('/api/integrations/calendar', async (c) => {
  return c.json(await safeCall(() => getTodayEvents()));
});

app.get('/api/integrations/slack', async (c) => {
  return c.json(await safeCall(() => getSlackSummary()));
});

app.get('/api/integrations/clickup', async (c) => {
  return c.json(await safeCall(() => getOpenTasks()));
});

// gBrain (knowledge plane) — reads the local brain via the gbrain CLI
app.get('/api/brain/stats', async (c) => {
  return c.json(await safeCall(() => getBrainStats()));
});

app.get('/api/brain/search', async (c) => {
  const q = c.req.query('q') || '';
  return c.json(await safeCall(() => searchBrain(q, { limit: 15 })));
});

app.get('/api/brain/think', async (c) => {
  const q = c.req.query('q') || '';
  return c.json(await safeCall(() => thinkBrain(q)));
});

// Fleet (operational plane): machines around the one brain
app.get('/api/fleet', async (c) => {
  return c.json(await safeCall(() => getFleet()));
});

app.get('/api/integrations/today', async (c) => {
  const [gmail, calendar, slack, clickup] = await Promise.all([
    safeCall(() => getInboxSummary({ limit: 5 })),
    safeCall(() => getTodayEvents()),
    safeCall(() => getSlackSummary()),
    safeCall(() => getOpenTasks()),
  ]);
  return c.json({ gmail, calendar, slack, clickup });
});

// ---------------------------------------------------------------------------
// GET /api/events — SSE stream
// ---------------------------------------------------------------------------

app.get('/api/events', (c) => {
  // Stream response headers
  c.header('Content-Type', 'text/event-stream');
  c.header('Cache-Control', 'no-cache');
  c.header('Connection', 'keep-alive');
  c.header('X-Accel-Buffering', 'no');

  const { readable, writable } = new TransformStream();
  const writer = writable.getWriter();
  const encoder = new TextEncoder();

  function send(data) {
    try {
      writer.write(encoder.encode('data: ' + JSON.stringify(data) + '\n\n'));
    } catch {
      // Connection closed
    }
  }

  // Send initial connected event
  send({ type: 'connected', ts: new Date().toISOString() });

  // Heartbeat every 30 seconds
  const heartbeat = setInterval(() => {
    send({ type: 'heartbeat', ts: new Date().toISOString() });
  }, 30_000);

  // Cleanup when client disconnects
  c.req.raw.signal?.addEventListener('abort', () => {
    clearInterval(heartbeat);
    try { writer.close(); } catch {}
  });

  return new Response(readable, {
    headers: {
      'Content-Type': 'text/event-stream',
      'Cache-Control': 'no-cache',
      'Connection': 'keep-alive',
      'X-Accel-Buffering': 'no',
    },
  });
});

// ---------------------------------------------------------------------------
// 404 fallback
// ---------------------------------------------------------------------------

app.notFound((c) => {
  return c.json({ error: 'not_found' }, 404);
});

// ---------------------------------------------------------------------------
// startDashboard()
// ---------------------------------------------------------------------------

/**
 * startDashboard() — Create and start the Hono dashboard server.
 *
 * Starts listening on DASHBOARD_PORT (default 3141).
 * Returns the server instance.
 */
export function startDashboard({ port } = {}) {
  // Railway/Heroku-style PORT env var takes precedence over the
  // dashboard-specific DASHBOARD_PORT, so the same code runs locally and
  // in a managed host.
  const finalPort = port ?? (Number(process.env.PORT) || DASHBOARD_PORT);

  const server = serve(
    {
      fetch: app.fetch,
      port: finalPort,
      hostname: '0.0.0.0',
    },
    (info) => {
      console.log(`[dashboard] Marcus v2 dashboard on ${info.address}:${info.port}`);
      console.log(`[dashboard] Auth: ${DASHBOARD_TOKEN ? 'token required' : 'OPEN (no token set)'}`);
    },
  );

  return server;
}

export { app };
