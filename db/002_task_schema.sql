-- SafeClaw: Task Database Schema
-- Database: safeclaw_tasks
-- Idempotent: safe to re-run.

-- ─── Extensions ──────────────────────────────────────────────────────────────

CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- ─── Roles ────────────────────────────────────────────────────────────────────
-- tasks_anon  : PostgREST unauthenticated role — no access
-- tasks_agent : hermes-actor service account — limited write + SELECT
-- tasks_human : human operator — full access for dashboard / overrides

DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'tasks_anon') THEN
        CREATE ROLE tasks_anon NOLOGIN;
    END IF;
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'tasks_agent') THEN
        CREATE ROLE tasks_agent NOLOGIN;
    END IF;
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'tasks_human') THEN
        CREATE ROLE tasks_human NOLOGIN;
    END IF;
END
$$;

-- Application users — passwords come from env vars injected at init time.
-- If the users already exist this is a no-op.
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'tasks_agent_user') THEN
        EXECUTE format(
            'CREATE USER tasks_agent_user PASSWORD %L IN ROLE tasks_agent',
            current_setting('app.tasks_agent_password', true)
        );
    END IF;
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'tasks_human_user') THEN
        EXECUTE format(
            'CREATE USER tasks_human_user PASSWORD %L IN ROLE tasks_human',
            current_setting('app.tasks_human_password', true)
        );
    END IF;
END
$$;

-- PostgREST authenticator role switch — PostgREST connects as this role then
-- switches to the JWT-specified role.
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'authenticator') THEN
        CREATE ROLE authenticator NOLOGIN;
    END IF;
END
$$;

GRANT tasks_anon  TO authenticator;
GRANT tasks_agent TO authenticator;
GRANT tasks_human TO authenticator;

-- ─── Tables ───────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS tasks (
    id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    title       TEXT        NOT NULL,
    description TEXT,
    status      TEXT        NOT NULL DEFAULT 'open'
                            CHECK (status IN ('open', 'in_progress', 'blocked', 'done', 'cancelled')),
    priority    TEXT        NOT NULL DEFAULT 'medium'
                            CHECK (priority IN ('low', 'medium', 'high', 'urgent')),
    due_at      TIMESTAMPTZ,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_by  TEXT        NOT NULL,
    assigned_to TEXT
);

CREATE TABLE IF NOT EXISTS comments (
    id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    task_id     UUID        NOT NULL REFERENCES tasks (id) ON DELETE CASCADE,
    author      TEXT        NOT NULL,
    body        TEXT        NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS status_transitions (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    task_id         UUID        NOT NULL REFERENCES tasks (id) ON DELETE CASCADE,
    from_status     TEXT,
    to_status       TEXT        NOT NULL,
    actor           TEXT        NOT NULL,
    reason          TEXT,
    transitioned_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ─── Row-Level Security ───────────────────────────────────────────────────────

ALTER TABLE tasks              ENABLE ROW LEVEL SECURITY;
ALTER TABLE comments           ENABLE ROW LEVEL SECURITY;
ALTER TABLE status_transitions ENABLE ROW LEVEL SECURITY;

-- tasks_human: full access
CREATE POLICY IF NOT EXISTS tasks_human_all ON tasks
    FOR ALL TO tasks_human USING (true) WITH CHECK (true);

CREATE POLICY IF NOT EXISTS comments_human_all ON comments
    FOR ALL TO tasks_human USING (true) WITH CHECK (true);

CREATE POLICY IF NOT EXISTS transitions_human_all ON status_transitions
    FOR ALL TO tasks_human USING (true) WITH CHECK (true);

-- tasks_agent: SELECT all rows
CREATE POLICY IF NOT EXISTS tasks_agent_select ON tasks
    FOR SELECT TO tasks_agent USING (true);

CREATE POLICY IF NOT EXISTS comments_agent_select ON comments
    FOR SELECT TO tasks_agent USING (true);

CREATE POLICY IF NOT EXISTS transitions_agent_select ON status_transitions
    FOR SELECT TO tasks_agent USING (true);

-- tasks_agent: INSERT tasks and comments
CREATE POLICY IF NOT EXISTS tasks_agent_insert ON tasks
    FOR INSERT TO tasks_agent WITH CHECK (true);

CREATE POLICY IF NOT EXISTS comments_agent_insert ON comments
    FOR INSERT TO tasks_agent WITH CHECK (true);

-- tasks_agent: INSERT status_transitions (audit trail)
CREATE POLICY IF NOT EXISTS transitions_agent_insert ON status_transitions
    FOR INSERT TO tasks_agent WITH CHECK (true);

-- tasks_agent: UPDATE status only — restricted to valid transitions
-- Transition matrix: open→in_progress, in_progress→blocked, blocked→in_progress, any→done, any→cancelled
CREATE POLICY IF NOT EXISTS tasks_agent_update_status ON tasks
    FOR UPDATE TO tasks_agent
    USING (true)
    WITH CHECK (
        (status = 'in_progress' AND (SELECT t.status FROM tasks t WHERE t.id = tasks.id) IN ('open', 'blocked'))
        OR (status = 'blocked'     AND (SELECT t.status FROM tasks t WHERE t.id = tasks.id) = 'in_progress')
        OR  status = 'done'
        OR  status = 'cancelled'
    );

-- tasks_anon: no access (default deny — no policies created means DENY ALL)

-- ─── Grants ───────────────────────────────────────────────────────────────────

GRANT SELECT, INSERT, UPDATE ON tasks              TO tasks_agent;
GRANT SELECT, INSERT         ON comments           TO tasks_agent;
GRANT SELECT, INSERT         ON status_transitions TO tasks_agent;

GRANT ALL ON tasks              TO tasks_human;
GRANT ALL ON comments           TO tasks_human;
GRANT ALL ON status_transitions TO tasks_human;

-- ─── Indexes ──────────────────────────────────────────────────────────────────

CREATE INDEX IF NOT EXISTS idx_tasks_status_due
    ON tasks (status, due_at);

CREATE INDEX IF NOT EXISTS idx_tasks_assigned_status
    ON tasks (assigned_to, status);

CREATE INDEX IF NOT EXISTS idx_comments_task_created
    ON comments (task_id, created_at);

CREATE INDEX IF NOT EXISTS idx_transitions_task_time
    ON status_transitions (task_id, transitioned_at DESC);
