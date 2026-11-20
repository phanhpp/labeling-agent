-- Every table the system uses. Applied by app/db.py apply_schema; safe to run again.
-- LangGraph's checkpoint tables are separate: AsyncPostgresSaver.setup() creates them.

-- Policy versions. The body is the whole policy (header, sections, screen cut-off) as JSON.
CREATE TABLE IF NOT EXISTS policy_versions (
    name          text PRIMARY KEY,                 -- v1, v2, ...
    status        text NOT NULL CHECK (status IN ('draft', 'live', 'retired')),
    parent        text REFERENCES policy_versions (name),
    body          jsonb NOT NULL,
    content_hash  text NOT NULL,                    -- everything, effects included
    model_hash    text NOT NULL,                    -- only what the models see (app/policy.py model_view)
    author        text NOT NULL,
    edited_by     text[] NOT NULL DEFAULT '{}',     -- a publisher listed here can't publish (four eyes)
    tested_hash   text,                             -- content_hash of the last Test; Publish needs a match
    published_by  text,
    published_at  timestamptz,
    created_at    timestamptz NOT NULL DEFAULT now()
);

-- At most one live version.
CREATE UNIQUE INDEX IF NOT EXISTS one_live_policy ON policy_versions ((true)) WHERE status = 'live';

-- A version that has left draft can change status (live, retired) but never its content.
CREATE OR REPLACE FUNCTION freeze_published_policy() RETURNS trigger AS $$
BEGIN
    IF OLD.status <> 'draft' AND (NEW.body IS DISTINCT FROM OLD.body
                                  OR NEW.content_hash IS DISTINCT FROM OLD.content_hash) THEN
        RAISE EXCEPTION 'policy % is published and cannot be edited', OLD.name;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE TRIGGER policy_frozen
    BEFORE UPDATE ON policy_versions
    FOR EACH ROW EXECUTE FUNCTION freeze_published_policy();

-- Postings as submitted. A job id is unique only within one client.
CREATE TABLE IF NOT EXISTS postings (
    id          bigserial PRIMARY KEY,
    client_id   text NOT NULL,
    job_id      text NOT NULL,
    raw         jsonb NOT NULL,                     -- kept as sent, for audit
    raw_hash    text NOT NULL,                      -- same job id and hash: the same posting sent twice
    demo        boolean NOT NULL DEFAULT false,     -- loaded by the demo seeder, not submitted
    created_at  timestamptz NOT NULL DEFAULT now(),
    UNIQUE (client_id, job_id)
);

CREATE TABLE IF NOT EXISTS batches (
    id          bigserial PRIMARY KEY,
    client_id   text NOT NULL,
    created_at  timestamptz NOT NULL DEFAULT now()
);

-- The queue: one row per (posting, policy version) to label.
CREATE TABLE IF NOT EXISTS jobs (
    id              bigserial PRIMARY KEY,
    posting_id      bigint NOT NULL REFERENCES postings (id),
    policy_version  text NOT NULL REFERENCES policy_versions (name),
    policy_hash     text NOT NULL,                  -- content_hash when queued: a draft may change later
    queue           text NOT NULL CHECK (queue IN ('live', 'backfill', 'shadow')),
    status          text NOT NULL DEFAULT 'queued' CHECK (status IN ('queued', 'running', 'done', 'failed')),
    attempts        int NOT NULL DEFAULT 0,
    locked_at       timestamptz,
    batch_id        bigint REFERENCES batches (id),
    last_error      text,
    created_at      timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS jobs_to_claim ON jobs (status, queue, created_at);

-- One label per (posting, policy version, model version). Older versions' labels are kept.
CREATE TABLE IF NOT EXISTS labels (
    id              bigserial PRIMARY KEY,
    posting_id      bigint NOT NULL REFERENCES postings (id),
    policy_version  text NOT NULL,
    policy_hash     text NOT NULL,
    model_version   text NOT NULL,
    label           text NOT NULL CHECK (label IN ('VIOLATING', 'ALLOWED', 'NEEDS_REVIEW')),
    sections        text[] NOT NULL DEFAULT '{}',
    evidence        jsonb NOT NULL DEFAULT '[]',    -- verified quotes: text, field, start, end
    findings        jsonb NOT NULL DEFAULT '[]',    -- per section, after check
    raw_output      jsonb,                          -- the model's answer before check (re-decide uses it)
    facts           jsonb NOT NULL DEFAULT '{}',    -- e.g. which fields were empty
    screen          jsonb,                          -- screen used, scores, injection score, regex hits
    rationale       text NOT NULL DEFAULT '',
    confidence      real NOT NULL,
    reason_codes    text[] NOT NULL DEFAULT '{}',
    cleaned         jsonb NOT NULL,                 -- the text the model saw; quote positions point into it
    cache_key       text,
    derived_from    bigint REFERENCES labels (id),  -- copied from this label (cache hit or re-decide)
    cost_usd        numeric(10, 6) NOT NULL DEFAULT 0,
    latency_ms      int NOT NULL DEFAULT 0,
    trace_id        text,
    created_at      timestamptz NOT NULL DEFAULT now(),
    UNIQUE (posting_id, policy_version, model_version)
);

CREATE INDEX IF NOT EXISTS labels_by_posting ON labels (posting_id);
CREATE INDEX IF NOT EXISTS labels_by_cache_key ON labels (cache_key);

-- Analysts' decisions. The latest one per posting is final.
CREATE TABLE IF NOT EXISTS decisions (
    id              bigserial PRIMARY KEY,
    posting_id      bigint NOT NULL REFERENCES postings (id),
    label           text NOT NULL CHECK (label IN ('VIOLATING', 'ALLOWED', 'NEEDS_REVIEW')),
    note            text NOT NULL DEFAULT '',
    analyst         text NOT NULL,
    policy_version  text NOT NULL,                  -- the live version when the analyst decided
    created_at      timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS decisions_by_posting ON decisions (posting_id, created_at DESC);
