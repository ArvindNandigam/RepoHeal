export type Repository = {
  name: string
  owner: string
  repo: string
  private: boolean
  description?: string | null
  language?: string | null
  default_branch?: string | null
  updated_at?: string | null
  health_score?: number | null
  issue_count: number
  critical_issue_count: number
  analysis_status: string
  analysis_progress: number
  last_analysis?: string | null
  last_commit_analyzed?: string | null
  current_head?: string | null
  trend: number[]
  status_url: string
}

export type Dashboard = {
  user: string
  timezone?: string
  repositories: Repository[]
  metrics: {
    active_repositories: number
    analyzed_repositories: number
    average_health_score?: number | null
    open_issues: number
    critical_issues: number
    active_analyses: number
  }
}

export type Graph = {
  repository: string
  nodes: Array<{ data: Record<string, unknown> }>
  edges: Array<{ data: Record<string, unknown> }>
  statistics?: Record<string, unknown>
  status?: string
  progress?: number
  message?: string
  neo4j_available?: boolean
  neo4j_warning?: string
}

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, { credentials: 'include', ...init })
  if (!response.ok) {
    const body = await response.text()
    throw new Error(body || `Request failed (${response.status})`)
  }
  return response.json() as Promise<T>
}

export const api = {
  dashboard: () => request<Dashboard>('/dashboard/data'),
  overview: (owner: string, repo: string) => request<Record<string, any>>(`/repos/${encodeURIComponent(owner)}/${encodeURIComponent(repo)}/overview`),
  repositoryStatus: (owner: string, repo: string) => request<Record<string, any>>(`/status/${encodeURIComponent(owner)}/${encodeURIComponent(repo)}`),
  graph: (owner: string, repo: string, analysisId?: string) =>
    request<Graph>(`/graph/${encodeURIComponent(owner)}/${encodeURIComponent(repo)}${analysisId ? `?analysis_id=${encodeURIComponent(analysisId)}` : ''}`),
  compare: (owner: string, repo: string, leftId?: string, rightId?: string) => {
    const params = new URLSearchParams()
    if (leftId) params.set('left_analysis_id', leftId)
    if (rightId) params.set('right_analysis_id', rightId)
    const qs = params.toString() ? `?${params.toString()}` : ''
    return request<Record<string, any>>(`/reports/${encodeURIComponent(owner)}/${encodeURIComponent(repo)}/compare${qs}`)
  },
  health: (owner: string, repo: string, analysisId?: string) =>
    request<Record<string, any>>(`/reports/${encodeURIComponent(owner)}/${encodeURIComponent(repo)}/health${analysisId ? `?analysis_id=${encodeURIComponent(analysisId)}` : ''}`),
  migration: (owner: string, repo: string, analysisId?: string) =>
    request<{ content: string }>(`/reports/${encodeURIComponent(owner)}/${encodeURIComponent(repo)}/migration${analysisId ? `?analysis_id=${encodeURIComponent(analysisId)}` : ''}`),
  history: (owner: string, repo: string, branch?: string) =>
    request<Record<string, any>>(`/reports/${encodeURIComponent(owner)}/${encodeURIComponent(repo)}/history${branch ? `?branch=${encodeURIComponent(branch)}` : ''}`),
  monitoring: (owner: string, repo: string) =>
    request<Record<string, any>>(`/monitor/dashboard/${encodeURIComponent(owner)}/${encodeURIComponent(repo)}`),
  adminMetrics: () => request<Record<string, any>>('/admin/metrics'),
  resetAdminMetrics: () => request<{ status: string; reset_at: string }>('/admin/metrics/reset', { method: 'POST' }),
  adminObservability: () => request<Record<string, any>>('/admin/observability'),
  branches: (owner: string, repo: string) => request<{ branches: string[] }>(`/repos/${encodeURIComponent(owner)}/${encodeURIComponent(repo)}/branches`),
  commits: (owner: string, repo: string, branch: string) => request<{ commits: Array<{ sha: string; message: string; date?: string }> }>(`/repos/${encodeURIComponent(owner)}/${encodeURIComponent(repo)}/commits?branch=${encodeURIComponent(branch)}`),
  startAnalysis: (owner: string, repo: string, branch?: string, commitSha?: string) => {
    const params = new URLSearchParams()
    params.set('mode', commitSha ? 'commit' : branch ? 'branch' : 'latest')
    if (branch) params.set('branch', branch)
    if (commitSha) params.set('commit_sha', commitSha)
    return request<Record<string, any>>(`/analyze/${encodeURIComponent(owner)}/${encodeURIComponent(repo)}?${params}`)
  },
  reanalyze: (owner: string, repo: string, branch?: string, commitSha?: string) => request<Record<string, any>>(
    `/reanalyze/${encodeURIComponent(owner)}/${encodeURIComponent(repo)}`,
    { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ mode: commitSha ? 'commit' : branch ? 'branch' : 'latest', branch: branch || null, commit_sha: commitSha || null }) }
  ),
  healthRefresh: (owner: string, repo: string, branch?: string, commitSha?: string) => request<Record<string, any>>(
    `/health-refresh/${encodeURIComponent(owner)}/${encodeURIComponent(repo)}`,
    { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ mode: commitSha ? 'commit' : branch ? 'branch' : 'latest', branch: branch || null, commit_sha: commitSha || null }) }
  ),
  diagnostics: () => request<Record<string, any>>('/healthz'),
}

export function subscribeToStatus(owner: string, repo: string, onMessage: (status: Record<string, any>) => void) {
  const source = new EventSource(`/sse/status/${encodeURIComponent(owner)}/${encodeURIComponent(repo)}`, { withCredentials: true })
  source.onmessage = (event) => {
    try { onMessage(JSON.parse(event.data)) } catch { /* malformed events are ignored by the stream */ }
  }
  return () => source.close()
}
