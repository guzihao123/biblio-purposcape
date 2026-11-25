// Server-only Qoder Sites task store. No browser bundle should import this file.
// Adapter contract: database.transaction(async (tx) => value), where tx.query(
// staticSql, boundParameters) returns { rows }. The SQL below is never accepted
// from a request, an owner, or a caller. Real Provider permissions and transaction
// atomicity are intentionally not claimed by the local fake-database tests.

const JSON_HEADERS = Object.freeze({
  'content-type': 'application/json; charset=utf-8',
  'cache-control': 'no-store',
});
const MAX_WORKER_BODY_BYTES = 2_000_000;
const MAX_ARTIFACT_BYTES = 50_000_000;
const ID_PATTERN = /^[A-Za-z0-9-]{1,64}$/;
const SHA256_PATTERN = /^[0-9a-f]{64}$/;
const CONTENT_TYPE_PATTERN = /^[A-Za-z0-9!#$&^_.+-]+\/[A-Za-z0-9!#$&^_.+-]+$/;
const TASK_STATES = new Set([
  'collecting_mode', 'collecting_terms', 'collecting_years', 'searching',
  'dashboard_ready', 'adjusting', 'delivery_confirmed', 'generating',
  'verifying', 'done', 'error',
]);
const NEXT_CARDS = new Set(['direction', 'mode', 'terms', 'years', 'adjustment', 'delivery']);
const SKILL_STATES = new Set(['draft', 'published', 'archived']);

const TASK_COLUMNS = `
  id, session_id, skill_version_id, idempotency_key, state, next_card,
  revision, created_at, updated_at
`;
const ARTIFACT_COLUMNS = `
  task_id, name, object_path, size_bytes, content_type, checksum_sha256,
  metadata, created_at, updated_at
`;
const JOB_COLUMNS = `
  id, task_id, stage, input_hash, status, attempt, revision, task_revision,
  lease_token, next_retry_at, started_at, finished_at, created_at, updated_at
`;
const PROGRESS_COLUMNS = `
  task_id, job_id, message, checkpoint, protected_traceback, updated_at
`;

// Operation comments are also used by the local fake adapter to reject anything
// outside this fixed statement allowlist. They are not request-provided labels.
const SQL = Object.freeze({
  createSession: `/* create_session */
    INSERT INTO sites_anonymous_sessions (
      id, client_ip, user_agent, created_at, last_seen_at, expires_at, revoked_at
    )
    VALUES ($1, $2, $3, $4, $4, $5, $6)
    RETURNING id, client_ip, user_agent, created_at, last_seen_at, expires_at, revoked_at`,
  getSession: `/* get_session */
    SELECT id, client_ip, user_agent, created_at, last_seen_at, expires_at, revoked_at
    FROM sites_anonymous_sessions WHERE id = $1`,
  getLatestPublishedSkill: `/* get_latest_published_skill */
    SELECT id, version, parent_id, state, content, content_hash, regression_report,
      created_at, published_at FROM sites_skill_versions
    WHERE state = 'published' ORDER BY version DESC LIMIT 1`,
  upsertSkill: `/* upsert_skill_version */
    INSERT INTO sites_skill_versions (
      id, version, parent_id, state, content, content_hash, regression_report,
      created_at, published_at
    ) VALUES ($1, $2, $3, $4, $5::jsonb, $6, $7::jsonb, $8, $9)
    ON CONFLICT (id) DO UPDATE SET
      version = EXCLUDED.version, parent_id = EXCLUDED.parent_id,
      state = EXCLUDED.state, content = EXCLUDED.content,
      content_hash = EXCLUDED.content_hash,
      regression_report = EXCLUDED.regression_report,
      published_at = EXCLUDED.published_at
    RETURNING id, version, parent_id, state, content, content_hash,
      regression_report, created_at, published_at`,
  getPublishedSkill: `/* get_published_skill */
    SELECT id FROM sites_skill_versions WHERE id = $1 AND state = 'published'`,
  getSkillVersion: `/* get_skill_version */
    SELECT id, version, parent_id, state, content, content_hash, regression_report,
      created_at, published_at FROM sites_skill_versions WHERE id = $1`,
  findTaskByKey: `/* find_task_by_key */
    SELECT ${TASK_COLUMNS} FROM sites_tasks
    WHERE session_id = $1 AND idempotency_key = $2`,
  insertTask: `/* insert_task */
    INSERT INTO sites_tasks (
      id, session_id, skill_version_id, idempotency_key, state, next_card,
      created_at, updated_at
    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $7)
    ON CONFLICT (session_id, idempotency_key) DO NOTHING
    RETURNING ${TASK_COLUMNS}`,
  consumeQuota: `/* consume_task_quota */
    INSERT INTO sites_task_quota_windows (
      session_id, window_start, used, created_at, updated_at
    )
    SELECT $1, $2, $4, $5, $5 WHERE $4 <= $3
    ON CONFLICT (session_id, window_start) DO UPDATE SET
      used = sites_task_quota_windows.used + $4,
      updated_at = $5
    WHERE sites_task_quota_windows.used + $4 <= $3
    RETURNING used`,
  getOwnedTask: `/* get_owned_task */
    SELECT ${TASK_COLUMNS} FROM sites_tasks
    WHERE id = $1 AND session_id = $2`,
  listOwnedTasks: `/* list_owned_tasks */
    SELECT ${TASK_COLUMNS} FROM sites_tasks
    WHERE session_id = $1
    ORDER BY created_at DESC, id DESC LIMIT $2 OFFSET $3`,
  updateOwnedTaskState: `/* update_owned_task_state */
    UPDATE sites_tasks SET
      state = $3, next_card = $4, revision = revision + 1, updated_at = $6
    WHERE id = $1 AND session_id = $2 AND revision = $5
    RETURNING ${TASK_COLUMNS}`,
  getTaskAnswer: `/* get_task_answer */
    SELECT task_id, card_id, value, created_at, updated_at FROM sites_task_answers
    WHERE task_id = $1 AND card_id = $2`,
  listTaskAnswers: `/* list_task_answers */
    SELECT task_id, card_id, value, created_at, updated_at FROM sites_task_answers
    WHERE task_id = $1 ORDER BY card_id`,
  insertTaskAnswer: `/* insert_task_answer */
    INSERT INTO sites_task_answers (task_id, card_id, value, created_at, updated_at)
    VALUES ($1, $2, $3::jsonb, $4, $4)
    RETURNING task_id, card_id, value, created_at, updated_at`,
  updateTaskAnswer: `/* update_task_answer */
    UPDATE sites_task_answers SET value = $3::jsonb, updated_at = $4
    WHERE task_id = $1 AND card_id = $2
    RETURNING task_id, card_id, value, created_at, updated_at`,
  listOwnedArtifacts: `/* list_owned_artifacts */
    SELECT ${ARTIFACT_COLUMNS} FROM sites_task_artifacts
    WHERE task_id = $1
      AND EXISTS (
        SELECT 1 FROM sites_tasks WHERE id = $1 AND session_id = $2
      )
    ORDER BY name`,
  upsertOwnedArtifact: `/* upsert_owned_artifact */
    INSERT INTO sites_task_artifacts (
      task_id, name, object_path, size_bytes, content_type, checksum_sha256,
      metadata, created_at, updated_at
    )
    SELECT $1, $3, $4, $5, $6, $7, $8::jsonb, $9, $9
    WHERE EXISTS (SELECT 1 FROM sites_tasks WHERE id = $1 AND session_id = $2)
    ON CONFLICT (task_id, name) DO UPDATE SET
      object_path = EXCLUDED.object_path, size_bytes = EXCLUDED.size_bytes,
      content_type = EXCLUDED.content_type, checksum_sha256 = EXCLUDED.checksum_sha256,
      metadata = EXCLUDED.metadata, updated_at = EXCLUDED.updated_at
    RETURNING ${ARTIFACT_COLUMNS}`,
  getStageJobNatural: `/* get_stage_job_natural */
    SELECT ${JOB_COLUMNS} FROM sites_task_jobs
    WHERE task_id = $1 AND stage = $2 AND input_hash = $3`,
  getStageJob: `/* get_stage_job */
    SELECT ${JOB_COLUMNS} FROM sites_task_jobs WHERE id = $1 AND task_id = $2`,
  insertStageJob: `/* insert_stage_job */
    INSERT INTO sites_task_jobs (
      id, task_id, stage, input_hash, status, task_revision
    ) SELECT $1, $2, $3, $4, 'queued', $5
    WHERE EXISTS (SELECT 1 FROM sites_tasks WHERE id = $2)
    ON CONFLICT (task_id, stage, input_hash) DO NOTHING
    RETURNING ${JOB_COLUMNS}`,
  getJobProgress: `/* get_job_progress */
    SELECT ${PROGRESS_COLUMNS} FROM sites_task_progress WHERE task_id = $1`,
  getLatestTaskProgress: `/* get_latest_task_progress */
    SELECT ${PROGRESS_COLUMNS}, sites_task_jobs.stage, sites_task_jobs.input_hash
    FROM sites_task_progress
    JOIN sites_task_jobs ON sites_task_jobs.id = sites_task_progress.job_id
    WHERE sites_task_progress.task_id = $1`,
  upsertJobProgress: `/* upsert_job_progress */
    INSERT INTO sites_task_progress (task_id, job_id, message, checkpoint, protected_traceback, updated_at)
    SELECT $1, $2, $3, $4::jsonb, $5, now()
    WHERE EXISTS (SELECT 1 FROM sites_task_jobs WHERE id = $2 AND task_id = $1)
    ON CONFLICT (task_id) DO UPDATE SET
      job_id = EXCLUDED.job_id, message = EXCLUDED.message,
      checkpoint = EXCLUDED.checkpoint,
      protected_traceback = EXCLUDED.protected_traceback,
      updated_at = EXCLUDED.updated_at
    RETURNING ${PROGRESS_COLUMNS}`,
  appendJobEvent: `/* append_job_event */
    INSERT INTO sites_task_events (task_id, job_id, event_type, event_key, payload, created_at)
    SELECT $1, $2, $3, $4, $5::jsonb, now()
    WHERE EXISTS (SELECT 1 FROM sites_task_jobs WHERE id = $2 AND task_id = $1)
    ON CONFLICT (event_key) DO NOTHING
    RETURNING id, task_id, job_id, event_type, event_key, payload, created_at`,
  updateJobStarted: `/* update_job_started */
    UPDATE sites_task_jobs SET
      status = 'started', attempt = attempt + 1, revision = revision + 1,
      lease_token = $4, started_at = now(), updated_at = now()
    WHERE id = $1 AND task_id = $2 AND revision = $3 AND status = 'queued'
      AND (next_retry_at IS NULL OR next_retry_at <= now())
    RETURNING ${JOB_COLUMNS}`,
  updateJobCompleted: `/* update_job_completed */
    UPDATE sites_task_jobs SET
      status = 'completed', revision = revision + 1, lease_token = NULL,
      finished_at = now(), updated_at = now()
    WHERE id = $1 AND task_id = $2 AND revision = $3
      AND status = 'started' AND lease_token = $4 AND input_hash = $5
    RETURNING ${JOB_COLUMNS}`,
  updateJobFailed: `/* update_job_failed */
    UPDATE sites_task_jobs SET
      status = 'failed', revision = revision + 1, lease_token = NULL,
      next_retry_at = $5, finished_at = now(), updated_at = now()
    WHERE id = $1 AND task_id = $2 AND revision = $3
      AND (status = 'queued' OR (status = 'started' AND lease_token = $4))
    RETURNING ${JOB_COLUMNS}`,
  retryStageJob: `/* retry_stage_job */
    UPDATE sites_task_jobs SET
      status = 'queued', revision = revision + 1, task_revision = $4,
      lease_token = NULL, next_retry_at = NULL, started_at = NULL, finished_at = NULL, updated_at = now()
    WHERE id = $1 AND task_id = $2 AND revision = $3 AND status = 'failed'
      AND (next_retry_at IS NULL OR next_retry_at <= now())
    RETURNING ${JOB_COLUMNS}`,
  updateTaskAfterStage: `/* update_task_after_stage */
    UPDATE sites_tasks SET
      state = $3, next_card = $4, revision = revision + 1, updated_at = now()
    WHERE id = $1 AND session_id = $2 AND revision = $5
    RETURNING ${TASK_COLUMNS}`,
  listJobEvents: `/* list_job_events */
    SELECT id, task_id, job_id, event_type, event_key, payload, created_at
    FROM sites_task_events WHERE job_id = $1 ORDER BY id`,
  appendTaskEvent: `/* append_task_event */
    INSERT INTO sites_task_events (task_id, job_id, event_type, event_key, payload, created_at)
    SELECT $1, NULL, $2, $3, $4::jsonb, now()
    WHERE EXISTS (SELECT 1 FROM sites_tasks WHERE id = $1)
    ON CONFLICT (event_key) DO NOTHING
    RETURNING id, task_id, job_id, event_type, event_key, payload, created_at`,
  getLatestTermsEvent: `/* get_latest_terms_event */
    SELECT id, task_id, job_id, event_type, event_key, payload, created_at
    FROM sites_task_events
    WHERE task_id = $1 AND event_type IN ('terms_candidates', 'terms_candidates_unavailable')
    ORDER BY id DESC LIMIT 1`,
});

type TaskState = 'collecting_mode' | 'collecting_terms' | 'collecting_years' | 'searching' |
  'dashboard_ready' | 'adjusting' | 'delivery_confirmed' | 'generating' | 'verifying' | 'done' | 'error';
type NextCard = 'direction' | 'mode' | 'terms' | 'years' | 'adjustment' | 'delivery';
type SkillState = 'draft' | 'published' | 'archived';
type SqlParameter = string | number | null;
type JsonObject = Record<string, unknown>;

interface QueryResult<Row> {
  rows: Row[];
}

interface Transaction {
  query<Row>(sql: string, parameters?: SqlParameter[]): Promise<QueryResult<Row>>;
}

interface DatabaseAdapter {
  transaction<Value>(work: (tx: Transaction) => Promise<Value>): Promise<Value>;
}

interface TaskStoreOptions {
  database: DatabaseAdapter;
  clock?: () => unknown;
  idFactory?: () => string;
  sessionTtlSeconds?: number;
}

interface TaskStoreErrorDetails {
  retry_after?: number;
}

interface SessionRow {
  id: string;
  client_ip: string;
  user_agent: string;
  created_at: unknown;
  last_seen_at: unknown;
  expires_at?: unknown;
  revoked_at?: unknown;
}

interface SkillVersionRow {
  id: string;
  version: number;
  parent_id: string | null;
  state: SkillState;
  content: JsonObject;
  content_hash: string;
  regression_report: JsonObject | null;
  created_at: unknown;
  published_at: unknown;
}

interface TaskRecord {
  id: string;
  session_id: string;
  skill_version_id: string;
  idempotency_key: string;
  state: TaskState;
  next_card: NextCard | null;
  revision: string | number;
  created_at: unknown;
  updated_at: unknown;
}

interface TaskDTO {
  id: string;
  session_id: string;
  skill_version_id: string;
  idempotency_key: string;
  state: TaskState;
  next_card: NextCard | null;
  revision: number;
  created_at: string;
  updated_at: string;
}

interface ArtifactRecord {
  task_id: string;
  name: string;
  object_path: string;
  size_bytes: string | number;
  content_type: string;
  checksum_sha256?: string | null;
  metadata?: string | JsonObject | null;
  created_at: unknown;
  updated_at: unknown;
}

interface ArtifactDTO {
  task_id: string;
  name: string;
  object_path: string;
  size_bytes: number;
  content_type: string;
  checksum_sha256: string | null;
  metadata: JsonObject;
  created_at: string;
  updated_at: string;
}

interface StageJobRecord {
  id: string;
  task_id: string;
  stage: 'search' | 'generate';
  input_hash: string;
  status: 'pending' | 'queued' | 'started' | 'completed' | 'failed' | 'interrupted';
  attempt: number;
  revision: number;
  task_revision: number;
  lease_token: string | null;
  next_retry_at: unknown;
  started_at: unknown;
  finished_at: unknown;
  created_at: unknown;
  updated_at: unknown;
}

interface StageProgressRecord {
  task_id: string;
  job_id: string;
  message: string;
  checkpoint: JsonObject | string | null;
  protected_traceback: string | null;
  updated_at: unknown;
  stage?: 'search' | 'generate';
  input_hash?: string;
}

interface StageEventRecord {
  id: number;
  task_id: string;
  job_id: string;
  event_type: string;
  event_key: string;
  payload: JsonObject | string;
  created_at: unknown;
}

interface ParsedArtifactInput {
  name: string;
  object_path: string;
  size_bytes: number;
  content_type: string;
  checksum_sha256: string | null;
  metadata: string;
}

interface Quota {
  limit: number;
  windowSeconds: number;
  cost: number;
}

export class TaskStoreError extends Error {
  code: string;
  status: number;
  details: TaskStoreErrorDetails | undefined;

  constructor(code: string, status = 503, details: TaskStoreErrorDetails | undefined = undefined) {
    super(code);
    this.name = 'TaskStoreError';
    this.code = code;
    this.status = status;
    this.details = details;
  }
}

function fail(code: string, status = 422, details: TaskStoreErrorDetails | undefined = undefined): never {
  throw new TaskStoreError(code, status, details);
}

function validId(value: unknown, field = 'id'): string {
  if (typeof value !== 'string' || !ID_PATTERN.test(value)) fail(`invalid_${field}`);
  return value;
}

function validIdempotencyKey(value: unknown): string {
  if (typeof value !== 'string') fail('invalid_idempotency_key');
  const key = value.trim();
  if (!key || key.length > 255) fail('invalid_idempotency_key');
  return key;
}

function validState(value: unknown): TaskState {
  if (typeof value !== 'string' || !TASK_STATES.has(value)) fail('invalid_task_state');
  return value as TaskState;
}

function validNextCard(value: unknown): NextCard | null {
  if (value !== null && (typeof value !== 'string' || !NEXT_CARDS.has(value))) {
    fail('invalid_next_card');
  }
  return value as NextCard | null;
}

function positiveInteger(value: unknown, field: string): number {
  if (typeof value !== 'number' || !Number.isSafeInteger(value) || value < 1) fail(`invalid_${field}`);
  return value;
}

function plainObject(value: unknown, field = 'metadata'): JsonObject {
  if (value === null || typeof value !== 'object' || Array.isArray(value)) {
    fail(`invalid_${field}`);
  }
  return value as JsonObject;
}

function jsonValue(value: unknown, field: string, maxBytes: number): string {
  plainObject(value, field);
  let encoded: string | undefined;
  try {
    encoded = JSON.stringify(value);
  } catch {
    fail(`invalid_${field}`);
  }
  if (encoded === undefined || new TextEncoder().encode(encoded).byteLength > maxBytes) {
    fail(`invalid_${field}`);
  }
  return encoded;
}

function isoTime(value: unknown): string {
  const date = value instanceof Date ? value : new Date(value as string | number);
  if (Number.isNaN(date.getTime())) fail('invalid_timestamp');
  return date.toISOString();
}

function taskRow(row: TaskRecord | null): TaskDTO | null {
  if (!row) return null;
  return {
    id: row.id,
    session_id: row.session_id,
    skill_version_id: row.skill_version_id,
    idempotency_key: row.idempotency_key,
    state: row.state,
    next_card: row.next_card,
    revision: Number(row.revision),
    created_at: isoTime(row.created_at),
    updated_at: isoTime(row.updated_at),
  };
}

function artifactRow(row: ArtifactRecord): ArtifactDTO {
  return {
    task_id: row.task_id,
    name: row.name,
    object_path: row.object_path,
    size_bytes: Number(row.size_bytes),
    content_type: row.content_type,
    checksum_sha256: row.checksum_sha256 || null,
    metadata: (typeof row.metadata === 'string' ? JSON.parse(row.metadata) : (row.metadata || {})) as JsonObject,
    created_at: isoTime(row.created_at),
    updated_at: isoTime(row.updated_at),
  };
}

function stageJobRow(row: StageJobRecord) {
  return {
    ...row,
    attempt: Number(row.attempt),
    revision: Number(row.revision),
    task_revision: Number(row.task_revision),
    next_retry_at: row.next_retry_at ? isoTime(row.next_retry_at) : null,
    started_at: row.started_at ? isoTime(row.started_at) : null,
    finished_at: row.finished_at ? isoTime(row.finished_at) : null,
    created_at: isoTime(row.created_at),
    updated_at: isoTime(row.updated_at),
  };
}

function stageProgressRow(row: StageProgressRecord) {
  return {
    ...row,
    checkpoint: row.checkpoint == null
      ? null
      : (typeof row.checkpoint === 'string' ? JSON.parse(row.checkpoint) : row.checkpoint),
    updated_at: isoTime(row.updated_at),
  };
}

function stageEventRow(row: StageEventRecord) {
  return {
    ...row,
    id: Number(row.id),
    payload: (typeof row.payload === 'string' ? JSON.parse(row.payload) : row.payload) as JsonObject,
    created_at: isoTime(row.created_at),
  };
}

function artifactInput(taskId: string, value: unknown): ParsedArtifactInput {
  const input = plainObject(value, 'artifact');
  const name = input.name;
  if (
    typeof name !== 'string' || !name || name.length > 255 || name === '.' || name === '..' ||
    name.includes('/') || name.includes('\\') || /[\u0000-\u001f]/.test(name)
  ) fail('invalid_artifact_name');
  const size = input.size_bytes;
  if (typeof size !== 'number' || !Number.isSafeInteger(size) || size < 0 || size > MAX_ARTIFACT_BYTES) {
    fail('invalid_artifact_size');
  }
  const contentType = input.content_type || 'application/octet-stream';
  if (typeof contentType !== 'string' || contentType.length > 255 || !CONTENT_TYPE_PATTERN.test(contentType)) {
    fail('invalid_artifact_content_type');
  }
  const checksum = input.checksum_sha256 == null ? null : String(input.checksum_sha256).toLowerCase();
  if (checksum !== null && !SHA256_PATTERN.test(checksum)) fail('invalid_artifact_checksum');
  const objectPath = `artifacts/${taskId}/${name}`;
  if (input.object_path !== undefined && input.object_path !== objectPath) fail('invalid_artifact_path');
  return {
    name,
    object_path: objectPath,
    size_bytes: size,
    content_type: contentType,
    checksum_sha256: checksum,
    metadata: jsonValue(input.metadata || {}, 'artifact_metadata', 16_384),
  };
}

function quotaInput(value: unknown): Quota {
  const input = plainObject(value, 'quota');
  return {
    limit: positiveInteger(input.limit, 'quota_limit'),
    windowSeconds: positiveInteger(input.window_seconds, 'quota_window'),
    cost: input.cost === undefined ? 1 : positiveInteger(input.cost, 'quota_cost'),
  };
}

function quotaWindow(now: Date, windowSeconds: number) {
  const duration = windowSeconds * 1000;
  const start = Math.floor(now.getTime() / duration) * duration;
  return {
    start: new Date(start).toISOString(),
    retryAfter: Math.max(1, Math.ceil((start + duration - now.getTime()) / 1000)),
  };
}

export function createTaskStore({
  database,
  clock = () => new Date(),
  idFactory = () => crypto.randomUUID(),
  sessionTtlSeconds = 604800,
}: TaskStoreOptions) {
  if (!database || typeof database.transaction !== 'function') {
    throw new TaskStoreError('invalid_database_adapter', 503);
  }

  async function run<Value>(work: (tx: Transaction) => Promise<Value>): Promise<Value> {
    try {
      return await database.transaction(work);
    } catch (error) {
      if (error instanceof TaskStoreError) throw error;
      // Do not preserve a Provider error as `cause`: it may contain SQL or secrets.
      throw new TaskStoreError('task_store_unavailable', 503);
    }
  }

  async function one<Row>(tx: Transaction, sql: string, parameters: SqlParameter[] = []): Promise<Row | null> {
    const result = await tx.query<Row>(sql, parameters);
    return result && Array.isArray(result.rows) ? (result.rows[0] || null) : null;
  }

  async function many<Row>(tx: Transaction, sql: string, parameters: SqlParameter[] = []): Promise<Row[]> {
    const result = await tx.query<Row>(sql, parameters);
    return result && Array.isArray(result.rows) ? result.rows : [];
  }

  async function aggregate(tx: Transaction, owned: TaskRecord) {
    const rows = await many<{ card_id: string; value: unknown }>(tx, SQL.listTaskAnswers, [owned.id]);
    const answers = Object.fromEntries(rows.map((row) => [row.card_id, row.value]));
    const latest = await one<StageProgressRecord>(tx, SQL.getLatestTaskProgress, [owned.id]);
    return {
      ...taskRow(owned),
      answers,
      progress: latest ? stageProgressRow(latest) : { stage: 'collecting', checkpoint: null, traceback: null },
    };
  }

  async function stageDetails(tx: Transaction, owned: TaskRecord, job: StageJobRecord) {
    const progress = await one<StageProgressRecord>(tx, SQL.getJobProgress, [owned.id]);
    const events = await many<StageEventRecord>(tx, SQL.listJobEvents, [job.id]);
    return {
      job: stageJobRow(job),
      progress: progress ? stageProgressRow(progress) : {
        task_id: owned.id,
        job_id: job.id,
        message: '',
        checkpoint: null,
        protected_traceback: null,
        updated_at: null,
      },
      events: events.map(stageEventRow),
      task: taskRow(owned),
    };
  }

  function stageName(value: unknown): 'search' | 'generate' {
    if (value !== 'search' && value !== 'generate') fail('invalid_stage', 422);
    return value;
  }

  function stageHash(value: unknown): string {
    if (typeof value !== 'string' || !SHA256_PATTERN.test(value)) fail('invalid_input_hash', 422);
    return value;
  }

  function stageMessage(value: unknown): string {
    if (typeof value !== 'string' || value.length > 500) fail('invalid_stage_message', 422);
    return value;
  }

  function stageLease(value: unknown): string {
    return validId(value, 'lease_token');
  }

  return Object.freeze({
    async createAnonymousSession({ clientIp = '', userAgent = '', id = undefined, expiresAt = undefined, revokedAt = null }: {
      clientIp?: unknown;
      userAgent?: unknown;
      id?: unknown;
      expiresAt?: unknown;
      revokedAt?: unknown;
    } = {}) {
      if (typeof clientIp !== 'string' || clientIp.length > 64 || typeof userAgent !== 'string') {
        fail('invalid_session_metadata');
      }
      const sessionId = validId(id === undefined ? idFactory() : id, 'session_id');
      const now = isoTime(clock());
      const expires = expiresAt === undefined
        ? new Date(new Date(now).getTime() + sessionTtlSeconds * 1000).toISOString()
        : isoTime(expiresAt);
      const revoked = revokedAt === null ? null : isoTime(revokedAt);
      return run(async (tx) => one<SessionRow>(
        tx, SQL.createSession, [sessionId, clientIp, userAgent.slice(0, 300), now, expires, revoked],
      ));
    },

    async getAnonymousSession(sessionId: unknown) {
      const ownerId = validId(sessionId, 'session_id');
      return run((tx) => one<SessionRow>(tx, SQL.getSession, [ownerId]));
    },

    async getSessionRecord({ sessionId }: { sessionId: unknown }) {
      const ownerId = validId(sessionId, 'session_id');
      return run(async (tx) => {
        const session = await one<SessionRow>(tx, SQL.getSession, [ownerId]);
        if (!session) fail('session_not_found', 401);
        if (session.revoked_at) fail('session_not_found', 401);
        if (session.expires_at && new Date(session.expires_at as string).getTime() <= new Date(isoTime(clock())).getTime()) {
          fail('session_not_found', 401);
        }
        return session;
      });
    },

    async getPublishedSkillVersion() {
      return run(async (tx) => {
        const skill = await one(tx, SQL.getLatestPublishedSkill, []);
        if (!skill) fail('skill_version_unavailable', 409);
        return skill;
      });
    },

    async getSkillVersion({ skillVersionId }: { skillVersionId: unknown }) {
      const id = validId(skillVersionId, 'skill_version_id');
      return run(async (tx) => {
        const skill = await one(tx, SQL.getSkillVersion, [id]);
        if (!skill) fail('skill_version_unavailable', 409);
        return skill;
      });
    },

    // Trusted server/worker operation; never expose it as a public browser route.
    async upsertSkillVersion(value: unknown) {
      const input = plainObject(value, 'skill_version');
      const id = validId(input.id, 'skill_version_id');
      const version = positiveInteger(input.version, 'skill_version');
      const state = input.state;
      if (typeof state !== 'string' || !SKILL_STATES.has(state)) fail('invalid_skill_state');
      const contentHash = input.content_hash;
      if (typeof contentHash !== 'string' || !SHA256_PATTERN.test(contentHash)) {
        fail('invalid_skill_content_hash');
      }
      const parentId = input.parent_id == null ? null : validId(input.parent_id, 'parent_skill_version_id');
      const content = jsonValue(input.content, 'skill_content', 1_000_000);
      const report = input.regression_report == null
        ? null : jsonValue(input.regression_report, 'regression_report', 500_000);
      const createdAt = isoTime(input.created_at || clock());
      const publishedAt = input.published_at == null ? null : isoTime(input.published_at);
      return run((tx) => one<SkillVersionRow>(tx, SQL.upsertSkill, [
        id, version, parentId, state, content, contentHash,
        report, createdAt, publishedAt,
      ]));
    },

    async createTask({
      sessionId, idempotencyKey, skillVersionId, quota,
      state = 'collecting_mode', nextCard = 'direction', taskId = undefined,
    }: {
      sessionId: unknown;
      idempotencyKey: unknown;
      skillVersionId: unknown;
      quota: unknown;
      state?: unknown;
      nextCard?: unknown;
      taskId?: unknown;
    }) {
      const ownerId = validId(sessionId, 'session_id');
      const key = validIdempotencyKey(idempotencyKey);
      const skillId = validId(skillVersionId, 'skill_version_id');
      const initialState = validState(state);
      const initialNextCard = validNextCard(nextCard);
      const allowance = quotaInput(quota);
      const id = validId(taskId === undefined ? idFactory() : taskId, 'task_id');
      const now = isoTime(clock());
      const window = quotaWindow(new Date(now), allowance.windowSeconds);

      return run(async (tx) => {
        // A replay is resolved before skill/quota work and can never reset state.
        const existing = await one<TaskRecord>(tx, SQL.findTaskByKey, [ownerId, key]);
        if (existing) return { task: taskRow(existing), replayed: true };

        const session = await one<SessionRow>(tx, SQL.getSession, [ownerId]);
        if (!session || session.revoked_at || (
          session.expires_at && new Date(session.expires_at as string).getTime() <= new Date(now).getTime()
        )) {
          fail('session_not_found', 401);
        }
        if (!await one<{ id: string }>(tx, SQL.getPublishedSkill, [skillId])) {
          fail('skill_version_unavailable', 409);
        }

        const inserted = await one<TaskRecord>(tx, SQL.insertTask, [
          id, ownerId, skillId, key, initialState, initialNextCard, now,
        ]);
        if (!inserted) {
          // ON CONFLICT waits for a competing insert; only that winner charges.
          const winner = await one<TaskRecord>(tx, SQL.findTaskByKey, [ownerId, key]);
          if (!winner) fail('task_store_unavailable', 503);
          return { task: taskRow(winner), replayed: true };
        }

        const charged = await one<{ used: number }>(tx, SQL.consumeQuota, [
          ownerId, window.start, allowance.limit, allowance.cost, now,
        ]);
        if (!charged) {
          // Throwing rolls back both the new task and the quota statement.
          fail('quota_exceeded', 429, { retry_after: window.retryAfter });
        }
        return { task: taskRow(inserted), replayed: false };
      });
    },

    async getTaskAggregate({ sessionId, taskId }: { sessionId: unknown; taskId: unknown }) {
      const ownerId = validId(sessionId, 'session_id');
      const id = validId(taskId, 'task_id');
      return run(async (tx) => {
        const owned = await one<TaskRecord>(tx, SQL.getOwnedTask, [id, ownerId]);
        return owned ? aggregate(tx, owned) : null;
      });
    },

    async submitDirectionAnswer({ sessionId, taskId, expectedRevision, value }: {
      sessionId: unknown;
      taskId: unknown;
      expectedRevision: unknown;
      value: unknown;
    }) {
      const ownerId = validId(sessionId, 'session_id');
      const id = validId(taskId, 'task_id');
      const revision = positiveInteger(expectedRevision, 'expected_revision');
      if (typeof value !== 'string' || !value.trim() || value.trim().length > 2000) {
        fail('invalid_direction', 422);
      }
      const direction = value.trim();
      const now = isoTime(clock());
      return run(async (tx) => {
        const owned = await one<TaskRecord>(tx, SQL.getOwnedTask, [id, ownerId]);
        if (!owned) fail('task_not_found', 404);
        if (Number(owned.revision) !== revision) fail('revision_conflict', 409);
        const existing = await one<{ value: unknown }>(tx, SQL.getTaskAnswer, [id, 'direction']);
        if (existing) {
          if (existing.value !== direction) fail('answer_conflict', 422);
          return { task: await aggregate(tx, owned), changed: false };
        }
        await one(tx, SQL.insertTaskAnswer, [id, 'direction', JSON.stringify(direction), now]);
        const updated = await one<TaskRecord>(tx, SQL.updateOwnedTaskState, [
          id, ownerId, 'collecting_mode', 'mode', revision, now,
        ]);
        if (!updated) fail('revision_conflict', 409);
        return { task: await aggregate(tx, updated), changed: true };
      });
    },

    async submitCardAnswer({ sessionId, taskId, cardId, expectedRevision, nextState, nextCard, value, allowRevision = false }: {
      sessionId: unknown;
      taskId: unknown;
      cardId: string;
      expectedRevision: unknown;
      nextState: TaskState;
      nextCard: NextCard | null;
      value: unknown;
      allowRevision?: boolean;
    }) {
      const ownerId = validId(sessionId, 'session_id');
      const id = validId(taskId, 'task_id');
      const revision = positiveInteger(expectedRevision, 'expected_revision');
      if (!NEXT_CARDS.has(cardId)) fail('invalid_answer', 422);
      let resultState = validState(nextState);
      let card = validNextCard(nextCard);
      const now = isoTime(clock());
      return run(async (tx) => {
        const owned = await one<TaskRecord>(tx, SQL.getOwnedTask, [id, ownerId]);
        if (!owned) fail('task_not_found', 404);
        if (Number(owned.revision) !== revision) fail('revision_conflict', 409);
        const existing = await one<{ value: unknown }>(tx, SQL.getTaskAnswer, [id, cardId]);
        const unchanged = existing
          ? JSON.stringify(existing.value) === JSON.stringify(value)
          : false;
        const answeringCurrentCard = owned.next_card === cardId;
        if (!answeringCurrentCard) {
          if (unchanged) return { task: await aggregate(tx, owned), changed: false };
          fail('answer_conflict', 422);
        }
        if (existing && !allowRevision) fail('answer_conflict', 422);

        if (existing && ['mode', 'terms', 'years'].includes(cardId)) {
          const adjustment = await one<{ value: unknown }>(tx, SQL.getTaskAnswer, [id, 'adjustment']);
          const adjustmentValue = adjustment?.value;
          const selected = adjustmentValue && typeof adjustmentValue === 'object' &&
              !Array.isArray(adjustmentValue) &&
              Array.isArray((adjustmentValue as JsonObject).adjustment)
            ? (adjustmentValue as JsonObject).adjustment as unknown[]
            : [];
          const position = selected.indexOf(cardId);
          if (position >= 0) {
            const following = selected[position + 1];
            if (following === 'mode' || following === 'terms' || following === 'years') {
              resultState = following === 'mode'
                ? 'collecting_mode'
                : following === 'terms' ? 'collecting_terms' : 'collecting_years';
              card = following;
            } else {
              resultState = 'searching';
              card = null;
            }
          }
        }

        if (existing) {
          if (!unchanged) {
            const saved = await one(tx, SQL.updateTaskAnswer, [id, cardId, JSON.stringify(value), now]);
            if (!saved) fail('answer_conflict', 422);
          }
        } else {
          const saved = await one(tx, SQL.insertTaskAnswer, [id, cardId, JSON.stringify(value), now]);
          if (!saved) fail('answer_conflict', 422);
        }
        const updated = await one<TaskRecord>(tx, SQL.updateOwnedTaskState, [
          id, ownerId, resultState, card, revision, now,
        ]);
        if (!updated) fail('revision_conflict', 409);
        return { task: await aggregate(tx, updated), changed: true };
      });
    },

    async submitModeAnswer({ sessionId, taskId, expectedRevision, value }: {
      sessionId: unknown; taskId: unknown; expectedRevision: unknown; value: unknown;
    }) {
      const answer: JsonObject = typeof value === 'string'
        ? { mode: value }
        : plainObject(value, 'answer');
      if (typeof answer.mode !== 'string' || !['A', 'B', 'C', 'D', 'E'].includes(answer.mode)) {
        fail('invalid_answer', 422);
      }
      return this.submitCardAnswer({
        sessionId, taskId, cardId: 'mode', expectedRevision,
        nextState: 'collecting_terms', nextCard: 'terms', value: answer,
        allowRevision: true,
      });
    },

    async submitTermsAnswer({ sessionId, taskId, expectedRevision, value }: {
      sessionId: unknown; taskId: unknown; expectedRevision: unknown; value: unknown;
    }) {
      if (!Array.isArray(value) || !value.length || value.length > 30) fail('invalid_answer', 422);
      const terms = value.map((term) => {
        if (typeof term !== 'string' || !term.trim() || term.trim().length > 300) fail('invalid_answer', 422);
        return term.trim();
      });
      return this.submitCardAnswer({
        sessionId, taskId, cardId: 'terms', expectedRevision,
        nextState: 'collecting_years', nextCard: 'years', value: terms,
        allowRevision: true,
      });
    },

    async submitYearsAnswer({ sessionId, taskId, expectedRevision, value }: {
      sessionId: unknown; taskId: unknown; expectedRevision: unknown; value: unknown;
    }) {
      const answer: JsonObject = typeof value === 'string'
        ? { years: value }
        : plainObject(value, 'answer');
      const choice = answer.choice ?? answer.years;
      if (choice !== undefined && (
        typeof choice !== 'string' || !['A', 'B', 'C', 'D'].includes(choice)
      )) {
        fail('invalid_answer', 422);
      }
      if (choice === undefined && answer.from_year === undefined) fail('invalid_answer', 422);
      return this.submitCardAnswer({
        sessionId, taskId, cardId: 'years', expectedRevision,
        nextState: 'searching', nextCard: null, value: answer,
        allowRevision: true,
      });
    },

    async submitAdjustmentAnswer({ sessionId, taskId, expectedRevision, value }: {
      sessionId: unknown; taskId: unknown; expectedRevision: unknown; value: unknown;
    }) {
      let selected: unknown = value;
      if (value && typeof value === 'object' && !Array.isArray(value)) {
        selected = (value as JsonObject).adjustment;
      }
      if (typeof selected === 'string') selected = [selected];
      if (!Array.isArray(selected) || !selected.length) fail('invalid_answer', 422);
      const allowed = ['terms', 'years', 'mode', 'continue'] as const;
      type AdjustmentChoice = typeof allowed[number];
      const validated: AdjustmentChoice[] = [];
      for (const item of selected as unknown[]) {
        if (typeof item !== 'string' || !(allowed as readonly string[]).includes(item)) {
          fail('invalid_answer', 422);
        }
        const choice = item as AdjustmentChoice;
        if (!validated.includes(choice)) validated.push(choice);
      }
      const normalized: AdjustmentChoice[] = validated.includes('continue')
        ? ['continue']
        : (['mode', 'terms', 'years'] as const).filter((item) => validated.includes(item));
      const first = normalized[0];
      const transitions: Record<AdjustmentChoice, [TaskState, NextCard | null]> = {
        continue: ['adjusting', 'delivery'],
        mode: ['collecting_mode', 'mode'],
        terms: ['collecting_terms', 'terms'],
        years: ['collecting_years', 'years'],
      };
      const [resultState, resultCard] = transitions[first];
      return this.submitCardAnswer({
        sessionId, taskId, cardId: 'adjustment', expectedRevision,
        nextState: resultState, nextCard: resultCard, value: { adjustment: normalized },
        allowRevision: true,
      });
    },

    async submitDeliveryAnswer({ sessionId, taskId, expectedRevision, value }: {
      sessionId: unknown; taskId: unknown; expectedRevision: unknown; value: unknown;
    }) {
      const answer: JsonObject = typeof value === 'string'
        ? { form: value }
        : plainObject(value, 'answer');
      const form = answer.form ?? answer.delivery;
      if (typeof form !== 'string' || !['A', 'B', 'C'].includes(form)) fail('invalid_answer', 422);
      return this.submitCardAnswer({
        sessionId, taskId, cardId: 'delivery', expectedRevision,
        nextState: 'generating', nextCard: null, value: answer,
        allowRevision: true,
      });
    },

    async enqueueStage({ sessionId, taskId, jobId, stage, inputHash, message }: {
      sessionId: unknown; taskId: unknown; jobId: unknown; stage: unknown; inputHash: unknown; message: unknown;
    }) {
      const ownerId = validId(sessionId, 'session_id');
      const id = validId(taskId, 'task_id');
      const idForJob = validId(jobId, 'job_id');
      const stageId = stageName(stage);
      const hash = stageHash(inputHash);
      const text = stageMessage(message);
      return run(async (tx) => {
        const owned = await one<TaskRecord>(tx, SQL.getOwnedTask, [id, ownerId]);
        if (!owned) fail('task_not_found', 404);
        const existing = await one<StageJobRecord>(tx, SQL.getStageJobNatural, [id, stageId, hash]);
        if (existing) return { ...await stageDetails(tx, owned, existing), duplicate: true };
        const inserted = await one<StageJobRecord>(tx, SQL.insertStageJob, [
          idForJob, id, stageId, hash, Number(owned.revision),
        ]);
        if (!inserted) {
          const winner = await one<StageJobRecord>(tx, SQL.getStageJobNatural, [id, stageId, hash]);
          if (!winner) fail('task_store_unavailable', 503);
          return { ...await stageDetails(tx, owned, winner), duplicate: true };
        }
        await one<StageProgressRecord>(tx, SQL.upsertJobProgress, [
          id, inserted.id, text, null, null,
        ]);
        await one(tx, SQL.appendJobEvent, [
          id, inserted.id, 'queued', `${inserted.id}:queued:1`,
          JSON.stringify({ stage: stageId, input_hash: hash }),
        ]);
        return { ...await stageDetails(tx, owned, inserted), duplicate: false };
      });
    },

    async startStage({ sessionId, taskId, jobId, expectedJobRevision, leaseToken, message }: {
      sessionId: unknown; taskId: unknown; jobId: unknown; expectedJobRevision: unknown;
      leaseToken: unknown; message: unknown;
    }) {
      const ownerId = validId(sessionId, 'session_id');
      const id = validId(taskId, 'task_id');
      const idForJob = validId(jobId, 'job_id');
      const expected = positiveInteger(expectedJobRevision, 'expected_job_revision');
      const lease = stageLease(leaseToken);
      const text = stageMessage(message);
      return run(async (tx) => {
        const owned = await one<TaskRecord>(tx, SQL.getOwnedTask, [id, ownerId]);
        if (!owned) fail('task_not_found', 404);
        const job = await one<StageJobRecord>(tx, SQL.getStageJob, [idForJob, id]);
        if (!job) fail('job_not_found', 404);
        if (
          (job.status === 'started' || job.status === 'completed') &&
          Number(job.revision) === expected + 1
        ) {
          return { ...await stageDetails(tx, owned, job), duplicate: true };
        }
        const updated = await one<StageJobRecord>(tx, SQL.updateJobStarted, [
          idForJob, id, expected, lease,
        ]);
        if (!updated) fail('revision_conflict', 409);
        await one(tx, SQL.upsertJobProgress, [id, idForJob, text, null, null]);
        await one(tx, SQL.appendJobEvent, [
          id, idForJob, 'started', `${idForJob}:started:${updated.attempt}`,
          JSON.stringify({ stage: updated.stage, input_hash: updated.input_hash }),
        ]);
        return { ...await stageDetails(tx, owned, updated), duplicate: false };
      });
    },

    async completeStage({ sessionId, taskId, jobId, expectedJobRevision, leaseToken, state, nextCard, message, checkpoint }: {
      sessionId: unknown; taskId: unknown; jobId: unknown; expectedJobRevision: unknown;
      leaseToken: unknown; state: unknown; nextCard: unknown; message: unknown; checkpoint: unknown;
    }) {
      const ownerId = validId(sessionId, 'session_id');
      const id = validId(taskId, 'task_id');
      const idForJob = validId(jobId, 'job_id');
      const expected = positiveInteger(expectedJobRevision, 'expected_job_revision');
      const lease = stageLease(leaseToken);
      const resultState = validState(state);
      const card = validNextCard(nextCard);
      const text = stageMessage(message);
      const checkpointText = jsonValue(checkpoint, 'checkpoint', 1_000_000);
      return run(async (tx) => {
        const owned = await one<TaskRecord>(tx, SQL.getOwnedTask, [id, ownerId]);
        if (!owned) fail('task_not_found', 404);
        const job = await one<StageJobRecord>(tx, SQL.getStageJob, [idForJob, id]);
        if (!job) fail('job_not_found', 404);
        if (job.status === 'completed' && Number(job.revision) === expected + 1) {
          const details = await stageDetails(tx, owned, job);
          return { ...details, checkpoint: details.progress.checkpoint, duplicate: true };
        }
        if (
          job.status !== 'started' || Number(job.revision) !== expected ||
          job.lease_token !== lease || Number(owned.revision) !== Number(job.task_revision)
        ) {
          fail('revision_conflict', 409);
        }
        const updated = await one<StageJobRecord>(tx, SQL.updateJobCompleted, [
          idForJob, id, expected, lease, job.input_hash,
        ]);
        if (!updated) fail('revision_conflict', 409);
        const updatedTask = await one<TaskRecord>(tx, SQL.updateTaskAfterStage, [
          id, ownerId, resultState, card, Number(job.task_revision),
        ]);
        if (!updatedTask) fail('revision_conflict', 409);
        await one(tx, SQL.upsertJobProgress, [id, idForJob, text, checkpointText, null]);
        await one(tx, SQL.appendJobEvent, [
          id, idForJob, 'checkpoint', `${idForJob}:checkpoint:${job.attempt}`, checkpointText,
        ]);
        await one(tx, SQL.appendJobEvent, [
          id, idForJob, 'completed', `${idForJob}:completed:${job.attempt}`,
          JSON.stringify({ stage: job.stage, input_hash: job.input_hash, message: text }),
        ]);
        const details = await stageDetails(tx, updatedTask, updated);
        return { ...details, checkpoint: details.progress.checkpoint, duplicate: false };
      });
    },

    async failStage({ sessionId, taskId, jobId, expectedJobRevision, leaseToken, eventType, message, protectedTraceback, retryAfter = undefined }: {
      sessionId: unknown; taskId: unknown; jobId: unknown; expectedJobRevision: unknown;
      leaseToken: unknown; eventType: unknown; message: unknown; protectedTraceback: unknown;
      retryAfter?: unknown;
    }) {
      const ownerId = validId(sessionId, 'session_id');
      const id = validId(taskId, 'task_id');
      const idForJob = validId(jobId, 'job_id');
      const expected = positiveInteger(expectedJobRevision, 'expected_job_revision');
      const lease = leaseToken === null ? null : stageLease(leaseToken);
      if (typeof eventType !== 'string' || !['failed', 'rate_limited', 'enqueue_failed', 'recovery_manual_required'].includes(eventType)) {
        fail('invalid_event_type', 422);
      }
      const text = stageMessage(message);
      if (protectedTraceback !== null && typeof protectedTraceback !== 'string') fail('invalid_traceback', 422);
      const seconds = retryAfter === undefined || retryAfter === null
        ? null
        : positiveInteger(retryAfter, 'retry_after');
      const nextRetryAt = seconds === null
        ? null
        : new Date(new Date(isoTime(clock())).getTime() + seconds * 1000).toISOString();
      return run(async (tx) => {
        const owned = await one<TaskRecord>(tx, SQL.getOwnedTask, [id, ownerId]);
        if (!owned) fail('task_not_found', 404);
        const job = await one<StageJobRecord>(tx, SQL.getStageJob, [idForJob, id]);
        if (!job) fail('job_not_found', 404);
        if (job.status === 'failed' && Number(job.revision) === expected + 1) {
          return { ...await stageDetails(tx, owned, job), duplicate: true };
        }
        if (
          !['queued', 'started'].includes(job.status) || Number(job.revision) !== expected ||
          (job.status === 'started' && job.lease_token !== lease) ||
          Number(owned.revision) !== Number(job.task_revision)
        ) {
          fail('revision_conflict', 409);
        }
        const updated = await one<StageJobRecord>(tx, SQL.updateJobFailed, [
          idForJob, id, expected, lease, nextRetryAt,
        ]);
        if (!updated) fail('revision_conflict', 409);
        const updatedTask = await one<TaskRecord>(tx, SQL.updateTaskAfterStage, [
          id, ownerId, 'error', owned.next_card, Number(job.task_revision),
        ]);
        if (!updatedTask) fail('revision_conflict', 409);
        await one(tx, SQL.upsertJobProgress, [id, idForJob, text, null, protectedTraceback]);
        await one(tx, SQL.appendJobEvent, [
          id, idForJob, eventType, `${idForJob}:${eventType}:${job.attempt}`,
          JSON.stringify({ stage: job.stage, input_hash: job.input_hash, retry_after: seconds }),
        ]);
        return { ...await stageDetails(tx, updatedTask, updated), duplicate: false };
      });
    },

    async retryStage({ sessionId, taskId, jobId, expectedJobRevision, message, maxAttempts = 3 }: {
      sessionId: unknown; taskId: unknown; jobId: unknown; expectedJobRevision: unknown;
      message: unknown; maxAttempts?: unknown;
    }) {
      const ownerId = validId(sessionId, 'session_id');
      const id = validId(taskId, 'task_id');
      const idForJob = validId(jobId, 'job_id');
      const expected = positiveInteger(expectedJobRevision, 'expected_job_revision');
      const text = stageMessage(message);
      const attempts = positiveInteger(maxAttempts, 'max_attempts');
      return run(async (tx) => {
        const owned = await one<TaskRecord>(tx, SQL.getOwnedTask, [id, ownerId]);
        if (!owned) fail('task_not_found', 404);
        const job = await one<StageJobRecord>(tx, SQL.getStageJob, [idForJob, id]);
        if (!job) fail('job_not_found', 404);
        const current = await stageDetails(tx, owned, job);
        const limited = current.events.filter((event) => event.event_type === 'rate_limited').length;
        if (limited >= attempts) {
          await one(tx, SQL.appendJobEvent, [
            id, idForJob, 'retry_exhausted', `${idForJob}:retry_exhausted`,
            JSON.stringify({ stage: job.stage, attempts: limited }),
          ]);
          return { ...await stageDetails(tx, owned, job), exhausted: true };
        }
        if (job.status !== 'failed' || Number(job.revision) !== expected) fail('revision_conflict', 409);
        const updated = await one<StageJobRecord>(tx, SQL.retryStageJob, [
          idForJob, id, expected, Number(owned.revision) + 1,
        ]);
        if (!updated) fail('retry_not_due', 409);
        const resultState = job.stage === 'search' ? 'searching' : 'generating';
        const updatedTask = await one<TaskRecord>(tx, SQL.updateTaskAfterStage, [
          id, ownerId, resultState, null, Number(owned.revision),
        ]);
        if (!updatedTask) fail('revision_conflict', 409);
        await one(tx, SQL.upsertJobProgress, [
          id, idForJob, text, null, current.progress.protected_traceback,
        ]);
        const retryAt = job.next_retry_at ? new Date(isoTime(job.next_retry_at)).getTime() : 0;
        const delay = Math.max(0, Math.ceil((retryAt - new Date(isoTime(clock())).getTime()) / 1000));
        await one(tx, SQL.appendJobEvent, [
          id, idForJob, 'retry_scheduled', `${idForJob}:retry_scheduled:${updated.revision}`,
          JSON.stringify({ stage: job.stage, delay_seconds: delay, attempt: limited + 1 }),
        ]);
        return { ...await stageDetails(tx, updatedTask, updated), exhausted: false, delay_seconds: delay };
      });
    },

    async getLatestTermsEvent({ sessionId, taskId }: { sessionId: unknown; taskId: unknown }) {
      const ownerId = validId(sessionId, 'session_id');
      const id = validId(taskId, 'task_id');
      return run(async (tx) => {
        const owned = await one<TaskRecord>(tx, SQL.getOwnedTask, [id, ownerId]);
        if (!owned) fail('task_not_found', 404);
        const event = await one<StageEventRecord>(tx, SQL.getLatestTermsEvent, [id]);
        return event ? stageEventRow(event) : null;
      });
    },

    async appendTaskEvent({ sessionId, taskId, eventType, eventKey, payload }: {
      sessionId: unknown; taskId: unknown; eventType: unknown; eventKey: unknown; payload: unknown;
    }) {
      const ownerId = validId(sessionId, 'session_id');
      const id = validId(taskId, 'task_id');
      if (eventType !== 'terms_candidates' && eventType !== 'terms_candidates_unavailable') {
        fail('invalid_event_type', 422);
      }
      if (typeof eventKey !== 'string' || !eventKey || eventKey.length > 160) fail('invalid_event_key', 422);
      const body = jsonValue(payload, 'event_payload', 1_000_000);
      return run(async (tx) => {
        const owned = await one<TaskRecord>(tx, SQL.getOwnedTask, [id, ownerId]);
        if (!owned) fail('task_not_found', 404);
        const event = await one<StageEventRecord>(tx, SQL.appendTaskEvent, [id, eventType, eventKey, body]);
        return event ? stageEventRow(event) : null;
      });
    },

    async getStageJob({ sessionId, taskId, jobId }: {
      sessionId: unknown; taskId: unknown; jobId: unknown;
    }) {
      const ownerId = validId(sessionId, 'session_id');
      const id = validId(taskId, 'task_id');
      const idForJob = validId(jobId, 'job_id');
      return run(async (tx) => {
        const owned = await one<TaskRecord>(tx, SQL.getOwnedTask, [id, ownerId]);
        if (!owned) fail('task_not_found', 404);
        const job = await one<StageJobRecord>(tx, SQL.getStageJob, [idForJob, id]);
        if (!job) fail('job_not_found', 404);
        return stageDetails(tx, owned, job);
      });
    },

    async getTask({ sessionId, taskId }: { sessionId: unknown; taskId: unknown }) {
      const ownerId = validId(sessionId, 'session_id');
      const id = validId(taskId, 'task_id');
      return run(async (tx) => taskRow(await one<TaskRecord>(tx, SQL.getOwnedTask, [id, ownerId])));
    },

    async listTasks({ sessionId, limit = 50, offset = 0 }: {
      sessionId: unknown;
      limit?: unknown;
      offset?: unknown;
    }) {
      const ownerId = validId(sessionId, 'session_id');
      if (typeof limit !== 'number' || !Number.isSafeInteger(limit) || limit < 1 || limit > 100) fail('invalid_limit');
      if (typeof offset !== 'number' || !Number.isSafeInteger(offset) || offset < 0) fail('invalid_offset');
      return run(async (tx) => (
        await many<TaskRecord>(tx, SQL.listOwnedTasks, [ownerId, limit, offset])
      ).map(taskRow));
    },

    async updateTaskState({ sessionId, taskId, expectedRevision, state, nextCard }: {
      sessionId: unknown;
      taskId: unknown;
      expectedRevision: unknown;
      state: unknown;
      nextCard: unknown;
    }) {
      const ownerId = validId(sessionId, 'session_id');
      const id = validId(taskId, 'task_id');
      const revision = positiveInteger(expectedRevision, 'expected_revision');
      const nextState = validState(state);
      const card = validNextCard(nextCard);
      const now = isoTime(clock());
      return run(async (tx) => {
        const owned = await one<TaskRecord>(tx, SQL.getOwnedTask, [id, ownerId]);
        if (!owned) fail('task_not_found', 404);
        if (Number(owned.revision) !== revision) fail('revision_conflict', 409);
        const updated = await one<TaskRecord>(tx, SQL.updateOwnedTaskState, [
          id, ownerId, nextState, card, revision, now,
        ]);
        if (!updated) fail('revision_conflict', 409);
        return taskRow(updated);
      });
    },

    async listArtifacts({ sessionId, taskId }: { sessionId: unknown; taskId: unknown }) {
      const ownerId = validId(sessionId, 'session_id');
      const id = validId(taskId, 'task_id');
      return run(async (tx) => {
        if (!await one<TaskRecord>(tx, SQL.getOwnedTask, [id, ownerId])) fail('task_not_found', 404);
        return (await many<ArtifactRecord>(tx, SQL.listOwnedArtifacts, [id, ownerId])).map(artifactRow);
      });
    },

    async syncArtifacts({ sessionId, taskId, artifacts }: {
      sessionId: unknown;
      taskId: unknown;
      artifacts: unknown;
    }) {
      const ownerId = validId(sessionId, 'session_id');
      const id = validId(taskId, 'task_id');
      if (!Array.isArray(artifacts) || artifacts.length > 1000) fail('invalid_artifacts');
      const inputs = artifacts.map((item: unknown) => artifactInput(id, item));
      const names = new Set(inputs.map((item) => item.name));
      if (names.size !== inputs.length) fail('duplicate_artifact_name');
      const now = isoTime(clock());
      return run(async (tx) => {
        if (!await one<TaskRecord>(tx, SQL.getOwnedTask, [id, ownerId])) fail('task_not_found', 404);
        const saved: ArtifactDTO[] = [];
        for (const item of inputs) {
          const row = await one<ArtifactRecord>(tx, SQL.upsertOwnedArtifact, [
            id, ownerId, item.name, item.object_path, item.size_bytes,
            item.content_type, item.checksum_sha256, item.metadata, now,
          ]);
          if (!row) fail('task_not_found', 404);
          saved.push(artifactRow(row));
        }
        return saved;
      });
    },
  });
}

// Generated by the Qoder Sites Agent App integration at deployment time.
// Keeping this dynamic import out of tests makes the local Provider boundary explicit.
export async function createPlatformTaskStore(options = {}) {
  let module;
  try {
    module = await import('./_qoder/database.mjs');
  } catch {
    throw new TaskStoreError('platform_database_unavailable', 503);
  }
  if (!module.database) throw new TaskStoreError('platform_database_unavailable', 503);
  return createTaskStore({ ...options, database: module.database });
}

type TaskStore = ReturnType<typeof createTaskStore>;
type WorkerTokenProvider = () => string | undefined | Promise<string | undefined>;
type WorkerToken = string | WorkerTokenProvider;

function json(data: unknown, status = 200, extraHeaders: Record<string, string> = {}) {
  return new Response(JSON.stringify(data), { status, headers: { ...JSON_HEADERS, ...extraHeaders } });
}

async function digest(value: string): Promise<string> {
  const bytes = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(value));
  return Array.from(new Uint8Array(bytes), (byte) => byte.toString(16).padStart(2, '0')).join('');
}

async function workerAuthorized(request: Request, tokenProvider: WorkerTokenProvider): Promise<boolean> {
  const expected = String(await tokenProvider() || '');
  const supplied = request.headers.get('x-worker-token') || '';
  const [left, right] = await Promise.all([digest(expected), digest(supplied)]);
  let difference = left.length ^ right.length;
  const length = Math.max(left.length, right.length);
  for (let index = 0; index < length; index += 1) {
    difference |= (left.charCodeAt(index) || 0) ^ (right.charCodeAt(index) || 0);
  }
  return difference === 0 && expected.length > 0 && supplied.length > 0;
}

async function workerBody(request: Request): Promise<JsonObject> {
  const declared = Number(request.headers.get('content-length') || 0);
  if (declared > MAX_WORKER_BODY_BYTES) fail('request_too_large', 413);
  const bytes = new Uint8Array(await request.arrayBuffer());
  if (bytes.byteLength > MAX_WORKER_BODY_BYTES) fail('request_too_large', 413);
  try {
    return plainObject(JSON.parse(new TextDecoder().decode(bytes)), 'body');
  } catch (error) {
    if (error instanceof TaskStoreError) throw error;
    fail('invalid_json');
  }
}

function routePath(pathname: string): string {
  const marker = '/functions/v1/app';
  return pathname.startsWith(marker) ? pathname.slice(marker.length) : pathname;
}

function safeWorkerError(error: unknown): Response {
  const safe = error instanceof TaskStoreError
    ? error : new TaskStoreError('task_store_unavailable', 503);
  const body: { error: string; retry_after?: number } = { error: safe.code };
  if (safe.details && Number.isSafeInteger(safe.details.retry_after)) {
    body.retry_after = safe.details.retry_after;
  }
  const headers: Record<string, string> = body.retry_after ? { 'retry-after': String(body.retry_after) } : {};
  return json(body, safe.status, headers);
}

// Fixed worker surface for the Python client. There is deliberately no SQL,
// filter, list-all, arbitrary task query, or public write operation here.
export function createWorkerTaskStoreHandler({ store, workerToken }: {
  store: TaskStore;
  workerToken?: WorkerToken;
}) {
  if (!store) throw new TaskStoreError('task_store_required', 503);
  const tokenProvider: WorkerTokenProvider = workerToken === undefined
    ? () => globalThis.Deno?.env?.get?.('WORKER_SHARED_SECRET') || ''
    : (typeof workerToken === 'function' ? workerToken : () => workerToken);

  return async function handleWorkerTaskStore(request: Request): Promise<Response> {
    try {
      if (!await workerAuthorized(request, tokenProvider)) fail('worker_unauthorized', 403);
      const path = routePath(new URL(request.url).pathname);
      const taskMatch = path.match(/^\/internal\/task-store\/tasks\/([A-Za-z0-9-]{1,64})(\/state|\/artifacts|\/aggregate|\/answers\/(?:direction|mode|terms|years|adjustment|delivery))?$/);
      const skillMatch = path.match(/^\/internal\/task-store\/skill-versions\/([A-Za-z0-9-]{1,64})$/);
      const sessionMatch = path.match(/^\/internal\/task-store\/sessions\/([A-Za-z0-9-]{1,64})$/);
      const stageMatch = path.match(/^\/internal\/task-store\/tasks\/([A-Za-z0-9-]{1,64})\/stage\/(enqueue|start|complete|fail|retry)$/);
      const jobMatch = path.match(/^\/internal\/task-store\/tasks\/([A-Za-z0-9-]{1,64})\/jobs\/([A-Za-z0-9-]{1,64})$/);
      const termsEventMatch = path.match(/^\/internal\/task-store\/tasks\/([A-Za-z0-9-]{1,64})\/events\/terms$/);
      const taskEventMatch = path.match(/^\/internal\/task-store\/tasks\/([A-Za-z0-9-]{1,64})\/events$/);

      if (sessionMatch) {
        if (request.method !== 'GET') fail('method_not_allowed', 405);
        const ownerId = request.headers.get('x-session-id') || '';
        if (ownerId !== sessionMatch[1]) fail('session_not_found', 401);
        return json(await store.getSessionRecord({ sessionId: sessionMatch[1] }));
      }
      if (path === '/internal/task-store/skill-versions/published') {
        if (request.method !== 'GET') fail('method_not_allowed', 405);
        return json({ skill_version: await store.getPublishedSkillVersion() });
      }

      if (path === '/internal/task-store/sessions') {
        if (request.method !== 'POST') fail('method_not_allowed', 405);
        const body = await workerBody(request);
        const session = await store.createAnonymousSession({
          clientIp: body.client_ip || '',
          userAgent: body.user_agent || '',
          // Trusted worker callers may pin the session id so the Python
          // sync layer can assert one exact identity (WIRE-01). Anonymous
          // callers omit `id` and keep server-generated behavior.
          ...(body.id !== undefined ? { id: body.id } : {}),
        });
        return json(session, 201);
      }
      if (path === '/internal/task-store/tasks') {
        if (request.method === 'POST') {
          const body = await workerBody(request);
          const result = await store.createTask({
            sessionId: body.session_id,
            idempotencyKey: body.idempotency_key,
            skillVersionId: body.skill_version_id,
            quota: body.quota,
            state: body.state,
            nextCard: body.next_card,
            taskId: body.task_id,
          });
          return json(result, result.replayed ? 200 : 201);
        }
        if (request.method === 'GET') {
          const sessionId = request.headers.get('x-session-id') || '';
          const url = new URL(request.url);
          const tasks = await store.listTasks({
            sessionId,
            limit: Number(url.searchParams.get('limit') || 50),
            offset: Number(url.searchParams.get('offset') || 0),
          });
          return json({ tasks });
        }
        fail('method_not_allowed', 405);
      }

      if (skillMatch) {
        if (request.method === 'GET') {
          return json({ skill_version: await store.getSkillVersion({ skillVersionId: skillMatch[1] }) });
        }
        if (request.method !== 'PUT') fail('method_not_allowed', 405);
        const body = await workerBody(request);
        if (body.id !== skillMatch[1]) fail('skill_version_id_mismatch');
        const version = await store.upsertSkillVersion(body);
        return json({ skill_version: version });
      }
      if (termsEventMatch) {
        if (request.method !== 'GET') fail('method_not_allowed', 405);
        const sessionId = request.headers.get('x-session-id') || '';
        return json({ event: await store.getLatestTermsEvent({ sessionId, taskId: termsEventMatch[1] }) });
      }
      if (taskEventMatch) {
        if (request.method !== 'POST') fail('method_not_allowed', 405);
        const body = await workerBody(request);
        return json({ event: await store.appendTaskEvent({
          sessionId: body.session_id,
          taskId: taskEventMatch[1],
          eventType: body.event_type,
          eventKey: body.event_key,
          payload: body.payload,
        }) }, 201);
      }
      if (stageMatch) {
        if (request.method !== 'POST') fail('method_not_allowed', 405);
        const body = await workerBody(request);
        const input = {
          sessionId: body.session_id,
          taskId: stageMatch[1],
          jobId: body.job_id,
          message: body.message,
        };
        if (stageMatch[2] === 'enqueue') {
          return json(await store.enqueueStage({
            ...input, stage: body.stage, inputHash: body.input_hash,
          }));
        }
        if (stageMatch[2] === 'start') {
          return json(await store.startStage({
            ...input, expectedJobRevision: body.expected_job_revision, leaseToken: body.lease_token,
          }));
        }
        if (stageMatch[2] === 'retry') {
          return json(await store.retryStage({
            ...input,
            expectedJobRevision: body.expected_job_revision,
            maxAttempts: body.max_attempts,
          }));
        }
        if (stageMatch[2] === 'complete') {
          return json(await store.completeStage({
            ...input,
            expectedJobRevision: body.expected_job_revision,
            leaseToken: body.lease_token,
            state: body.state,
            nextCard: body.next_card,
            checkpoint: body.checkpoint,
          }));
        }
        return json(await store.failStage({
          ...input,
          expectedJobRevision: body.expected_job_revision,
          leaseToken: body.lease_token,
          eventType: body.event_type,
          protectedTraceback: body.protected_traceback,
          retryAfter: body.retry_after,
        }));
      }
      if (jobMatch) {
        if (request.method !== 'GET') fail('method_not_allowed', 405);
        const sessionId = request.headers.get('x-session-id') || '';
        return json(await store.getStageJob({
          sessionId, taskId: jobMatch[1], jobId: jobMatch[2],
        }));
      }
      if (!taskMatch) fail('not_found', 404);

      const taskId = taskMatch[1];
      const suffix = taskMatch[2] || '';
      if (suffix === '/aggregate') {
        if (request.method !== 'GET') fail('method_not_allowed', 405);
        const sessionId = request.headers.get('x-session-id') || '';
        const task = await store.getTaskAggregate({ sessionId, taskId });
        if (!task) fail('task_not_found', 404);
        return json({ task });
      }
      if (suffix.startsWith('/answers/')) {
        if (request.method !== 'POST') fail('method_not_allowed', 405);
        const body = await workerBody(request);
        const input = {
          sessionId: body.session_id,
          taskId,
          expectedRevision: body.expected_revision,
          value: body.value,
        };
        let result;
        if (suffix === '/answers/direction') result = await store.submitDirectionAnswer(input);
        else if (suffix === '/answers/mode') result = await store.submitModeAnswer(input);
        else if (suffix === '/answers/terms') result = await store.submitTermsAnswer(input);
        else if (suffix === '/answers/years') result = await store.submitYearsAnswer(input);
        else if (suffix === '/answers/adjustment') result = await store.submitAdjustmentAnswer(input);
        else if (suffix === '/answers/delivery') result = await store.submitDeliveryAnswer(input);
        else fail('not_found', 404);
        return json(result);
      }
      if (suffix === '') {
        if (request.method !== 'GET') fail('method_not_allowed', 405);
        const sessionId = request.headers.get('x-session-id') || '';
        const task = await store.getTask({ sessionId, taskId });
        if (!task) fail('task_not_found', 404);
        return json({ task });
      }
      if (suffix === '/state') {
        if (request.method !== 'PUT') fail('method_not_allowed', 405);
        const body = await workerBody(request);
        const task = await store.updateTaskState({
          sessionId: body.session_id,
          taskId,
          expectedRevision: body.expected_revision,
          state: body.state,
          nextCard: body.next_card,
        });
        return json({ task });
      }
      if (suffix === '/artifacts') {
        if (request.method === 'GET') {
          const sessionId = request.headers.get('x-session-id') || '';
          return json({ artifacts: await store.listArtifacts({ sessionId, taskId }) });
        }
        if (request.method === 'PUT') {
          const body = await workerBody(request);
          const artifacts = await store.syncArtifacts({
            sessionId: body.session_id, taskId, artifacts: body.artifacts,
          });
          return json({ artifacts });
        }
        fail('method_not_allowed', 405);
      }
      fail('not_found', 404);
    } catch (error) {
      return safeWorkerError(error);
    }
  };
}
