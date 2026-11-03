CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS fields (
    id          BIGSERIAL PRIMARY KEY,
    field_name  TEXT NOT NULL UNIQUE,
    description TEXT NOT NULL                        
);


CREATE TABLE IF NOT EXISTS users (
    id         BIGSERIAL PRIMARY KEY,
    name       TEXT NOT NULL,
    email      TEXT NOT NULL UNIQUE,
    role       TEXT NOT NULL CHECK (role IN ('admin', 'recruiter')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);


CREATE TABLE IF NOT EXISTS user_fields (
    user_id  BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    field_id BIGINT NOT NULL REFERENCES fields(id) ON DELETE CASCADE,
    PRIMARY KEY (user_id, field_id)
);


CREATE TABLE IF NOT EXISTS documents (
    id            BIGSERIAL PRIMARY KEY,
    drive_file_id TEXT UNIQUE,                      
    title         TEXT NOT NULL,                    
    field_id      BIGINT REFERENCES fields(id),      
    filename      TEXT NOT NULL,                     
    mime_type     TEXT NOT NULL DEFAULT 'application/pdf',
    content_hash  TEXT NOT NULL,                  
    status        TEXT NOT NULL DEFAULT 'processing'
                  CHECK (status IN ('processing', 'ready', 'needs_review', 'failed', 'rejected')),
    reasons       TEXT[] NOT NULL DEFAULT '{}',     
    metadata      JSONB NOT NULL DEFAULT '{}',       -- page_count
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);


CREATE TABLE IF NOT EXISTS combinations (
    id        BIGSERIAL PRIMARY KEY,
    extractor TEXT NOT NULL,
    strategy  TEXT NOT NULL,
    settings  JSONB NOT NULL,                       -- chunk size, overlap, embedding_model, dimensions
    selected  BOOLEAN NOT NULL DEFAULT FALSE,
    notes     TEXT,
    UNIQUE (extractor, strategy)
);


CREATE TABLE IF NOT EXISTS document_chunks (
    id             BIGSERIAL PRIMARY KEY,
    document_id    BIGINT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    combination_id BIGINT NOT NULL REFERENCES combinations(id) ON DELETE CASCADE,
    chunk_index    INT NOT NULL,
    level          TEXT NOT NULL DEFAULT 'chunk' CHECK (level IN ('chunk', 'parent', 'child')),
    parent_id      BIGINT REFERENCES document_chunks(id) ON DELETE CASCADE,  -- hierarchical only
    content        TEXT NOT NULL,
    token_count    INT NOT NULL,
    metadata       JSONB NOT NULL DEFAULT '{}',    -- page, section
    embedding      VECTOR(768),
    UNIQUE (document_id, combination_id, chunk_index)
);


-- Only one combination may be selected
CREATE UNIQUE INDEX IF NOT EXISTS one_selected
ON combinations (selected)
WHERE selected = true;


CREATE INDEX IF NOT EXISTS chunks_combination
ON document_chunks (combination_id);