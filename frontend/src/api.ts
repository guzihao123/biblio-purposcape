import type { TaskCard, TaskAnswer } from './components/TaskWizard'

export interface TaskProgress {
  stage: string | null
  message: string
  checkpoint: Record<string, unknown> | null
}

export interface TaskView {
  id: string
  session_id?: string
  skill_version_id?: string
  state: string
  next_card: string | null
  card: TaskCard | null
  created_at?: string | null
  updated_at?: string | null
  progress?: TaskProgress | null
  job_id?: string | null
  direction?: string
}

export interface ArtifactLink {
  name: string
  url: string
  size: number
}

export interface DashboardPayload {
  data: { overview?: string } | null
  artifacts: ArtifactLink[]
}

export interface ReportPayload {
  mode?: string
  outline: string
  sample: string
  body: string
  references: string
  verification: {
    clean: boolean
    report: string
    conformance: string
  }
  artifacts: ArtifactLink[]
}

export interface SkillVersion {
  id: string
  version: number
  parent_id: string | null
  state: string
  content: Record<string, unknown>
  regression_report?: { passed: boolean } | null
}

export class ApiError extends Error {
  status: number

  constructor(status: number) {
    super(`API request failed with status ${status}`)
    this.status = status
  }
}

const API_BASE = import.meta.env.VITE_API_BASE_URL || '/api'
const endpoint = (path: string) => `${API_BASE}${path}`

export function artifactUrl(url: string) {
  return API_BASE === '/api' ? url : url.replace(/^\/api\//, `${API_BASE}/`)
}

async function request<T>(url: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(url, {
    ...init,
    credentials: 'include',
    headers: init.body
      ? { 'Content-Type': 'application/json', ...(init.headers ?? {}) }
      : init.headers,
  })
  if (!response.ok) throw new ApiError(response.status)
  return response.json() as Promise<T>
}

export function createTask(idempotencyKey: string) {
  return request<TaskView>(endpoint('/tasks'), {
    method: 'POST',
    headers: { 'Idempotency-Key': idempotencyKey },
    body: JSON.stringify({}),
  })
}

export function getTask(taskId: string) {
  return request<TaskView>(endpoint(`/tasks/${taskId}`))
}

export function listTasks() {
  return request<{ tasks: TaskView[] }>(endpoint('/tasks'))
}

export function answerTask(taskId: string, cardId: string, value: TaskAnswer) {
  return request<TaskView>(endpoint(`/tasks/${taskId}/answers/${cardId}`), {
    method: 'POST',
    body: JSON.stringify({ value }),
  })
}

export function getDashboard(taskId: string) {
  return request<DashboardPayload>(endpoint(`/tasks/${taskId}/dashboard`))
}

export function getReport(taskId: string) {
  return request<ReportPayload>(endpoint(`/tasks/${taskId}/report`))
}

function adminHeaders(token: string) {
  return { 'X-Admin-Token': token }
}

export function listSkillVersions(token: string) {
  return request<{ versions: SkillVersion[] }>(endpoint('/admin/skill/versions'), {
    headers: adminHeaders(token),
  })
}

export function createSkillDraft(token: string, parentId: string, content: Record<string, unknown>) {
  return request<SkillVersion>(endpoint('/admin/skill/drafts'), {
    method: 'POST',
    headers: adminHeaders(token),
    body: JSON.stringify({ parent_id: parentId, content }),
  })
}

export function regressSkillVersion(token: string, versionId: string) {
  return request<{ passed: boolean; errors?: string[] }>(endpoint(`/admin/skill/versions/${versionId}/regression`), {
    method: 'POST',
    headers: adminHeaders(token),
  })
}

export function publishSkillVersion(token: string, versionId: string) {
  return request<SkillVersion>(endpoint(`/admin/skill/versions/${versionId}/publish`), {
    method: 'POST',
    headers: adminHeaders(token),
  })
}

export function rollbackSkillVersion(token: string, versionId: string) {
  return request<SkillVersion>(endpoint(`/admin/skill/versions/${versionId}/rollback`), {
    method: 'POST',
    headers: adminHeaders(token),
  })
}
