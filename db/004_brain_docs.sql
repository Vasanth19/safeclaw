-- SafeClaw: Brain Docs — vector index for .md brain files
-- Stores summaries (not full content) of People/, Companies/, Meetings/ etc.
-- The embedder polls brain_docs WHERE embedded = FALSE and fills brain_doc_embeddings.
-- brain_search MCP tool does cosine similarity search over these summaries,
-- returning file_path so the actor can read the full .md for detail.
-- Idempotent: safe to re-run.

CREATE TABLE IF NOT EXISTS brain_docs (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    user_key        TEXT        NOT NULL,
    file_path       TEXT        NOT NULL,        -- path relative to /opt/brain/
    doc_type        TEXT        NOT NULL,        -- 'person' | 'company' | 'meeting' | 'project' | 'journal' | 'other'
    title           TEXT,                        -- display name (person name, company name)
    summary         TEXT        NOT NULL,        -- short extracted summary — what gets vectorised
    content_hash    TEXT        NOT NULL,        -- sha256(full .md content) for change detection
    embedded        BOOLEAN     NOT NULL DEFAULT FALSE,
    indexed_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT brain_docs_file_unique UNIQUE (user_key, file_path)
);

CREATE TABLE IF NOT EXISTS brain_doc_embeddings (
    doc_id          UUID        PRIMARY KEY REFERENCES brain_docs(id) ON DELETE CASCADE,
    embedding       vector(384) NOT NULL,
    embedded_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- HNSW cosine index for fast similarity search
CREATE INDEX IF NOT EXISTS idx_brain_doc_embeddings_hnsw
    ON brain_doc_embeddings USING hnsw (embedding vector_cosine_ops);

-- Embedder poll index
CREATE INDEX IF NOT EXISTS idx_brain_docs_embedded_false
    ON brain_docs (indexed_at)
    WHERE embedded = FALSE;

-- Type + title lookup
CREATE INDEX IF NOT EXISTS idx_brain_docs_type
    ON brain_docs (user_key, doc_type);
