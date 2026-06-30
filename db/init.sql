CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TYPE message_status AS ENUM (
    'pending', 'processing', 'completed', 'failed', 'dead_lettered'
);

CREATE TABLE IF NOT EXISTS messages (
    message_id      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    customer_id     VARCHAR(64) NOT NULL,
    text            TEXT NOT NULL,
    text_normalized TEXT,
    channel         VARCHAR(32) NOT NULL DEFAULT 'web',
    status          message_status NOT NULL DEFAULT 'pending',
    retry_count     INTEGER NOT NULL DEFAULT 0,
    error_reason    TEXT,
    index_status    VARCHAR(30) NOT NULL DEFAULT 'pending',
    index_error     TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    processed_at    TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_messages_customer_created
    ON messages (customer_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_messages_status
    ON messages (status) WHERE status IN ('failed', 'dead_lettered');

CREATE INDEX IF NOT EXISTS idx_messages_index_status
    ON messages (index_status) WHERE index_status = 'failed';
