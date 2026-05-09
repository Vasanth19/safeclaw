-- SafeClaw: Brain Database Schema
-- Database: safeclaw_obs  (co-located with observations)
-- Run as: obs_user (superuser on this DB)
-- Idempotent: safe to re-run; all objects use IF NOT EXISTS where valid.
--
-- Five memory layers:
--   1. Soul          — user_profile + soul_revisions
--   2. Preferences   — preferences
--   3. Relationships — entities + relationships + facts
--   4. Style         — style_samples
--   5. Rhythms       — rhythms
--
-- Plus pgvector embedding sidecar tables for semantic recall.

-- ─── Extensions ──────────────────────────────────────────────────────────────

CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- ─── Layer 1: Soul (user profile) ────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS user_profile (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    user_key        TEXT        NOT NULL UNIQUE,     -- e.g. 'primary' or a Gmail address
    display_name    TEXT,
    role            TEXT,
    location        TEXT,
    entities        JSONB,                            -- list of LLCs/companies the user controls
    markets         TEXT[],
    working_hours   TEXT,
    signature_style TEXT,
    soul_md         TEXT,                             -- markdown dump of user.soul.md, mirrored for agent access
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    version         INT         NOT NULL DEFAULT 1
);

-- Proposals for Soul updates (weekly reflector drops rows here for user approval).
CREATE TABLE IF NOT EXISTS soul_revisions (
    id                UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    user_key          TEXT        NOT NULL,
    from_version      INT         NOT NULL,
    to_version        INT         NOT NULL,
    diff_summary      TEXT        NOT NULL,
    proposed_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    approved_at       TIMESTAMPTZ,
    approved_by       TEXT,
    rejected_at       TIMESTAMPTZ,
    rejection_reason  TEXT,
    CONSTRAINT soul_revisions_one_outcome CHECK (
        approved_at IS NULL OR rejected_at IS NULL
    )
);

-- ─── Layer 2: Preferences ────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS preferences (
    id                        UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    user_key                  TEXT        NOT NULL,
    rule                      TEXT        NOT NULL,
    reason                    TEXT,
    extracted_from_review_id  UUID,                               -- nullable FK to review_queue (no hard FK; review_queue lives in obs schema but cross-cutting)
    confidence                REAL        NOT NULL DEFAULT 0.5,
    active                    BOOLEAN     NOT NULL DEFAULT TRUE,
    examples_count            INT         NOT NULL DEFAULT 1,
    first_seen_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
    promoted_at               TIMESTAMPTZ,                        -- set when confidence crosses threshold
    CONSTRAINT preferences_confidence_range CHECK (confidence >= 0 AND confidence <= 1)
);

-- ─── Layer 3: Relationships ──────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS entities (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    kind            TEXT        NOT NULL CHECK (kind IN ('person','company','property','deal','vehicle','other')),
    name            TEXT        NOT NULL,
    aliases         TEXT[],
    canonical_email TEXT,
    canonical_phone TEXT,
    metadata        JSONB,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Unique on (kind, lower(name)) — one entity per kind/name pair.
CREATE UNIQUE INDEX IF NOT EXISTS entities_kind_name_unique
    ON entities (kind, lower(name));

CREATE TABLE IF NOT EXISTS relationships (
    id                UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    from_entity       UUID        NOT NULL REFERENCES entities (id) ON DELETE CASCADE,
    to_entity         UUID        NOT NULL REFERENCES entities (id) ON DELETE CASCADE,
    kind              TEXT        NOT NULL,                       -- buyer, seller, agent, attorney, title_co, employee, family, friend, etc.
    strength          REAL        NOT NULL DEFAULT 0.5,
    first_contact_at  TIMESTAMPTZ,
    last_contact_at   TIMESTAMPTZ,
    notes             TEXT,
    CONSTRAINT relationships_strength_range CHECK (strength >= 0 AND strength <= 1),
    CONSTRAINT relationships_no_self_loop   CHECK (from_entity <> to_entity)
);

CREATE TABLE IF NOT EXISTS facts (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    entity_id       UUID        NOT NULL REFERENCES entities (id) ON DELETE CASCADE,
    fact            TEXT        NOT NULL,
    source          TEXT        NOT NULL,                          -- e.g. 'email:<message_id>', 'slack:<ts>', 'manual:<user>'
    confidence      REAL        NOT NULL DEFAULT 0.7,
    embedded        BOOLEAN     NOT NULL DEFAULT FALSE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    superseded_by   UUID        REFERENCES facts (id),
    CONSTRAINT facts_confidence_range CHECK (confidence >= 0 AND confidence <= 1),
    CONSTRAINT facts_source_nonempty  CHECK (length(source) > 0)
);

-- ─── Layer 4: Style Samples ──────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS style_samples (
    id                      UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    user_key                TEXT        NOT NULL,
    sample_text             TEXT        NOT NULL,
    recipient_relationship  TEXT,                                  -- 'close_contact' | 'vendor' | 'cold' | etc.
    topic_category          TEXT,
    word_count              INT,
    embedded                BOOLEAN     NOT NULL DEFAULT FALSE,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ─── Layer 5: Rhythms ────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS rhythms (
    id                  UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    user_key            TEXT        NOT NULL,
    dimension           TEXT        NOT NULL,                     -- 'email_send_hours' | 'slack_active_hours' | 'meeting_days' | 'heads_down_hours'
    value               JSONB       NOT NULL,                     -- e.g. {"hours": [6,7,8,9,18,19,20,21]}
    observations_count  INT         NOT NULL DEFAULT 1,
    computed_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS rhythms_user_dimension_unique
    ON rhythms (user_key, dimension);

-- ─── Embedding Sidecar Tables (pgvector 384-dim for all-MiniLM-L6-v2) ────────

CREATE TABLE IF NOT EXISTS observation_embeddings (
    observation_id  UUID        PRIMARY KEY REFERENCES observations (id) ON DELETE CASCADE,
    embedding       vector(384) NOT NULL,
    embedded_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS fact_embeddings (
    fact_id     UUID        PRIMARY KEY REFERENCES facts (id) ON DELETE CASCADE,
    embedding   vector(384) NOT NULL,
    embedded_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS style_sample_embeddings (
    sample_id   UUID        PRIMARY KEY REFERENCES style_samples (id) ON DELETE CASCADE,
    embedding   vector(384) NOT NULL,
    embedded_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ─── Indexes ────────────────────────────────────────────────────────────────

-- Embedding similarity (HNSW, cosine distance operator <=>).
CREATE INDEX IF NOT EXISTS idx_observation_embeddings_hnsw
    ON observation_embeddings USING hnsw (embedding vector_cosine_ops);

CREATE INDEX IF NOT EXISTS idx_fact_embeddings_hnsw
    ON fact_embeddings USING hnsw (embedding vector_cosine_ops);

CREATE INDEX IF NOT EXISTS idx_style_sample_embeddings_hnsw
    ON style_sample_embeddings USING hnsw (embedding vector_cosine_ops);

-- Entity lookups: alias search + fuzzy name.
CREATE INDEX IF NOT EXISTS idx_entities_aliases_gin
    ON entities USING gin (aliases);

CREATE INDEX IF NOT EXISTS idx_entities_name_trgm
    ON entities USING gin (name gin_trgm_ops);

CREATE INDEX IF NOT EXISTS idx_entities_canonical_email
    ON entities (lower(canonical_email))
    WHERE canonical_email IS NOT NULL;

-- Preferences: active rules per user.
CREATE INDEX IF NOT EXISTS idx_preferences_user_active
    ON preferences (user_key, active);

-- Relationships: adjacency lookup.
CREATE INDEX IF NOT EXISTS idx_relationships_from
    ON relationships (from_entity);

CREATE INDEX IF NOT EXISTS idx_relationships_to
    ON relationships (to_entity);

-- Facts: per-entity timeline + embedder poll index.
CREATE INDEX IF NOT EXISTS idx_facts_entity_created
    ON facts (entity_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_facts_embedded_false
    ON facts (created_at)
    WHERE embedded = FALSE;

-- Style samples: per-user + embedder poll index.
CREATE INDEX IF NOT EXISTS idx_style_samples_user
    ON style_samples (user_key, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_style_samples_embedded_false
    ON style_samples (created_at)
    WHERE embedded = FALSE;

-- Observations: fast scan for rows missing an embedding.
-- (The embedder LEFT JOINs observation_embeddings WHERE e.observation_id IS NULL.)
CREATE INDEX IF NOT EXISTS idx_observations_processed_at
    ON observations (processed_at DESC);

-- Soul revisions: pending approval queue.
CREATE INDEX IF NOT EXISTS idx_soul_revisions_pending
    ON soul_revisions (proposed_at DESC)
    WHERE approved_at IS NULL AND rejected_at IS NULL;
