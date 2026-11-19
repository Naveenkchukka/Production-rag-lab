-- Initial HarborDesk schema. Apply once to the local development database.
-- Embeddings use text-embedding-3-small with 512 dimensions for this version.
BEGIN;

CREATE EXTENSION IF NOT EXISTS vector;
CREATE SCHEMA rag;

CREATE TABLE rag.schema_migrations (
    version     text PRIMARY KEY,
    applied_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE rag.organizations (
    id          uuid PRIMARY KEY,
    slug        text NOT NULL UNIQUE CHECK (slug <> ''),
    name        text NOT NULL CHECK (name <> ''),
    created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE rag.users (
    id              uuid PRIMARY KEY,
    organization_id uuid NOT NULL REFERENCES rag.organizations(id),
    auth_subject    text NOT NULL CHECK (auth_subject <> ''),
    status          text NOT NULL DEFAULT 'active'
                    CHECK (status IN ('active', 'disabled')),
    created_at      timestamptz NOT NULL DEFAULT now(),
    UNIQUE (organization_id, auth_subject),
    UNIQUE (organization_id, id)
);

CREATE TABLE rag.access_groups (
    id              uuid PRIMARY KEY,
    organization_id uuid NOT NULL REFERENCES rag.organizations(id),
    name            text NOT NULL CHECK (name <> ''),
    UNIQUE (organization_id, name),
    UNIQUE (organization_id, id)
);

CREATE TABLE rag.user_group_memberships (
    organization_id uuid NOT NULL,
    user_id         uuid NOT NULL,
    group_id        uuid NOT NULL,
    PRIMARY KEY (organization_id, user_id, group_id),
    FOREIGN KEY (organization_id, user_id)
        REFERENCES rag.users (organization_id, id) ON DELETE CASCADE,
    FOREIGN KEY (organization_id, group_id)
        REFERENCES rag.access_groups (organization_id, id) ON DELETE CASCADE
);

CREATE TABLE rag.documents (
    id              uuid PRIMARY KEY,
    organization_id uuid NOT NULL REFERENCES rag.organizations(id),
    filename        text NOT NULL CHECK (filename <> ''), -- display name only
    sha256          text NOT NULL CHECK (sha256 ~ '^[a-f0-9]{64}$'),
    version         text NOT NULL CHECK (version <> ''),
    object_key      text,
    content_type    text NOT NULL,
    byte_size       bigint NOT NULL CHECK (byte_size > 0),
    status          text NOT NULL DEFAULT 'uploaded'
                    CHECK (status IN ('uploaded', 'queued', 'processing', 'indexed', 'failed', 'archived')),
    trust           text NOT NULL DEFAULT 'trusted'
                    CHECK (trust IN ('trusted', 'untrusted')),
    contains_pii    boolean NOT NULL DEFAULT false,
    metadata        jsonb NOT NULL DEFAULT '{}'::jsonb
                    CHECK (jsonb_typeof(metadata) = 'object'),
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now(),
    UNIQUE (organization_id, sha256, version),
    UNIQUE (organization_id, id)
);

CREATE TABLE rag.document_access_groups (
    organization_id uuid NOT NULL,
    document_id     uuid NOT NULL,
    group_id        uuid NOT NULL,
    PRIMARY KEY (organization_id, document_id, group_id),
    FOREIGN KEY (organization_id, document_id)
        REFERENCES rag.documents (organization_id, id) ON DELETE CASCADE,
    FOREIGN KEY (organization_id, group_id)
        REFERENCES rag.access_groups (organization_id, id) ON DELETE CASCADE
);

CREATE TABLE rag.ingestion_jobs (
    id              uuid PRIMARY KEY,
    organization_id uuid NOT NULL,
    document_id     uuid NOT NULL,
    source_sha256   text NOT NULL CHECK (source_sha256 ~ '^[a-f0-9]{64}$'),
    status          text NOT NULL DEFAULT 'queued'
                    CHECK (status IN ('queued', 'processing', 'retryable', 'succeeded', 'failed')),
    attempts        integer NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    available_at    timestamptz NOT NULL DEFAULT now(),
    last_error      text,
    created_at      timestamptz NOT NULL DEFAULT now(),
    UNIQUE (organization_id, document_id, source_sha256),
    FOREIGN KEY (organization_id, document_id)
        REFERENCES rag.documents (organization_id, id) ON DELETE CASCADE
);

CREATE TABLE rag.outbox_events (
    id              uuid PRIMARY KEY,
    organization_id uuid NOT NULL REFERENCES rag.organizations(id),
    event_type      text NOT NULL,
    aggregate_id    uuid NOT NULL,
    payload         jsonb NOT NULL CHECK (jsonb_typeof(payload) = 'object'),
    created_at      timestamptz NOT NULL DEFAULT now(),
    published_at    timestamptz
);

CREATE TABLE rag.document_chunks (
    id                  uuid PRIMARY KEY,
    organization_id     uuid NOT NULL,
    document_id         uuid NOT NULL,
    source_sha256       text NOT NULL CHECK (source_sha256 ~ '^[a-f0-9]{64}$'),
    chunk_index         integer NOT NULL CHECK (chunk_index >= 0),
    chunking_version    text NOT NULL,
    content             text NOT NULL CHECK (content <> ''),
    source_locator      jsonb NOT NULL DEFAULT '{}'::jsonb,
    embedding_model     text NOT NULL,
    embedding           vector(512) NOT NULL,
    search_text         tsvector GENERATED ALWAYS AS
                        (to_tsvector('simple'::regconfig, content)) STORED,
    created_at          timestamptz NOT NULL DEFAULT now(),
    UNIQUE (organization_id, document_id, source_sha256, chunking_version, chunk_index),
    FOREIGN KEY (organization_id, document_id)
        REFERENCES rag.documents (organization_id, id) ON DELETE CASCADE
);

CREATE INDEX document_chunks_vector_hnsw
    ON rag.document_chunks USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);
CREATE INDEX document_chunks_text_gin
    ON rag.document_chunks USING gin (search_text);
CREATE INDEX document_chunks_document
    ON rag.document_chunks (organization_id, document_id);
CREATE INDEX ingestion_jobs_ready
    ON rag.ingestion_jobs (available_at, created_at)
    WHERE status IN ('queued', 'retryable');
CREATE INDEX outbox_events_ready
    ON rag.outbox_events (created_at)
    WHERE published_at IS NULL;

INSERT INTO rag.schema_migrations (version) VALUES ('0001_initial');
COMMIT;
