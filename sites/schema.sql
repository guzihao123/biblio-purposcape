-- Qoder Sites task primary store: PostgreSQL review material only.
-- DO NOT execute this file as a cloud migration from the adapter or tests.
-- The Provider must apply and authorize this schema through its reviewed migration flow.

BEGIN;

CREATE TABLE sites_anonymous_sessions (
    id              VARCHAR(64) PRIMARY KEY,
    client_ip       VARCHAR(64) NOT NULL DEFAULT '',
    user_agent      VARCHAR(300) NOT NULL DEFAULT '',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at      TIMESTAMPTZ,
    revoked_at      TIMESTAMPTZ
);

CREATE TABLE sites_skill_versions (
    id                  VARCHAR(64) PRIMARY KEY,
    version             BIGINT NOT NULL UNIQUE CHECK (version > 0),
    parent_id           VARCHAR(64) REFERENCES sites_skill_versions(id) ON DELETE SET NULL,
    state               VARCHAR(16) NOT NULL
                        CHECK (state IN ('draft', 'published', 'archived')),
    content             JSONB NOT NULL,
    content_hash        VARCHAR(64) NOT NULL,
    regression_report   JSONB,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    published_at        TIMESTAMPTZ
);

-- At most one published version; existing tasks retain their original version FK.
CREATE UNIQUE INDEX sites_one_published_skill
    ON sites_skill_versions (state)
    WHERE state = 'published';

CREATE TABLE sites_tasks (
    id                  VARCHAR(64) PRIMARY KEY,
    session_id          VARCHAR(64) NOT NULL
                        REFERENCES sites_anonymous_sessions(id) ON DELETE CASCADE,
    skill_version_id    VARCHAR(64) NOT NULL
                        REFERENCES sites_skill_versions(id) ON DELETE RESTRICT,
    idempotency_key     VARCHAR(255) NOT NULL,
    state               VARCHAR(32) NOT NULL CHECK (
                            state IN (
                                'collecting_mode', 'collecting_terms',
                                'collecting_years', 'searching', 'dashboard_ready',
                                'adjusting', 'delivery_confirmed', 'generating',
                                'verifying', 'done', 'error'
                            )
                        ),
    next_card           VARCHAR(32) CHECK (
                            next_card IS NULL OR next_card IN (
                                'direction', 'mode', 'terms', 'years',
                                'adjustment', 'delivery'
                            )
                        ),
    revision            BIGINT NOT NULL DEFAULT 1 CHECK (revision > 0),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_sites_tasks_session_idempotency_key
        UNIQUE (session_id, idempotency_key)
);

CREATE INDEX sites_tasks_owner_created
    ON sites_tasks (session_id, created_at DESC, id DESC);

CREATE TABLE sites_task_answers (
    task_id             VARCHAR(64) NOT NULL
                        REFERENCES sites_tasks(id) ON DELETE CASCADE,
    card_id             VARCHAR(32) NOT NULL CHECK (
                            card_id IN (
                                'direction', 'mode', 'terms', 'years',
                                'adjustment', 'delivery'
                            )
                        ),
    value               JSONB NOT NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (task_id, card_id)
);

CREATE TABLE sites_task_artifacts (
    task_id             VARCHAR(64) NOT NULL
                        REFERENCES sites_tasks(id) ON DELETE CASCADE,
    name                VARCHAR(255) NOT NULL,
    object_path         VARCHAR(1024) NOT NULL,
    size_bytes          BIGINT NOT NULL CHECK (size_bytes >= 0),
    content_type        VARCHAR(255) NOT NULL,
    checksum_sha256     VARCHAR(64),
    metadata            JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (task_id, name),
    UNIQUE (task_id, object_path)
);

-- Same-database quota accounting makes insert + charge one transaction. The
-- unique task key ensures only the winning insert charges this fixed window.
CREATE TABLE sites_task_quota_windows (
    session_id          VARCHAR(64) NOT NULL
                        REFERENCES sites_anonymous_sessions(id) ON DELETE CASCADE,
    window_start        TIMESTAMPTZ NOT NULL,
    used                INTEGER NOT NULL CHECK (used >= 0),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (session_id, window_start)
);

CREATE TABLE sites_task_jobs (
    id                  VARCHAR(64) PRIMARY KEY,
    task_id             VARCHAR(64) NOT NULL
                        REFERENCES sites_tasks(id) ON DELETE CASCADE,
    stage               VARCHAR(32) NOT NULL CHECK (stage IN ('search', 'generate')),
    input_hash          VARCHAR(64) NOT NULL CHECK (input_hash ~ '^[0-9a-f]{64}$'),
    status              VARCHAR(32) NOT NULL CHECK (
                            status IN ('pending', 'queued', 'started', 'completed', 'failed', 'interrupted')
                        ),
    attempt             INTEGER NOT NULL DEFAULT 0 CHECK (attempt >= 0),
    revision            BIGINT NOT NULL DEFAULT 1 CHECK (revision > 0),
    task_revision       BIGINT NOT NULL CHECK (task_revision > 0),
    lease_token         VARCHAR(64),
    next_retry_at       TIMESTAMPTZ,
    started_at          TIMESTAMPTZ,
    finished_at         TIMESTAMPTZ,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (task_id, stage, input_hash),
    UNIQUE (id, task_id),
    CHECK ((status = 'started') = (lease_token IS NOT NULL))
);

CREATE INDEX sites_task_jobs_recovery
    ON sites_task_jobs (status, next_retry_at, updated_at);

CREATE TABLE sites_task_progress (
    task_id             VARCHAR(64) NOT NULL
                        REFERENCES sites_tasks(id) ON DELETE CASCADE,
    job_id              VARCHAR(64) NOT NULL,
    message             VARCHAR(500) NOT NULL DEFAULT '',
    checkpoint          JSONB,
    protected_traceback TEXT,
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (task_id),
    FOREIGN KEY (job_id, task_id) REFERENCES sites_task_jobs(id, task_id) ON DELETE CASCADE
);

CREATE TABLE sites_task_events (
    id                  BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    task_id             VARCHAR(64) NOT NULL,
    job_id              VARCHAR(64),
    event_type          VARCHAR(64) NOT NULL,
    event_key           VARCHAR(160) NOT NULL UNIQUE,
    payload             JSONB NOT NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    FOREIGN KEY (job_id, task_id) REFERENCES sites_task_jobs(id, task_id) ON DELETE CASCADE
);

CREATE INDEX sites_task_events_job_order
    ON sites_task_events (job_id, id);

COMMIT;
