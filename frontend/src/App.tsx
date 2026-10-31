import { useEffect, useMemo, useState, useCallback, useRef } from 'react'
import { api, type Dashboard, type Graph, type Repository, subscribeToStatus } from './api'

type IconName =
  | 'activity'
  | 'alert'
  | 'arrow'
  | 'branch'
  | 'check'
  | 'chevron'
  | 'code'
  | 'compare'
  | 'dashboard'
  | 'download'
  | 'heart'
  | 'logout'
  | 'monitor'
  | 'refresh'
  | 'report'
  | 'search'
  | 'settings'
  | 'shield'
  | 'spark'
  | 'trend'
  | 'users'

const icons: Record<IconName, React.ReactNode> = {
  activity: <path d="M3 12h3l2.2-6 4 12 2.6-7H21" />,
  alert: (
    <>
      <path d="M10.3 3.2 2.6 17a2 2 0 0 0 1.8 3h15.2a2 2 0 0 0 1.8-3L13.7 3.2a2 2 0 0 0-3.4 0Z" />
      <path d="M12 9v4M12 17h.01" />
    </>
  ),
  arrow: <path d="M5 12h14M14 7l5 5-5 5" />,
  branch: (
    <>
      <circle cx="6" cy="5" r="2" />
      <circle cx="18" cy="6" r="2" />
      <circle cx="6" cy="19" r="2" />
      <path d="M6 7v10M8 7c5 0 4 7 8 7h2M18 8v6" />
    </>
  ),
  check: <path d="m5 12 4 4L19 6" />,
  chevron: <path d="m9 18 6-6-6-6" />,
  code: (
    <>
      <path d="m8 9-3 3 3 3M16 9l3 3-3 3M14 5l-4 14" />
    </>
  ),
  compare: (
    <>
      <path d="M8 7h11m0 0-3-3m3 3-3 3M16 17H5m0 0 3-3m-3 3 3 3" />
    </>
  ),
  dashboard: (
    <>
      <rect x="3" y="3" width="7" height="7" rx="2" />
      <rect x="14" y="3" width="7" height="7" rx="2" />
      <rect x="3" y="14" width="7" height="7" rx="2" />
      <rect x="14" y="14" width="7" height="7" rx="2" />
    </>
  ),
  download: (
    <>
      <path d="M12 3v12m-4-4 4 4 4-4M5 21h14" />
    </>
  ),
  heart: <path d="M20.8 4.6a5.5 5.5 0 0 0-7.8 0L12 5.7l-1.1-1.1a5.5 5.5 0 0 0-7.8 7.8L12 21l8.8-8.6a5.5 5.5 0 0 0 0-7.8Z" />,
  logout: (
    <>
      <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" />
      <polyline points="16 17 21 12 16 7" />
      <line x1="21" y1="12" x2="9" y2="12" />
    </>
  ),
  monitor: (
    <>
      <rect x="3" y="4" width="18" height="13" rx="2" />
      <path d="M8 21h8M12 17v4M7 11h2l1.5-3 3 6 1.5-3h2" />
    </>
  ),
  refresh: (
    <>
      <path d="M20 11a8 8 0 1 0-2.3 5.7L20 14" />
      <path d="M20 8v6h-6" />
    </>
  ),
  report: (
    <>
      <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8Z" />
      <path d="M14 2v6h6M8 13h2M8 17h8M14 13h2" />
    </>
  ),
  search: (
    <>
      <circle cx="11" cy="11" r="7" />
      <path d="m20 20-4-4" />
    </>
  ),
  settings: (
    <>
      <circle cx="12" cy="12" r="3" />
      <path d="M19 15a2 2 0 0 0 2-1v-4a2 2 0 0 0-2-1 2 2 0 0 1-1-3 2 2 0 0 0-3-2 2 2 0 0 1-3-1 2 2 0 0 0-4 0 2 2 0 0 1-3 1 2 2 0 0 0-3 2 2 2 0 0 1-1 3 2 2 0 0 0 0 4 2 2 0 0 1 1 3 2 2 0 0 0 3 2 2 0 0 1 3 1 2 2 0 0 0 4 2 2 0 0 1 3-1 2 2 0 0 0 3-2 2 2 0 0 1 1-3Z" />
    </>
  ),
  shield: (
    <>
      <path d="M12 22s8-3.5 8-10V5l-8-3-8 3v7c0 6.5 8 10 8 10Z" />
      <path d="m9 12 2 2 4-4" />
    </>
  ),
  spark: (
    <path d="m12 3 1.2 4.1L17 9l-3.8 1.9L12 15l-1.2-4.1L7 9l3.8-1.9L12 3ZM5 15l.7 2.3L8 18l-2.3.7L5 21l-.7-2.3L2 18l2.3-.7L5 15ZM19 13l.6 1.8 1.9.7-1.9.7L19 18l-.6-1.8-1.9-.7 1.9-.7L19 13Z" />
  ),
  trend: (
    <>
      <path d="m3 17 6-6 4 4 8-9" />
      <path d="M15 6h6v6" />
    </>
  ),
  users: (
    <>
      <path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2" />
      <circle cx="9" cy="7" r="4" />
      <path d="M22 21v-2a4 4 0 0 0-3-3.87" />
      <path d="M16 3.13a4 4 0 0 1 0 7.75" />
    </>
  ),
}

function Icon({ name, size = 18, className = '' }: { name: IconName; size?: number; className?: string }) {
  return (
    <svg className={className} width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      {icons[name]}
    </svg>
  )
}

function download(name: string, content: string, type: string) {
  const url = URL.createObjectURL(new Blob([content], { type }))
  const link = document.createElement('a')
  link.href = url
  link.download = name
  link.click()
  URL.revokeObjectURL(url)
}

function Sparkline({ points }: { points: number[] }) {
  const values = points.length > 1 ? points : [0, 0]
  const coordinates = values.map((point, index) => `${(index / (values.length - 1)) * 110},${34 - ((point - 50) / 50) * 28}`).join(' ')
  return (
    <svg className="sparkline" viewBox="0 0 110 38" preserveAspectRatio="none">
      <polyline points={coordinates} fill="none" stroke="#3f8d70" strokeWidth="2" vectorEffect="non-scaling-stroke" />
    </svg>
  )
}

function RepositoryRow({ repo, onOpen }: { repo: Repository; onOpen: () => void }) {
  const score = repo.health_score ?? 0
  const status =
    repo.analysis_status === 'completed' && repo.health_score !== null
      ? 'Healthy'
      : repo.analysis_status === 'not_analyzed'
      ? 'Not analyzed'
      : 'In progress'
  return (
    <div className="repo-row">
      <div className="repo-name-cell">
        <span className="repo-icon"><Icon name="code" size={17} /></span>
        <div>
          <button className="repo-name" onClick={onOpen}>{repo.name}</button>
          <span>{repo.language || 'Repository'} · {repo.default_branch || 'default'}</span>
        </div>
      </div>
      <div className="health-cell">
        <div className={`score-ring ${score < 80 ? 'warning' : ''}`} style={{ '--score': `${score * 3.6}deg` } as React.CSSProperties}>
          <span>{repo.health_score ?? '—'}</span>
        </div>
        <Sparkline points={repo.trend} />
      </div>
      <div className="analysis-cell">
        <strong>{repo.last_analysis ? new Date(repo.last_analysis).toLocaleString() : 'Not analyzed'}</strong>
        <span><Icon name="branch" size={12} />{repo.last_commit_analyzed?.slice(0, 7) || '—'}</span>
      </div>
      <div>
        <span className={`status-pill ${status === 'Healthy' ? 'healthy' : 'attention'}`}>
          <i />{status}
        </span>
      </div>
      <button className="row-action" aria-label={`Open ${repo.name}`} onClick={onOpen}>
        <Icon name="chevron" size={17} />
      </button>
    </div>
  )
}

function App() {
  const [page, setPage] = useState('Overview')
  const [dashboard, setDashboard] = useState<Dashboard | null>(null)
  const [selected, setSelected] = useState<Repository | null>(null)
  const [overview, setOverview] = useState<Record<string, any> | null>(null)
  const [graph, setGraph] = useState<Graph | null>(null)
  const [compare, setCompare] = useState<Record<string, any> | null>(null)
  const [history, setHistory] = useState<Record<string, any> | null>(null)
  const [healthReport, setHealthReport] = useState<Record<string, any> | null>(null)
  const [migrationDoc, setMigrationDoc] = useState<string | null>(null)
  const [monitoring, setMonitoring] = useState<Record<string, any> | null>(null)
  const [adminMetrics, setAdminMetrics] = useState<Record<string, any> | null>(null)
  const [adminObservability, setAdminObservability] = useState<Record<string, any> | null>(null)
  const [query, setQuery] = useState('')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [refreshing, setRefreshing] = useState(false)
  const [graphQuery, setGraphQuery] = useState('')
  const [graphType, setGraphType] = useState('all')
  const [graphViewMode, setGraphViewMode] = useState<'topology' | 'explorer'>('topology')
  const [inspectedNode, setInspectedNode] = useState<Record<string, any> | null>(null)
  const [status, setStatus] = useState<Record<string, any> | null>(null)
  const repositoryRequest = useRef(0)
  const [triaged, setTriaged] = useState<string[]>(() => JSON.parse(localStorage.getItem('repoheal-triage') || '[]'))

  // Routing helper that syncs with browser history
  const navigate = useCallback((targetPage: string, repo?: Repository | null, extra?: Record<string, string>) => {
    let resolvedPage = targetPage
    if (resolvedPage === 'Repositories') {
      resolvedPage = 'Overview'
    }
    if (resolvedPage === 'Admin' && dashboardRef.current?.user !== 'ArvindNandigam') {
      resolvedPage = 'Overview'
    }
    setPage(resolvedPage)
    const params = new URLSearchParams()
    if (resolvedPage === 'Overview') params.set('view', 'overview')
    else if (resolvedPage === 'Repository') params.set('view', 'repository')
    else if (resolvedPage === 'Reports') params.set('view', 'reports')
    else if (resolvedPage === 'Monitoring') params.set('view', 'monitoring')
    else if (resolvedPage === 'Admin') params.set('view', 'admin')
    else if (resolvedPage === 'Diagnostics') params.set('view', 'diagnostics')
    else if (resolvedPage === 'Compare') params.set('view', 'compare')

    const currentRepo = repo !== undefined ? repo : selected
    if (currentRepo) {
      params.set('owner', currentRepo.owner)
      params.set('repo', currentRepo.repo)
    }
    if (extra) {
      Object.entries(extra).forEach(([k, v]) => params.set(k, v))
    }
    const newUrl = `${window.location.pathname}?${params.toString()}`
    window.history.pushState({ page: resolvedPage, owner: currentRepo?.owner, repo: currentRepo?.repo }, '', newUrl)
  }, [selected])

  const loadDashboard = async () => {
    setLoading(true)
    setError('')
    try {
      const data = await api.dashboard()
      setDashboard(data)
      return data
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Unable to load dashboard')
      return null
    } finally {
      setLoading(false)
    }
  }

  const openRepository = async (repo: Repository, pushUrl = true, clearExisting = true) => {
    const requestId = ++repositoryRequest.current
    const isDifferentRepo = !selected || selected.owner !== repo.owner || selected.repo !== repo.repo
    setSelected(repo)
    setPage('Repository')
    if (clearExisting || isDifferentRepo) {
      setOverview(null)
      setGraph(null)
      setCompare(null)
      setHistory(null)
      setHealthReport(null)
      setMigrationDoc(null)
      setMonitoring(null)
      setStatus(null)
      setInspectedNode(null)
    }
    if (pushUrl) {
      const params = new URLSearchParams(window.location.search)
      params.set('view', 'repository')
      params.set('owner', repo.owner)
      params.set('repo', repo.repo)
      window.history.pushState({ page: 'Repository', owner: repo.owner, repo: repo.repo }, '', `${window.location.pathname}?${params.toString()}`)
    }
    try {
      const [nextOverview, nextGraph] = await Promise.all([
        api.overview(repo.owner, repo.repo),
        api.graph(repo.owner, repo.repo),
      ])
      if (requestId !== repositoryRequest.current) return
      setOverview(nextOverview)
      setGraph(nextGraph)
    } catch (reason) {
      if (requestId !== repositoryRequest.current) return
      setError(reason instanceof Error ? reason.message : 'Repository data is unavailable')
    }
  }

  const loadAdmin = async () => {
    if (dashboardRef.current?.user && dashboardRef.current.user !== 'ArvindNandigam') return
    setRefreshing(true)
    try {
      const [metrics, observability] = await Promise.all([api.adminMetrics(), api.adminObservability()])
      setAdminMetrics(metrics)
      setAdminObservability(observability)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Admin data is unavailable')
    } finally {
      setRefreshing(false)
    }
  }

  const loadReports = async (repoParam?: Repository | null, analysisId?: string) => {
    const repo = repoParam || selected || (dashboard?.repositories || [])[0]
    if (!repo) return
    setSelected(repo)
    setRefreshing(true)
    try {
      const [nextHistory, nextHealth, nextMigration] = await Promise.allSettled([
        api.history(repo.owner, repo.repo),
        api.health(repo.owner, repo.repo, analysisId),
        api.migration(repo.owner, repo.repo, analysisId),
      ])
      if (nextHistory.status === 'fulfilled') setHistory(nextHistory.value)
      if (nextHealth.status === 'fulfilled') {
        setHealthReport(nextHealth.value)
        setOverview((curr) => curr || { health: nextHealth.value })
      } else {
        setHealthReport(null)
      }
      if (nextMigration.status === 'fulfilled') {
        setMigrationDoc(nextMigration.value.content)
      } else {
        setMigrationDoc(null)
      }
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Reports are unavailable')
    } finally {
      setRefreshing(false)
    }
  }

  const loadMonitoring = async (repoParam?: Repository | null) => {
    const repo = repoParam || selected || (dashboard?.repositories || [])[0]
    if (!repo) return
    setSelected(repo)
    setRefreshing(true)
    try {
      setMonitoring(await api.monitoring(repo.owner, repo.repo))
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Monitoring data is unavailable')
    } finally {
      setRefreshing(false)
    }
  }

  const loadCompare = async (repoParam?: Repository | null, leftId?: string, rightId?: string) => {
    const repo = repoParam || selected || (dashboard?.repositories || [])[0]
    if (!repo) return
    setSelected(repo)
    setRefreshing(true)
    try {
      setCompare(await api.compare(repo.owner, repo.repo, leftId, rightId))
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Comparison is unavailable')
    } finally {
      setRefreshing(false)
    }
  }

  const dashboardRef = useRef<Dashboard | null>(null)
  dashboardRef.current = dashboard

  // Handle URL change on initial load & popstate (browser back/forward)
  const syncFromUrl = useCallback(
    (reposList: Repository[], currentUser?: string) => {
      const params = new URLSearchParams(window.location.search)
      const view = params.get('view') || 'overview'
      const owner = params.get('owner')
      const repoName = params.get('repo')
      const analysisId = params.get('analysis_id') || undefined

      let targetRepo: Repository | null = null
      if (owner && repoName) {
        targetRepo = reposList.find((r) => r.owner === owner && r.repo === repoName) || null
      }
      if (!targetRepo && reposList.length > 0 && ['repository', 'reports', 'monitoring', 'compare'].includes(view)) {
        targetRepo = reposList[0]
      }

      const activeUser = currentUser || dashboardRef.current?.user

      if (view === 'repositories') setPage('Overview')
      else if (view === 'repository') {
        setPage('Repository')
        if (targetRepo) void openRepository(targetRepo, false)
      } else if (view === 'reports') {
        setPage('Reports')
        if (targetRepo) void loadReports(targetRepo, analysisId)
      } else if (view === 'monitoring') {
        setPage('Monitoring')
        if (targetRepo) void loadMonitoring(targetRepo)
      } else if (view === 'admin') {
        if (activeUser === 'ArvindNandigam') {
          setPage('Admin')
          void loadAdmin()
        } else {
          setPage('Overview')
        }
      } else if (view === 'diagnostics') setPage('Diagnostics')
      else if (view === 'compare') {
        setPage('Compare')
        if (targetRepo) void loadCompare(targetRepo)
      } else {
        setPage('Overview')
      }
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    []
  )

  useEffect(() => {
    void loadDashboard().then((d) => {
      if (d) syncFromUrl(d.repositories, d.user)
    })
  }, [syncFromUrl])

  useEffect(() => {
    const handlePopState = () => {
      if (dashboardRef.current) syncFromUrl(dashboardRef.current.repositories, dashboardRef.current.user)
    }
    window.addEventListener('popstate', handlePopState)
    return () => window.removeEventListener('popstate', handlePopState)
  }, [syncFromUrl])

  useEffect(() => {
    if (!selected) return
    let hadActiveAnalysis = ['queued', 'running', 'analyzing', 'generating_graph', 'generating_reports', 'generating_migrations', 'updating_metadata'].includes(selected.analysis_status)

    return subscribeToStatus(selected.owner, selected.repo, (next) => {
      setStatus(next)
      const isActive = ['queued', 'running', 'analyzing', 'generating_graph', 'generating_reports', 'generating_migrations', 'updating_metadata'].includes(next.status)
      if (isActive) {
        hadActiveAnalysis = true
      } else if (next.status === 'completed' && hadActiveAnalysis) {
        hadActiveAnalysis = false
        void openRepository(selected, false, false)
      }
    })
  }, [selected?.owner, selected?.repo])

  const repos = useMemo(
    () =>
      (dashboard?.repositories || []).filter(
        (repo) =>
          repo.name.toLowerCase().includes(query.toLowerCase()) ||
          repo.repo.toLowerCase().includes(query.toLowerCase())
      ),
    [dashboard, query]
  )

  const visibleNodes = useMemo(() => {
    return (graph?.nodes || []).filter((node) => {
      const data = node.data
      const typeMatch = graphType === 'all' || String(data.type || '').toLowerCase() === graphType.toLowerCase()
      const queryMatch =
        !graphQuery ||
        String(data.label || data.path || data.id || '')
          .toLowerCase()
          .includes(graphQuery.toLowerCase())
      return typeMatch && queryMatch
    })
  }, [graph, graphQuery, graphType])

  const toggleTriage = (issue: string) => {
    const next = triaged.includes(issue) ? triaged.filter((item) => item !== issue) : [...triaged, issue]
    setTriaged(next)
    localStorage.setItem('repoheal-triage', JSON.stringify(next))
  }

  const startAnalysis = async () => {
    if (!selected) return
    setRefreshing(true)
    try {
      await api.startAnalysis(selected.owner, selected.repo)
      setStatus({ status: 'queued', progress: 0, message: 'Analysis queued' })
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Could not start analysis')
    } finally {
      setRefreshing(false)
    }
  }

  const rerunAnalysis = async () => {
    if (!selected) return
    setRefreshing(true)
    try {
      await api.reanalyze(selected.owner, selected.repo)
      setStatus({ status: 'queued', progress: 0, message: 'Full reanalysis queued' })
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Could not rerun analysis')
    } finally {
      setRefreshing(false)
    }
  }

  const title = page === 'Overview' ? `Good morning, ${dashboard?.user || 'there'}.` : page
  const metrics = dashboard?.metrics
  const issues = overview?.health?.issues?.items || overview?.health?.issues?.findings || []

  // Check graph status
  const isGraphUnstarted =
    selected &&
    (selected.analysis_status === 'not_analyzed' ||
      graph?.status === 'not_analyzed' ||
      (!selected.last_analysis && (!graph?.nodes || graph.nodes.length === 0)))
  const isGraphEmpty =
    graph?.status === 'empty' ||
    (graph && graph.nodes && graph.nodes.length === 0 && selected?.last_analysis)

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <a className="brand" href="#overview" onClick={(e) => { e.preventDefault(); navigate('Overview', null) }}>
          <span className="brand-mark"><Icon name="heart" size={19} /></span>
          <span>RepoHeal</span>
        </a>
        <nav className="main-nav" aria-label="Primary navigation">
          <p className="nav-label">Workspace</p>
          {[
            ['Repositories', 'dashboard'],
            ['Reports', 'report'],
            ['Monitoring', 'monitor'],
          ].map(([label, icon]) => (
            <button
              key={label}
              className={`nav-item ${page === label ? 'active' : ''}`}
              onClick={() => {
                if (label === 'Reports') void loadReports(selected)
                if (label === 'Monitoring') void loadMonitoring(selected)
                navigate(label)
              }}
            >
              <Icon name={icon as IconName} size={18} />
              <span>{label}</span>
            </button>
          ))}
          <p className="nav-label secondary">Manage</p>
          <button className={`nav-item ${page === 'Diagnostics' ? 'active' : ''}`} onClick={() => navigate('Diagnostics')}>
            <Icon name="settings" size={18} />
            <span>Diagnostics</span>
          </button>
          {dashboard?.user === 'ArvindNandigam' && (
            <button
              className={`nav-item ${page === 'Admin' ? 'active' : ''}`}
              onClick={() => {
                void loadAdmin()
                navigate('Admin')
              }}
            >
              <Icon name="shield" size={18} />
              <span>Admin</span>
            </button>
          )}
        </nav>
        <div className="sidebar-insight">
          <span className="insight-icon"><Icon name="spark" size={16} /></span>
          <strong>Local triage</strong>
          <p>Keep issue decisions in this browser without changing GitHub state.</p>
        </div>
        <div className="profile">
          <div className="avatar">{(dashboard?.user || '?').slice(0, 2).toUpperCase()}</div>
          <div className="profile-info">
            <strong>{dashboard?.user || 'Authenticated user'}</strong>
            <span>@{dashboard?.user || 'unknown'}</span>
          </div>
          <div className="profile-quick-actions">
            <a href="/auth/switch-account" className="profile-btn" title="Change GitHub account" aria-label="Change GitHub account">
              <Icon name="users" size={14} />
            </a>
            <a href="/auth/logout" className="profile-btn logout" title="Log out" aria-label="Log out">
              <Icon name="logout" size={14} />
            </a>
          </div>
        </div>
      </aside>

      <main className="main">
        <header className="topbar">
          <div className="mobile-brand">
            <span className="brand-mark"><Icon name="heart" size={17} /></span>
            <strong>RepoHeal</strong>
          </div>
          <div className="search-wrap">
            <Icon name="search" size={17} />
            <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search repositories..." aria-label="Search repositories" />
          </div>
          <div className="top-actions">
            <span className="sync-status"><span /> Authenticated workspace</span>
            <a className="button secondary-button top-action-btn" href="/auth/switch-account" title="Change GitHub account">
              <Icon name="users" size={13} />
              <span>Change account</span>
            </a>
            <a className="button secondary-button top-action-btn logout-btn" href="/auth/logout" title="Log out of RepoHeal">
              <Icon name="logout" size={13} />
              <span>Log out</span>
            </a>
          </div>
        </header>

        <div className="content">
          {error && (
            <div className="error-banner" role="alert">
              <span>{error}</span>
              <button onClick={() => setError('')}>Dismiss</button>
            </div>
          )}

          {loading ? (
            <div className="loading-state" aria-live="polite">Loading authenticated workspace…</div>
          ) : page === 'Repository' && selected ? (
            <section>
              <section className="page-heading">
                <div>
                  <p className="eyebrow">{selected.owner}/{selected.repo}</p>
                  <h1>{overview?.metadata?.name || selected.repo}</h1>
                  <p>{overview?.metadata?.description || selected.description || 'Repository overview and analysis history'}</p>
                </div>
                <div className="heading-actions">
                  <button className="button secondary-button" onClick={startAnalysis}>
                    <Icon name="refresh" className={refreshing ? 'spin' : ''} size={16} />
                    {refreshing ? 'Starting…' : 'Run analysis'}
                  </button>
                  <button
                    className="button primary-button"
                    onClick={() => {
                      void loadReports(selected)
                      navigate('Reports', selected)
                    }}
                  >
                    <Icon name="report" size={16} /> Reports
                  </button>
                </div>
              </section>

              {status && status.status !== 'completed' && (
                <div className="progress-card">
                  <strong>Analysis {status.status}</strong>
                  <span>{status.message}</span>
                  <progress value={status.progress || 0} max="100" />
                  <b>{status.progress || 0}%</b>
                </div>
              )}

              <div className="metrics-grid">
                <article className="metric-card featured">
                  <span className="metric-icon mint"><Icon name="heart" size={18} /></span>
                  <div className="metric-value-row">
                    <strong>{overview?.health?.score ?? '—'}</strong>
                    <span className="score-unit">/100</span>
                  </div>
                  <p>Health score</p>
                </article>
                <article className="metric-card">
                  <span className="metric-icon violet"><Icon name="code" size={18} /></span>
                  <div className="metric-value-row">
                    <strong>{overview?.graph?.files ?? '—'}</strong>
                  </div>
                  <p>Files analyzed</p>
                </article>
                <article className="metric-card">
                  <span className="metric-icon amber"><Icon name="alert" size={18} /></span>
                  <div className="metric-value-row">
                    <strong>{overview?.health?.risk_score ?? '—'}</strong>
                  </div>
                  <p>Migration risk</p>
                </article>
                <article className="metric-card">
                  <span className="metric-icon blue"><Icon name="branch" size={18} /></span>
                  <div className="metric-value-row">
                    <strong>{status?.code_state_status || overview?.status?.code_state_status || 'unknown'}</strong>
                  </div>
                  <p>Code state</p>
                </article>
              </div>

              {isGraphUnstarted ? (
                <div className="callout-card warning">
                  <div className="callout-content">
                    <h3>Run analysis first</h3>
                    <p>This repository has not completed an analysis yet. Run an analysis to build the dependency graph, map module relationships, and calculate health metrics.</p>
                  </div>
                  <button className="button primary-button" onClick={startAnalysis}>
                    <Icon name="refresh" size={16} /> Run analysis now
                  </button>
                </div>
              ) : null}

              <div className="dashboard-grid">
                <div className="panel graph-panel">
                  <div className="panel-header">
                    <div>
                      <h2>Dependency & Relationship Graph</h2>
                      <p>
                        {graph?.nodes?.length
                          ? `${visibleNodes.length} of ${graph.nodes.length} nodes · ${graph.edges?.length || 0} relationships`
                          : isGraphUnstarted
                          ? 'Run analysis first to view graph.'
                          : 'No graph data found.'}
                      </p>
                    </div>
                    <div className="graph-tools">
                      {graph?.neo4j_available !== undefined && (
                        <span className={`graph-badge-neo4j ${graph.neo4j_available ? 'connected' : 'unavailable'}`}>
                          Neo4j {graph.neo4j_available ? 'Live' : 'Unavailable'}
                        </span>
                      )}
                      <div className="graph-view-tabs">
                        <button
                          className={`graph-view-tab ${graphViewMode === 'topology' ? 'active' : ''}`}
                          onClick={() => setGraphViewMode('topology')}
                        >
                          Topology
                        </button>
                        <button
                          className={`graph-view-tab ${graphViewMode === 'explorer' ? 'active' : ''}`}
                          onClick={() => setGraphViewMode('explorer')}
                        >
                          Explorer
                        </button>
                      </div>
                      <input
                        value={graphQuery}
                        onChange={(event) => setGraphQuery(event.target.value)}
                        placeholder="Filter symbol or path..."
                        aria-label="Filter graph nodes"
                      />
                      <select value={graphType} onChange={(event) => setGraphType(event.target.value)} aria-label="Filter graph node type">
                        <option value="all">All types</option>
                        <option value="file">Files</option>
                        <option value="package">Packages</option>
                        <option value="function">Functions</option>
                        <option value="class">Classes</option>
                        <option value="api">APIs</option>
                      </select>
                    </div>
                  </div>

                  {isGraphUnstarted ? (
                    <div className="empty-state">
                      <strong>No analysis snapshot available</strong>
                      <p>Click "Run analysis now" above to build the dependency graph for {selected.repo}.</p>
                    </div>
                  ) : isGraphEmpty ? (
                    <div className="empty-state">
                      <strong>Empty graph</strong>
                      <p>Analysis completed, but no dependencies, files, or relationships were found.</p>
                    </div>
                  ) : graph?.nodes?.length ? (
                    graphViewMode === 'topology' ? (
                      <div className="graph-canvas-wrap">
                        <svg className="graph-svg" viewBox="0 0 680 380">
                          {/* Render visual graph topology */}
                          <defs>
                            <marker id="arrow" viewBox="0 0 10 10" refX="18" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
                              <path d="M 0 0 L 10 5 L 0 10 z" fill="#8da394" />
                            </marker>
                          </defs>
                          {/* Edges */}
                          {graph.edges &&
                            graph.edges.slice(0, 60).map((edge, i) => {
                              const total = Math.min(visibleNodes.length, 36)
                              const srcIdx = visibleNodes.findIndex((n) => String(n.data.id) === String(edge.data.source))
                              const tgtIdx = visibleNodes.findIndex((n) => String(n.data.id) === String(edge.data.target))
                              if (srcIdx < 0 || tgtIdx < 0) return null
                              const x1 = 340 + 220 * Math.cos((srcIdx / Math.max(total, 1)) * 2 * Math.PI)
                              const y1 = 190 + 130 * Math.sin((srcIdx / Math.max(total, 1)) * 2 * Math.PI)
                              const x2 = 340 + 220 * Math.cos((tgtIdx / Math.max(total, 1)) * 2 * Math.PI)
                              const y2 = 190 + 130 * Math.sin((tgtIdx / Math.max(total, 1)) * 2 * Math.PI)
                              return (
                                <line
                                  key={`edge-${i}`}
                                  x1={x1}
                                  y1={y1}
                                  x2={x2}
                                  y2={y2}
                                  stroke="#ccd5ce"
                                  strokeWidth="1.2"
                                  strokeDasharray={edge.data.relationship === 'IMPORTS' ? 'none' : '3,3'}
                                  markerEnd="url(#arrow)"
                                />
                              )
                            })}
                          {/* Nodes */}
                          {visibleNodes.slice(0, 36).map((node, index) => {
                            const total = Math.min(visibleNodes.length, 36)
                            const angle = (index / Math.max(total, 1)) * 2 * Math.PI
                            const cx = 340 + 220 * Math.cos(angle)
                            const cy = 190 + 130 * Math.sin(angle)
                            const type = String(node.data.type || '').toLowerCase()
                            const color =
                              type === 'file' ? '#3f8d70' : type === 'package' ? '#6860ba' : type === 'function' ? '#b5713c' : '#4a7d9e'
                            const isSelected = inspectedNode && inspectedNode.id === node.data.id
                            return (
                              <g
                                key={String(node.data.id || index)}
                                style={{ cursor: 'pointer' }}
                                onClick={() => setInspectedNode(node.data)}
                              >
                                <circle
                                  cx={cx}
                                  cy={cy}
                                  r={isSelected ? 11 : 8}
                                  fill={color}
                                  stroke={isSelected ? '#17231d' : '#fff'}
                                  strokeWidth={isSelected ? 3 : 1.5}
                                />
                                <text
                                  x={cx + (cx > 340 ? 12 : -12)}
                                  y={cy + 3}
                                  textAnchor={cx > 340 ? 'start' : 'end'}
                                  fill="#313932"
                                  fontSize="9"
                                  fontFamily="DM Mono, monospace"
                                  fontWeight={isSelected ? 'bold' : 'normal'}
                                >
                                  {String(node.data.label || node.data.path || node.data.id).slice(0, 20)}
                                </text>
                              </g>
                            )
                          })}
                        </svg>
                      </div>
                    ) : (
                      <div className="graph-list">
                        {visibleNodes.slice(0, 120).map((node) => {
                          const label = String(node.data.label || node.data.path || node.data.id)
                          const match = graphQuery ? label.toLowerCase().indexOf(graphQuery.toLowerCase()) : -1
                          return (
                            <span
                              key={String(node.data.id)}
                              className={`graph-node graph-${String(node.data.type || 'file').toLowerCase()}`}
                              style={{ cursor: 'pointer' }}
                              onClick={() => setInspectedNode(node.data)}
                            >
                              {match >= 0 ? (
                                <>
                                  {label.slice(0, match)}
                                  <mark>{label.slice(match, match + graphQuery.length)}</mark>
                                  {label.slice(match + graphQuery.length)}
                                </>
                              ) : (
                                label
                              )}
                            </span>
                          )
                        })}
                      </div>
                    )
                  ) : (
                    <div className="empty-state">No graph nodes match your filter.</div>
                  )}

                  {inspectedNode && (
                    <div className="graph-inspect-card">
                      <div>
                        <strong>{String(inspectedNode.label || inspectedNode.path || inspectedNode.id)}</strong>
                        <span> · Type: {String(inspectedNode.type || inspectedNode.kind || 'node')} · {inspectedNode.path || 'Root'}</span>
                      </div>
                      <button className="button tertiary-button" onClick={() => setInspectedNode(null)}>
                        Clear
                      </button>
                    </div>
                  )}

                  <div className="export-actions">
                    <button
                      onClick={() => graph && download(`${selected.repo}-graph.json`, JSON.stringify(graph, null, 2), 'application/json')}
                      disabled={!graph?.nodes?.length}
                    >
                      <Icon name="download" size={14} /> JSON
                    </button>
                    <button
                      onClick={() =>
                        graph &&
                        download(
                          `${selected.repo}-graph.md`,
                          `# ${selected.owner}/${selected.repo} graph\n\nNodes: ${graph.nodes.length}\nEdges: ${graph.edges.length}\n\n## Nodes\n${graph.nodes.map((n) => `- ${n.data.label || n.data.id} (${n.data.type})`).join('\n')}\n`,
                          'text/markdown'
                        )
                      }
                      disabled={!graph?.nodes?.length}
                    >
                      <Icon name="download" size={14} /> Markdown
                    </button>
                    <a href={`/visualize/${selected.owner}/${selected.repo}/export.png`} target="_blank" rel="noreferrer" className={!graph?.nodes?.length ? 'disabled' : ''}>
                      <Icon name="download" size={14} /> PNG
                    </a>
                  </div>
                </div>

                <aside className="side-stack">
                  <div className="panel">
                    <div className="panel-header compact">
                      <div>
                        <h2>Issue triage</h2>
                        <p>Local-only decisions</p>
                      </div>
                    </div>
                    {Array.isArray(issues) &&
                      issues.slice(0, 5).map((issue: any, index: number) => {
                        const key = String(issue.id || issue.symbol || issue.title || index)
                        return (
                          <label className="triage-item" key={key}>
                            <input type="checkbox" checked={triaged.includes(key)} onChange={() => toggleTriage(key)} />
                            <span>{issue.title || issue.symbol || issue.message || 'Finding'}</span>
                          </label>
                        )
                      })}
                    {(!Array.isArray(issues) || issues.length === 0) && (
                      <div className="empty-state">No historical issue list is available.</div>
                    )}
                  </div>

                  <div className="panel monitoring-card">
                    <div className="monitoring-heading">
                      <span className="live-icon"><Icon name="compare" size={17} /></span>
                      <div>
                        <h2>Comparison</h2>
                        <p>Compare saved analyses</p>
                      </div>
                    </div>
                    <button
                      className="text-button"
                      onClick={() => {
                        void loadCompare(selected)
                        navigate('Compare', selected)
                      }}
                    >
                      Open comparison <Icon name="arrow" size={14} />
                    </button>
                  </div>
                </aside>
              </div>
            </section>
          ) : page === 'Compare' ? (
            <section>
              <div className="page-heading">
                <div>
                  <p className="eyebrow">{selected?.owner}/{selected?.repo || 'Historical'}</p>
                  <h1>Analysis Comparison</h1>
                  <p>Review health score, commit differences, and dependency shifts across analysis runs.</p>
                </div>
                <div className="heading-actions">
                  <button className="button secondary-button" onClick={() => void loadCompare(selected)}>
                    <Icon name="refresh" className={refreshing ? 'spin' : ''} size={16} /> Refresh
                  </button>
                  <button className="button primary-button" onClick={() => selected && void openRepository(selected)}>
                    <Icon name="code" size={16} /> Repository
                  </button>
                </div>
              </div>
              <div className="panel detail-panel">
                {compare?.available ? (
                  <>
                    <div className="compare-grid">
                      <div>
                        <span>Before</span>
                        <strong>{compare.left.commit?.slice(0, 7) || '—'}</strong>
                        <small>{compare.left.health_score ?? '—'} health</small>
                      </div>
                      <div>
                        <span>After</span>
                        <strong>{compare.right.commit?.slice(0, 7) || '—'}</strong>
                        <small>{compare.right.health_score ?? '—'} health</small>
                      </div>
                    </div>
                    {compare.changes.map((change: any) => (
                      <div className="change-row" key={change.metric}>
                        <span>{change.metric}</span>
                        <b>{String(change.before ?? '—')}</b>
                        <Icon name="arrow" size={14} />
                        <b>{String(change.after ?? '—')}</b>
                        <em>
                          {change.delta == null
                            ? 'changed'
                            : `${change.delta > 0 ? '+' : ''}${change.delta}`}
                        </em>
                      </div>
                    ))}
                  </>
                ) : (
                  <div className="empty-state">
                    <strong>{compare?.message || 'Comparison unavailable.'}</strong>
                    <p>At least two completed analysis snapshots are required to compute comparative differences.</p>
                  </div>
                )}
              </div>
            </section>
          ) : page === 'Reports' ? (
            <ReportsPage
              selectedRepo={selected}
              history={history}
              healthReport={healthReport}
              migrationDoc={migrationDoc}
              refreshing={refreshing}
              onRefresh={() => void loadReports(selected)}
              onRetry={() => void rerunAnalysis()}
              onOpenRepository={() => selected && void openRepository(selected)}
              onSelectAnalysis={(aid) => void loadReports(selected, aid)}
            />
          ) : page === 'Monitoring' ? (
            <MonitoringPage data={monitoring} refreshing={refreshing} onRefresh={() => void loadMonitoring(selected)} />
          ) : page === 'Admin' && dashboard?.user === 'ArvindNandigam' ? (
            <AdminPage metrics={adminMetrics} observability={adminObservability} refreshing={refreshing} onRefresh={loadAdmin} />
          ) : page === 'Diagnostics' ? (
            <Diagnostics />
          ) : (
            <section>
              <div className="page-heading">
                <div>
                  <p className="eyebrow">Authenticated workspace</p>
                  <h1>{title}</h1>
                  <p>
                    Repositories connected to your GitHub workspace. Health and analysis status are based on the latest saved repository data.
                  </p>
                </div>
                <div className="heading-actions">
                  <button
                    className="button secondary-button"
                    onClick={() => {
                      setRefreshing(true)
                      void loadDashboard().finally(() => setRefreshing(false))
                    }}
                  >
                    <Icon name="refresh" className={refreshing ? 'spin' : ''} size={16} /> Refresh
                  </button>
                </div>
              </div>

              <section className="metrics-grid">
                <article className="metric-card featured">
                  <span className="metric-icon mint"><Icon name="heart" size={18} /></span>
                  <div className="metric-value-row">
                    <strong>{metrics?.average_health_score ?? '—'}</strong>
                    <span className="score-unit">/100</span>
                  </div>
                  <p>Average health score</p>
                </article>
                <article className="metric-card">
                  <span className="metric-icon violet"><Icon name="code" size={18} /></span>
                  <div className="metric-value-row">
                    <strong>{metrics?.active_repositories ?? 0}</strong>
                  </div>
                  <p>Active repositories</p>
                </article>
                <article className="metric-card">
                  <span className="metric-icon amber"><Icon name="alert" size={18} /></span>
                  <div className="metric-value-row">
                    <strong>{metrics?.open_issues ?? 0}</strong>
                  </div>
                  <p>Open issues · {metrics?.critical_issues ?? 0} critical</p>
                </article>
                <article className="metric-card">
                  <span className="metric-icon blue"><Icon name="activity" size={18} /></span>
                  <div className="metric-value-row">
                    <strong>{metrics?.active_analyses ?? 0}</strong>
                  </div>
                  <p>Analyses in progress</p>
                </article>
              </section>

              <div className="panel repositories-panel">
                <div className="panel-header">
                  <div>
                    <h2>Repositories</h2>
                    <p>Live metadata and analysis state</p>
                  </div>
                </div>
                <div className="repo-table">
                  <div className="table-head">
                    <span>Repository</span>
                    <span>Health score</span>
                    <span>Last analysis</span>
                    <span>Status</span>
                    <span />
                  </div>
                  {repos.map((repo) => (
                    <RepositoryRow key={repo.name} repo={repo} onOpen={() => void openRepository(repo)} />
                  ))}
                  {repos.length === 0 && (
                    <div className="empty-state">
                      {dashboard?.repositories.length
                        ? 'No repositories match your search.'
                        : 'No installed repositories are available.'}
                    </div>
                  )}
                </div>
              </div>
            </section>
          )}
        </div>
      </main>
    </div>
  )
}

function ReportsPage({
  selectedRepo,
  history,
  healthReport,
  migrationDoc,
  refreshing,
  onRefresh,
  onRetry,
  onOpenRepository,
  onSelectAnalysis,
}: {
  selectedRepo: Repository | null
  history: Record<string, any> | null
  healthReport: Record<string, any> | null
  migrationDoc: string | null
  refreshing: boolean
  onRefresh: () => void
  onRetry: () => void
  onOpenRepository: () => void
  onSelectAnalysis: (analysisId: string) => void
}) {
  const [activeTab, setActiveTab] = useState<'health' | 'migration' | 'history'>('health')
  const timeline = Array.isArray(history?.timeline) ? history.timeline : []
  const score = healthReport?.overall_health_score ?? healthReport?.health_score
  const risk = healthReport?.overall_risk_score ?? healthReport?.risk_score

  const actions = Array.isArray(healthReport?.recommended_actions) ? healthReport.recommended_actions : []
  const deprecatedApis = Array.isArray(healthReport?.deprecated_apis) ? healthReport.deprecated_apis : []
  const warnings = Array.isArray(healthReport?.intelligence_warnings) ? healthReport.intelligence_warnings : []

  // Check state: "no report", "generation failed", "report available"
  const hasHistory = timeline.length > 0
  const isReportAvailable = Boolean(healthReport && (healthReport.overall_health_score !== undefined || healthReport.generated_at))
  const isFailed = healthReport?.migration_intelligence_status === 'failed' || (!isReportAvailable && hasHistory && selectedRepo?.analysis_status === 'completed')

  return (
    <section>
      <div className="page-heading">
        <div>
          <p className="eyebrow">{selectedRepo ? `${selectedRepo.owner}/${selectedRepo.repo}` : 'Reports'}</p>
          <h1>Health & Migration Reports</h1>
          <p>Verified health indicators, migration documents, and historical evolution.</p>
        </div>
        <div className="heading-actions">
          <button className="button secondary-button" onClick={onRefresh}>
            <Icon name="refresh" className={refreshing ? 'spin' : ''} size={16} /> Refresh
          </button>
          <button className="button primary-button" onClick={onOpenRepository}>
            <Icon name="code" size={16} /> Open repository
          </button>
        </div>
      </div>

      <section className="metrics-grid">
        <article className="metric-card featured">
          <span className="metric-icon mint"><Icon name="heart" size={18} /></span>
          <div className="metric-value-row">
            <strong>{score ?? '—'}</strong>
            <span className="score-unit">/100</span>
          </div>
          <p>Health score</p>
        </article>
        <article className="metric-card">
          <span className="metric-icon amber"><Icon name="shield" size={18} /></span>
          <div className="metric-value-row">
            <strong>{risk ?? '—'}</strong>
          </div>
          <p>Overall migration risk</p>
        </article>
        <article className="metric-card">
          <span className="metric-icon violet"><Icon name="report" size={18} /></span>
          <div className="metric-value-row">
            <strong>{timeline.length}</strong>
          </div>
          <p>Saved analyses</p>
        </article>
        <article className="metric-card">
          <span className="metric-icon blue"><Icon name="branch" size={18} /></span>
          <div className="metric-value-row">
            <strong>{history?.current_head?.slice(0, 7) || '—'}</strong>
          </div>
          <p>Current head</p>
        </article>
      </section>

      {/* Report state banner */}
      {!hasHistory && !isReportAvailable ? (
        <div className="callout-card warning">
          <div className="callout-content">
            <h3>No report available</h3>
            <p>This repository has not generated a health report yet. Run an analysis from the repository page to calculate health scores and generate migration docs.</p>
          </div>
          <button className="button primary-button" onClick={onOpenRepository}>
            Go to repository
          </button>
        </div>
      ) : isFailed ? (
        <div className="callout-card warning">
          <div className="callout-content">
            <h3>Report generation incomplete or failed</h3>
            <p>The analysis finished but the migration intelligence pipeline reported an issue. Review warnings or rerun the analysis.</p>
          </div>
          <button className="button secondary-button" onClick={onRetry}>
            Rerun analysis
          </button>
        </div>
      ) : null}

      {/* Tabs */}
      <div className="report-tabs">
        <button className={`report-tab ${activeTab === 'health' ? 'active' : ''}`} onClick={() => setActiveTab('health')}>
          <Icon name="heart" size={15} /> Health Findings
        </button>
        <button className={`report-tab ${activeTab === 'migration' ? 'active' : ''}`} onClick={() => setActiveTab('migration')}>
          <Icon name="code" size={15} /> Migration Document
        </button>
        <button className={`report-tab ${activeTab === 'history' ? 'active' : ''}`} onClick={() => setActiveTab('history')}>
          <Icon name="trend" size={15} /> Analysis History ({timeline.length})
        </button>
        {isReportAvailable && selectedRepo && (
          <div style={{ marginLeft: 'auto', display: 'flex', gap: '8px' }}>
            <button
              className="button tertiary-button"
              onClick={() => download(`${selectedRepo.repo}-report.json`, JSON.stringify(healthReport, null, 2), 'application/json')}
            >
              <Icon name="download" size={13} /> JSON
            </button>
            <a
              href={`/reports/${selectedRepo.owner}/${selectedRepo.repo}/export?format=markdown`}
              className="button tertiary-button"
              target="_blank"
              rel="noreferrer"
            >
              <Icon name="download" size={13} /> Markdown
            </a>
          </div>
        )}
      </div>

      {activeTab === 'health' ? (
        <div className="dashboard-grid">
          <div className="panel detail-panel">
            <div className="panel-header" style={{ padding: 0, marginBottom: '16px', minHeight: 'auto', border: 0 }}>
              <div>
                <h2>Recommended Actions & Deprecated APIs</h2>
                <p>Derived from AST inspections and library version compatibility</p>
              </div>
            </div>

            {warnings.length > 0 && (
              <div className="callout-card warning" style={{ padding: '12px 16px', marginBottom: '16px' }}>
                <div className="callout-content">
                  <h3>Intelligence Warnings</h3>
                  {warnings.map((w: string, i: number) => <p key={i}>{w}</p>)}
                </div>
              </div>
            )}

            {actions.length > 0 ? (
              actions.map((action: any, i: number) => (
                <div className="finding-card" key={i}>
                  <div className="finding-card-header">
                    <span className="finding-tag">{action.symbol || action.library || 'Finding'}</span>
                    <span className={`finding-priority ${(action.priority || 'medium').toLowerCase()}`}>
                      {action.priority || 'Action'}
                    </span>
                  </div>
                  <p style={{ margin: '4px 0', fontSize: '11px', color: '#444c45' }}>
                    {action.description || action.recommendation || action.message || 'Review and plan upgrade.'}
                  </p>
                  {action.target && (
                    <small style={{ color: '#3f8d70', font: "600 10px 'DM Mono', monospace" }}>
                      Replace with: {action.target}
                    </small>
                  )}
                </div>
              ))
            ) : deprecatedApis.length > 0 ? (
              deprecatedApis.map((dep: any, i: number) => (
                <div className="finding-card" key={i}>
                  <div className="finding-card-header">
                    <span className="finding-tag">{dep.symbol || 'Deprecated API'}</span>
                    <span className="finding-priority high">Deprecated</span>
                  </div>
                  <p style={{ margin: '4px 0', fontSize: '11px', color: '#444c45' }}>
                    Found in {dep.files?.length || 1} file(s). Recommended replacement: {dep.replacement || 'Check documentation'}.
                  </p>
                </div>
              ))
            ) : (
              <div className="empty-state">
                {isReportAvailable ? 'No breaking changes or deprecated APIs found. Repository is clean.' : 'No report data loaded.'}
              </div>
            )}
          </div>

          <aside className="side-stack">
            <div className="panel monitoring-card">
              <div className="monitoring-heading">
                <span className="live-icon"><Icon name="spark" size={17} /></span>
                <div>
                  <h2>Analysis Snapshot</h2>
                  <p>Generated details</p>
                </div>
              </div>
              <div className="monitoring-stats">
                <div>
                  <span>Generated at</span>
                  <strong>{healthReport?.generated_at ? new Date(healthReport.generated_at).toLocaleString() : '—'}</strong>
                </div>
                <div>
                  <span>Commit</span>
                  <strong>{healthReport?.commit_sha?.slice(0, 7) || '—'}</strong>
                </div>
              </div>
              <div style={{ marginTop: '14px', fontSize: '10px', color: '#7a8279' }}>
                <p style={{ margin: '4px 0' }}>Branch: <b>{healthReport?.branch || 'default'}</b></p>
                <p style={{ margin: '4px 0' }}>Analysis ID: <code style={{ font: '10px DM Mono' }}>{healthReport?.analysis_id || 'latest'}</code></p>
              </div>
            </div>
          </aside>
        </div>
      ) : activeTab === 'migration' ? (
        <div className="panel detail-panel">
          <div className="panel-header" style={{ padding: 0, marginBottom: '16px', minHeight: 'auto', border: 0 }}>
            <div>
              <h2>Migration Document</h2>
              <p>Generated step-by-step upgrade plan and compatibility shims</p>
            </div>
            {migrationDoc && (
              <button
                className="button secondary-button"
                onClick={() => selectedRepo && download(`${selectedRepo.repo}-migration.md`, migrationDoc, 'text/markdown')}
              >
                <Icon name="download" size={14} /> Download Markdown
              </button>
            )}
          </div>
          {migrationDoc ? (
            <pre className="doc-viewer">{migrationDoc}</pre>
          ) : (
            <div className="empty-state">
              No migration document generated for this analysis.
            </div>
          )}
        </div>
      ) : (
        <div className="panel repositories-panel">
          <div className="panel-header">
            <div>
              <h2>Historical Analyses</h2>
              <p>{history?.repository || 'Select a repository to inspect past analyses'}</p>
            </div>
          </div>
          <div className="repo-table">
            <div className="table-head">
              <span>Analysis</span>
              <span>Branch</span>
              <span>Commit</span>
              <span>Health</span>
              <span />
            </div>
            {timeline.map((item: any) => (
              <div className="repo-row" key={item.analysis_id || item.timestamp}>
                <div className="repo-name-cell">
                  <span className="repo-icon"><Icon name="report" size={17} /></span>
                  <div>
                    <strong className="repo-name">{item.analysis_id || 'Analysis'}</strong>
                    <span>{item.timestamp ? new Date(item.timestamp).toLocaleString() : 'Unknown date'}</span>
                  </div>
                </div>
                <div className="analysis-cell">
                  <strong>{item.branch || '—'}</strong>
                </div>
                <div className="analysis-cell">
                  <span>{item.commit?.slice(0, 7) || '—'}</span>
                </div>
                <div>
                  <span className="status-pill healthy"><i />{item.health_score ?? '—'}</span>
                </div>
                <button
                  className="row-action"
                  title="View this report"
                  onClick={() => {
                    onSelectAnalysis(item.analysis_id)
                    setActiveTab('health')
                  }}
                >
                  <Icon name="chevron" size={17} />
                </button>
              </div>
            ))}
            {timeline.length === 0 && (
              <div className="empty-state">No saved analyses or health reports are available.</div>
            )}
          </div>
        </div>
      )}
    </section>
  )
}

function MonitoringPage({ data, refreshing, onRefresh }: { data: Record<string, any> | null; refreshing: boolean; onRefresh: () => void }) {
  const alerts = Array.isArray(data?.active_alerts) ? data.active_alerts : []
  const watchlist = Array.isArray(data?.watchlist) ? data.watchlist : []
  const hist = Array.isArray(data?.health_history) ? data.health_history : []
  return (
    <section>
      <div className="page-heading">
        <div>
          <p className="eyebrow">Live MongoDB monitoring data</p>
          <h1>Monitoring</h1>
          <p>Alerts, dependency watchlist, health snapshots, and schedule settings.</p>
        </div>
        <div className="heading-actions">
          <button className="button secondary-button" onClick={onRefresh}>
            <Icon name="refresh" className={refreshing ? 'spin' : ''} size={16} /> Refresh
          </button>
        </div>
      </div>
      <section className="metrics-grid">
        <article className="metric-card featured">
          <span className="metric-icon mint"><Icon name="activity" size={18} /></span>
          <div className="metric-value-row"><strong>{alerts.length}</strong></div>
          <p>Active alerts</p>
        </article>
        <article className="metric-card">
          <span className="metric-icon amber"><Icon name="alert" size={18} /></span>
          <div className="metric-value-row"><strong>{watchlist.length}</strong></div>
          <p>Watched dependencies</p>
        </article>
        <article className="metric-card">
          <span className="metric-icon violet"><Icon name="trend" size={18} /></span>
          <div className="metric-value-row"><strong>{hist.length}</strong></div>
          <p>Health snapshots</p>
        </article>
        <article className="metric-card">
          <span className="metric-icon blue"><Icon name="monitor" size={18} /></span>
          <div className="metric-value-row"><strong>{data?.schedule?.frequency || '—'}</strong></div>
          <p>Monitoring schedule</p>
        </article>
      </section>
      <div className="dashboard-grid">
        <div className="panel repositories-panel">
          <div className="panel-header">
            <div>
              <h2>Active alerts</h2>
              <p>Only persisted, undismissed alerts are shown.</p>
            </div>
          </div>
          {alerts.length ? (
            alerts.slice(0, 10).map((alert: any) => (
              <div className="risk-item" key={alert.id || alert.created_at}>
                <span className="risk-severity critical"><Icon name="alert" size={15} /></span>
                <div>
                  <strong>{alert.title || alert.category || 'Alert'}</strong>
                  <p>{alert.message || alert.description || 'No description available.'}</p>
                  <span>{alert.severity || 'unknown'} · {alert.created_at ? new Date(alert.created_at).toLocaleString() : 'Unknown time'}</span>
                </div>
              </div>
            ))
          ) : (
            <div className="empty-state">No active alerts are recorded.</div>
          )}
        </div>
        <aside className="side-stack">
          <div className="panel">
            <div className="panel-header compact">
              <div>
                <h2>Dependency watchlist</h2>
                <p>Persisted packages under observation</p>
              </div>
            </div>
            {watchlist.length ? (
              watchlist.slice(0, 8).map((item: any) => (
                <div className="risk-item" key={item.package_name}>
                  <span className="risk-severity moderate"><Icon name="code" size={15} /></span>
                  <div>
                    <strong>{item.package_name || 'Dependency'}</strong>
                    <p>{item.current_version || 'Current version unknown'}</p>
                    <span>{item.risk_level || 'unclassified'}</span>
                  </div>
                </div>
              ))
            ) : (
              <div className="empty-state">No dependencies are being watched.</div>
            )}
          </div>
          <div className="panel monitoring-card">
            <div className="monitoring-heading">
              <span className="live-icon"><Icon name="monitor" size={17} /></span>
              <div>
                <h2>Schedule</h2>
                <p>Configured monitoring cadence</p>
              </div>
            </div>
            <div className="monitoring-stats">
              <div>
                <span>Frequency</span>
                <strong>{data?.schedule?.frequency || '—'}</strong>
              </div>
              <div>
                <span>Next run</span>
                <strong>{data?.schedule?.next_run ? new Date(data.schedule.next_run).toLocaleString() : 'Not scheduled'}</strong>
              </div>
            </div>
          </div>
        </aside>
      </div>
    </section>
  )
}

function AdminPage({
  metrics,
  observability,
  refreshing,
  onRefresh,
}: {
  metrics: Record<string, any> | null
  observability: Record<string, any> | null
  refreshing: boolean
  onRefresh: () => void
}) {
  const dependencies = metrics?.dependency_status || {}
  const metricStatus = metrics?.metrics_status || {}
  const platform = metrics || {}
  const cards = [
    ['Repositories analyzed', platform.repositories_analyzed],
    ['Analyses performed', platform.analyses_performed],
    ['Commits analyzed', platform.commits_analyzed],
    ['Lines of code scanned', platform.lines_of_code_scanned],
    ['Graph nodes', platform.total_nodes],
    ['Graph relationships', platform.total_edges],
    ['Dependencies detected', platform.dependencies_detected],
    ['Active jobs', observability?.active_jobs_count ?? 0],
  ]
  return (
    <section>
      <div className="page-heading">
        <div>
          <p className="eyebrow">Owner-only operational view</p>
          <h1>Admin</h1>
          <p>Live service health and persisted platform metrics. Nothing is estimated or fabricated.</p>
        </div>
        <div className="heading-actions">
          <button className="button secondary-button" onClick={onRefresh}>
            <Icon name="refresh" className={refreshing ? 'spin' : ''} size={16} /> Refresh
          </button>
        </div>
      </div>
      <div className="panel admin-status-panel">
        <div className="panel-header">
          <div>
            <h2>Dependency status</h2>
            <p>Last checked during page load or refresh</p>
          </div>
          <span className={`status-pill ${dependencies.status === 'healthy' ? 'healthy' : 'attention'}`}>
            <i />{dependencies.status || 'unknown'}
          </span>
        </div>
        <div className="admin-status-grid">
          <div>
            <span>MongoDB</span>
            <strong>{dependencies.mongodb || 'unknown'}</strong>
          </div>
          <div>
            <span>Neo4j</span>
            <strong>{dependencies.neo4j || 'unknown'}</strong>
          </div>
          <div>
            <span>Checked at</span>
            <strong>{dependencies.checked_at ? new Date(dependencies.checked_at).toLocaleString() : 'unknown'}</strong>
          </div>
        </div>
      </div>
      <section className="metrics-grid admin-metrics-grid">
        {cards.map(([label, value]) => (
          <article className="metric-card" key={label}>
            <span className="metric-icon violet"><Icon name="activity" size={18} /></span>
            <div className="metric-value-row">
              <strong>{value == null ? '—' : typeof value === 'number' ? value.toLocaleString() : value}</strong>
            </div>
            <p>{label}</p>
          </article>
        ))}
      </section>
      <div className="dashboard-grid">
        <div className="panel detail-panel">
          <div className="panel-header">
            <div>
              <h2>Metric collection status</h2>
              <p>Persistence coverage for core operational metrics</p>
            </div>
          </div>
          <div className="admin-metric-state">
            <strong>{metricStatus.state || 'unknown'}</strong>
            <span>{metricStatus.message || 'No collection status available.'}</span>
            {Array.isArray(metricStatus.missing_metrics) && metricStatus.missing_metrics.length > 0 && (
              <small>Pending events: {metricStatus.missing_metrics.join(', ')}</small>
            )}
          </div>
        </div>
        <aside className="side-stack">
          <div className="panel monitoring-card">
            <div className="monitoring-heading">
              <span className="live-icon"><Icon name="monitor" size={17} /></span>
              <div>
                <h2>Runtime</h2>
                <p>Current worker state</p>
              </div>
            </div>
            <div className="monitoring-stats">
              <div>
                <span>Historical analysis success rate</span>
                <strong>{observability?.success_rate_pct == null ? '—' : `${observability.success_rate_pct}%`}</strong>
              </div>
              <div>
                <span>Cache size</span>
                <strong>{observability?.cache_size_mb == null ? '—' : `${observability.cache_size_mb} MB`}</strong>
              </div>
            </div>
          </div>
          <div className="panel monitoring-card">
            <div className="monitoring-heading">
              <span className="live-icon"><Icon name="shield" size={17} /></span>
              <div>
                <h2>Access</h2>
                <p>Restricted administrator view</p>
              </div>
            </div>
            <p className="admin-access-note">Visible only to ArvindNandigam.</p>
          </div>
        </aside>
      </div>
    </section>
  )
}

function Diagnostics() {
  const [data, setData] = useState<Record<string, any> | null>(null)
  const [error, setError] = useState('')
  useEffect(() => {
    api
      .diagnostics()
      .then(setData)
      .catch((reason) => setError(reason instanceof Error ? reason.message : 'Diagnostics unavailable'))
  }, [])
  return (
    <section>
      <div className="page-heading">
        <div>
          <p className="eyebrow">Service health</p>
          <h1>Diagnostics</h1>
          <p>Safe, read-only dependency checks. Credentials and configuration values are never shown.</p>
        </div>
      </div>
      <div className="panel detail-panel">
        {error ? (
          <div className="error-banner" role="alert">{error}</div>
        ) : (
          <pre className="diagnostics">{JSON.stringify(data || { status: 'checking' }, null, 2)}</pre>
        )}
      </div>
    </section>
  )
}

export default App
