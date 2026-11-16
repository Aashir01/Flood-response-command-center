-- library-mcp schema, version 1 (design section 5.3). Applied by stitch_library.store.pgvector.
-- CREATE EXTENSION vector runs in the Postgres init script (needs a superuser), not here.
CREATE TABLE IF NOT EXISTS meta (key text PRIMARY KEY, value text NOT NULL);
CREATE TABLE IF NOT EXISTS documents (
    doc_id text PRIMARY KEY,
    title text NOT NULL,
    publisher text NOT NULL,
    doc_type text NOT NULL,
    lang text NOT NULL,
    source_url text NOT NULL,
    license text NOT NULL,
    redistributable boolean NOT NULL,
    tier text NOT NULL CHECK (tier IN ('committed', 'fetched')),
    sha256 text NOT NULL,
    as_of date
);
CREATE TABLE IF NOT EXISTS pages (
    doc_id text REFERENCES documents ON DELETE CASCADE,
    page int NOT NULL,
    lang text NOT NULL,
    status text NOT NULL CHECK (status IN ('ok', 'unreadable')),
    reason text,
    text text NOT NULL,
    PRIMARY KEY (doc_id, page)
);
CREATE TABLE IF NOT EXISTS chunks (
    chunk_id text PRIMARY KEY,
    doc_id text NOT NULL,
    page int NOT NULL,
    start_char int NOT NULL,
    end_char int NOT NULL,
    lang text NOT NULL,
    text text NOT NULL,
    search_text text NOT NULL,
    text_sha text NOT NULL,
    FOREIGN KEY (doc_id, page) REFERENCES pages ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS chunk_vectors (
    model_id text NOT NULL,
    chunk_id text REFERENCES chunks ON DELETE CASCADE,
    embedding vector NOT NULL,
    PRIMARY KEY (model_id, chunk_id)
);
