import { useEffect, useMemo, useState } from 'react'
import { api, type Dashboard, type Graph, type Repository, subscribeToStatus } from './api'

type IconName = 'activity' | 'alert' | 'arrow' | 'branch' | 'check' | 'chevron' | 'code' | 'compare' | 'dashboard' | 'download' | 'heart' | 'monitor' | 'refresh' | 'report' | 'search' | 'settings' | 'shield' | 'spark' | 'trend'

const icons: Record<IconName, React.ReactNode> = {
  activity: <path d="M3 12h3l2.2-6 4 12 2.6-7H21" />,
  alert: <><path d="M10.3 3.2 2.6 17a2 2 0 0 0 1.8 3h15.2a2 2 0 0 0 1.8-3L13.7 3.2a2 2 0 0 0-3.4 0Z" /><path d="M12 9v4M12 17h.01" /></>,
  arrow: <><path d="M5 12h14M14 7l5 5-5 5" /></>,
  branch: <><circle cx="6" cy="5" r="2" /><circle cx="18" cy="6" r="2" /><circle cx="6" cy="19" r="2" /><path d="M6 7v10M8 7c5 0 4 7 8 7h2M18 8v6" /></>,
  check: <path d="m5 12 4 4L19 6" />,
  chevron: <path d="m9 18 6-6-6-6" />,
  code: <><path d="m8 9-3 3 3 3M16 9l3 3-3 3M14 5l-4 14" /></>,
  compare: <><path d="M8 7h11m0 0-3-3m3 3-3 3M16 17H5m0 0 3-3m-3 3 3 3" /></>,
  dashboard: <><rect x="3" y="3" width="7" height="7" rx="2" /><rect x="14" y="3" width="7" height="7" rx="2" /><rect x="3" y="14" width="7" height="7" rx="2" /><rect x="14" y="14" width="7" height="7" rx="2" /></>,
  download: <><path d="M12 3v12m-4-4 4 4 4-4M5 21h14" /></>,
  heart: <path d="M20.8 4.6a5.5 5.5 0 0 0-7.8 0L12 5.7l-1.1-1.1a5.5 5.5 0 0 0-7.8 7.8L12 21l8.8-8.6a5.5 5.5 0 0 0 0-7.8Z" />,
  monitor: <><rect x="3" y="4" width="18" height="13" rx="2" /><path d="M8 21h8M12 17v4M7 11h2l1.5-3 3 6 1.5-3h2" /></>,
  refresh: <><path d="M20 11a8 8 0 1 0-2.3 5.7L20 14" /><path d="M20 8v6h-6" /></>,
  report: <><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8Z" /><path d="M14 2v6h6M8 13h2M8 17h8M14 13h2" /></>,
  search: <><circle cx="11" cy="11" r="7" /><path d="m20 20-4-4" /></>,
  settings: <><circle cx="12" cy="12" r="3" /><path d="M19 15a2 2 0 0 0 2-1v-4a2 2 0 0 0-2-1 2 2 0 0 1-1-3 2 2 0 0 0-3-2 2 2 0 0 1-3-1 2 2 0 0 0-4 0 2 2 0 0 1-3 1 2 2 0 0 0-3 2 2 2 0 0 1-1 3 2 2 0 0 0 0 4 2 2 0 0 1 1 3 2 2 0 0 0 3 2 2 0 0 1 3 1 2 2 0 0 0 4 2 2 0 0 1 3-1 2 2 0 0 0 3-2 2 2 0 0 1 1-3Z" /></>,
  shield: <><path d="M12 22s8-3.5 8-10V5l-8-3-8 3v7c0 6.5 8 10 8 10Z" /><path d="m9 12 2 2 4-4" /></>,
  spark: <path d="m12 3 1.2 4.1L17 9l-3.8 1.9L12 15l-1.2-4.1L7 9l3.8-1.9L12 3ZM5 15l.7 2.3L8 18l-2.3.7L5 21l-.7-2.3L2 18l2.3-.7L5 15ZM19 13l.6 1.8 1.9.7-1.9.7L19 18l-.6-1.8-1.9-.7 1.9-.7L19 13Z" />,
  trend: <><path d="m3 17 6-6 4 4 8-9" /><path d="M15 6h6v6" /></>,
}

function Icon({ name, size = 18, className = '' }: { name: IconName; size?: number; className?: string }) {
  return <svg className={className} width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{icons[name]}</svg>
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
  return <svg className="sparkline" viewBox="0 0 110 38" preserveAspectRatio="none"><polyline points={coordinates} fill="none" stroke="#3f8d70" strokeWidth="2" vectorEffect="non-scaling-stroke" /></svg>
}

function GraphCanvas({ graph, nodes }: { graph: Graph; nodes: Array<{ data: Record<string, unknown> }> }) {
  const width = 760
  const height = 300
  const positions = new Map(nodes.map((node, index) => [String(node.data.id), {
    x: 45 + (index % 6) * 135,
    y: 45 + Math.floor(index / 6) * 82,
  }]))
  const edgeValue = (edge: { data: Record<string, unknown> }, keys: string[]) => keys.map((key) => edge.data[key]).find(Boolean)
  return <div className="graph-canvas" role="img" aria-label={`Dependency graph with ${nodes.length} nodes and ${graph.edges.length} relationships`}>
    <svg viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="xMidYMid meet">
      {graph.edges.map((edge, index) => {
        const source = positions.get(String(edgeValue(edge, ['source', 'from'])))
        const target = positions.get(String(edgeValue(edge, ['target', 'to'])))
        return source && target ? <line key={`edge-${index}`} x1={source.x} y1={source.y} x2={target.x} y2={target.y} /> : null
      })}
      {nodes.map((node) => {
        const id = String(node.data.id)
        const position = positions.get(id)
        if (!position) return null
        const label = String(node.data.label || node.data.path || id).split(/[\\/]/).pop()
        return <g key={id} transform={`translate(${position.x},${position.y})`}><circle r="17" className={`graph-dot graph-dot-${String(node.data.type || 'node')}`} /><text y="31" textAnchor="middle">{label.slice(0, 18)}</text></g>
      })}
    </svg>
  </div>
}

function RepositoryRow({ repo, onOpen }: { repo: Repository; onOpen: () => void }) {
  const score = repo.health_score ?? 0
  const status = repo.analysis_status === 'completed' && repo.health_score !== null ? 'Healthy' : repo.analysis_status === 'not_analyzed' ? 'Not analyzed' : 'In progress'
  return <div className="repo-row">
    <div className="repo-name-cell"><span className="repo-icon"><Icon name="code" size={17} /></span><div><button className="repo-name" onClick={onOpen}>{repo.name}</button><span>{repo.language || 'Repository'} � {repo.default_branch || 'default'}</span></div></div>
    <div className="health-cell"><div className={`score-ring ${score < 80 ? 'warning' : ''}`} style={{ '--score': `${score * 3.6}deg` } as React.CSSProperties}><span>{repo.health_score ?? '�'}</span></div><Sparkline points={repo.trend} /></div>
    <div className="analysis-cell"><strong>{repo.last_analysis ? new Date(repo.last_analysis).toLocaleString() : 'Not analyzed'}</strong><span><Icon name="branch" size={12} />{repo.last_commit_analyzed?.slice(0, 7) || '�'}</span></div>
    <div><span className={`status-pill ${status === 'Healthy' ? 'healthy' : 'attention'}`}><i />{status}</span></div>
    <button className="row-action" aria-label={`Open ${repo.name}`} onClick={onOpen}><Icon name="chevron" size={17} /></button>
  </div>
}

function App() {
  const [page, setPage] = useState('Overview')
  const [dashboard, setDashboard] = useState<Dashboard | null>(null)
  const [selected, setSelected] = useState<Repository | null>(null)
  const [overview, setOverview] = useState<Record<string, any> | null>(null)
  const [graph, setGraph] = useState<Graph | null>(null)
  const [compare, setCompare] = useState<Record<string, any> | null>(null)
  const [history, setHistory] = useState<Record<string, any> | null>(null)
  const [monitoring, setMonitoring] = useState<Record<string, any> | null>(null)
  const [adminMetrics, setAdminMetrics] = useState<Record<string, any> | null>(null)
  const [adminObservability, setAdminObservability] = useState<Record<string, any> | null>(null)
  const [migration, setMigration] = useState<Record<string, any> | null>(null)
  const [query, setQuery] = useState('')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [refreshing, setRefreshing] = useState(false)
  const [graphQuery, setGraphQuery] = useState('')
  const [graphType, setGraphType] = useState('all')
  const [status, setStatus] = useState<Record<string, any> | null>(null)
  const [triaged, setTriaged] = useState<string[]>(() => JSON.parse(localStorage.getItem('repoheal-triage') || '[]'))
  const navigate = (nextPage: string) => {
    setPage(nextPage)
    const params = new URLSearchParams(window.location.search)
    const view = nextPage === 'Repository' ? 'repository' : nextPage === 'Reports' ? 'reports' : nextPage === 'Monitoring' ? 'monitoring' : nextPage === 'Admin' ? 'admin' : undefined
    if (view) params.set('view', view)
    else params.delete('view')
    window.history.pushState({}, '', `${window.location.pathname}${params.toString() ? `?${params}` : ''}`)
  }

  const loadDashboard = async () => {
    setLoading(true); setError('')
    try { setDashboard(await api.dashboard()) } catch (reason) { setError(reason instanceof Error ? reason.message : 'Unable to load dashboard') } finally { setLoading(false) }
  }
  useEffect(() => {
    const params = new URLSearchParams(window.location.search)
    const view = params.get('view')
    if (view === 'repository') setPage('Repository')
    if (view === 'reports') setPage('Reports')
    if (view === 'monitoring') setPage('Monitoring')
    if (view === 'admin') setPage('Admin')
    void loadDashboard()
  }, [])

  useEffect(() => {
    const handlePopState = () => {
      const view = new URLSearchParams(window.location.search).get('view')
      setPage(view === 'repository' ? 'Repository' : view === 'reports' ? 'Reports' : view === 'monitoring' ? 'Monitoring' : view === 'admin' ? 'Admin' : 'Overview')
    }
    window.addEventListener('popstate', handlePopState)
    return () => window.removeEventListener('popstate', handlePopState)
  }, [])

  const openRepository = async (repo: Repository) => {
    setSelected(repo); navigate('Repository'); setOverview(null); setGraph(null); setCompare(null); setHistory(null); setMonitoring(null); setStatus(null)
    try {
      const [nextOverview, nextGraph] = await Promise.all([api.overview(repo.owner, repo.repo), api.graph(repo.owner, repo.repo)])
      setOverview(nextOverview); setGraph(nextGraph)
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'Repository data is unavailable') }
  }

  useEffect(() => {
    if (!selected) return
    return subscribeToStatus(selected.owner, selected.repo, (next) => setStatus(next))
  }, [selected])

  const repos = useMemo(() => (dashboard?.repositories || []).filter((repo) => repo.name.toLowerCase().includes(query.toLowerCase()) || repo.repo.toLowerCase().includes(query.toLowerCase())), [dashboard, query])
  const visibleNodes = useMemo(() => (graph?.nodes || []).filter((node) => {
    const data = node.data
    return (graphType === 'all' || data.type === graphType) && (!graphQuery || String(data.label || data.path || '').toLowerCase().includes(graphQuery.toLowerCase()))
  }), [graph, graphQuery, graphType])

  const toggleTriage = (issue: string) => {
    const next = triaged.includes(issue) ? triaged.filter((item) => item !== issue) : [...triaged, issue]
    setTriaged(next); localStorage.setItem('repoheal-triage', JSON.stringify(next))
  }

  const startAnalysis = async () => {
    if (!selected) return
    setRefreshing(true)
    try { await api.startAnalysis(selected.owner, selected.repo); setStatus({ status: 'queued', progress: 0, message: 'Analysis queued' }) } catch (reason) { setError(reason instanceof Error ? reason.message : 'Could not start analysis') } finally { setRefreshing(false) }
  }

  const loadReports = async () => {
    const repo = selected || repos[0]
    if (!repo) return
    setSelected(repo)
    setRefreshing(true)
    try {
      const [nextHistory, nextHealth] = await Promise.all([
        api.history(repo.owner, repo.repo),
        api.health(repo.owner, repo.repo),
      ])
      setHistory(nextHistory)
      setOverview((current) => current || { health: nextHealth })
      setMigration(null)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Reports are unavailable')
    } finally {
      setRefreshing(false)
    }

    const loadMigration = async (analysisId?: string) => {
      const repo = selected || repos[0]
      if (!repo) return
      setRefreshing(true)
      try {
        setMigration(await api.migration(repo.owner, repo.repo, analysisId))
      } catch (reason) {
        setMigration(null)
        setError(reason instanceof Error ? reason.message : 'Migration report is unavailable')
      } finally {
        setRefreshing(false)
      }
    }
  }

  const loadMonitoring = async () => {
    const repo = selected || repos[0]
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

  const loadAdmin = async () => {
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

  useEffect(() => {
    if (page === 'Reports') void loadReports()
    if (page === 'Monitoring') void loadMonitoring()
    if (page === 'Admin') {
      void loadAdmin()
    }
  }, [page, dashboard])

  useEffect(() => {
    if (!dashboard) return
    const params = new URLSearchParams(window.location.search)
    const owner = params.get('owner')
    const repoName = params.get('repo')
    if (!owner || !repoName || selected) return
    const match = dashboard.repositories.find((repo) => repo.owner === owner && repo.repo === repoName)
    if (match) void openRepository(match)
  }, [dashboard])

  const title = page === 'Overview' ? `Good morning, ${dashboard?.user || 'there'}.` : page
  const metrics = dashboard?.metrics
  const issues = overview?.health?.issues?.items || overview?.health?.issues?.findings || []

  return <div className="app-shell">
    <aside className="sidebar">
      <a className="brand" href="#overview" onClick={(event) => { event.preventDefault(); navigate('Overview') }}><span className="brand-mark"><Icon name="heart" size={19} /></span><span>RepoHeal</span></a>
      <nav className="main-nav" aria-label="Primary navigation">
        <p className="nav-label">Workspace</p>
        {[['Overview', 'dashboard'], ['Repositories', 'code'], ['Reports', 'report'], ['Monitoring', 'monitor']].map(([label, icon]) => <button key={label} className={`nav-item ${page === label ? 'active' : ''}`} onClick={() => navigate(label)}><Icon name={icon as IconName} size={18} /><span>{label}</span></button>)}
        <p className="nav-label secondary">Manage</p>
        <button className={`nav-item ${page === 'Diagnostics' ? 'active' : ''}`} onClick={() => navigate('Diagnostics')}><Icon name="settings" size={18} /><span>Diagnostics</span></button>
        {dashboard?.user === 'ArvindNandigam' && <button className={`nav-item ${page === 'Admin' ? 'active' : ''}`} onClick={() => navigate('Admin')}><Icon name="shield" size={18} /><span>Admin</span></button>}
      </nav>
      <div className="sidebar-insight"><span className="insight-icon"><Icon name="spark" size={16} /></span><strong>Local triage</strong><p>Keep issue decisions in this browser without changing GitHub state.</p></div>
      <div className="profile"><div className="avatar">{(dashboard?.user || '?').slice(0, 2).toUpperCase()}</div><div><strong>{dashboard?.user || 'Authenticated user'}</strong><span>@{dashboard?.user || 'unknown'}</span></div></div>
    </aside>
    <main className="main">
      <header className="topbar"><div className="mobile-brand"><span className="brand-mark"><Icon name="heart" size={17} /></span><strong>RepoHeal</strong></div><div className="search-wrap"><Icon name="search" size={17} /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search repositories..." aria-label="Search repositories" /></div><div className="top-actions"><span className="sync-status"><span /> Authenticated workspace</span></div></header>
      <div className="content">
        {error && <div className="error-banner" role="alert">{error}<button onClick={() => setError('')}>Dismiss</button></div>}
        {loading ? <div className="loading-state" aria-live="polite">Loading authenticated workspace�</div> : page === 'Repository' && selected ? <section>
          <section className="page-heading"><div><p className="eyebrow">{selected.owner}/{selected.repo}</p><h1>{overview?.metadata?.name || selected.repo}</h1><p>{overview?.metadata?.description || selected.description || 'Repository overview and analysis history'}</p></div><div className="heading-actions"><button className="button secondary-button" onClick={startAnalysis}><Icon name="refresh" size={16} />{refreshing ? 'Starting�' : 'Run analysis'}</button><button className="button primary-button" onClick={() => navigate('Reports')}><Icon name="report" size={16} /> Reports</button></div></section>
          {status && status.status !== 'completed' && <div className="progress-card"><strong>Analysis {status.status}</strong><span>{status.message}</span><progress value={status.progress || 0} max="100" /><b>{status.progress || 0}%</b></div>}
          <div className="metrics-grid"><article className="metric-card featured"><span className="metric-icon mint"><Icon name="heart" size={18} /></span><div className="metric-value-row"><strong>{overview?.health?.score ?? '�'}</strong><span className="score-unit">/100</span></div><p>Health score</p></article><article className="metric-card"><span className="metric-icon violet"><Icon name="code" size={18} /></span><div className="metric-value-row"><strong>{overview?.graph?.files ?? '�'}</strong></div><p>Files analyzed</p></article><article className="metric-card"><span className="metric-icon amber"><Icon name="alert" size={18} /></span><div className="metric-value-row"><strong>{overview?.health?.risk_score ?? '�'}</strong></div><p>Migration risk</p></article><article className="metric-card"><span className="metric-icon blue"><Icon name="branch" size={18} /></span><div className="metric-value-row"><strong>{status?.code_state_status || overview?.status?.code_state_status || 'unknown'}</strong></div><p>Code state</p></article></div>
          <div className="dashboard-grid"><div className="panel graph-panel"><div className="panel-header"><div><h2>Dependency graph</h2><p>{graph?.nodes?.length ? `${visibleNodes.length} of ${graph.nodes.length} nodes � ${graph.edges.length} relationships` : 'Run an analysis to create a graph snapshot.'}</p></div><div className="graph-tools"><input value={graphQuery} onChange={(event) => setGraphQuery(event.target.value)} placeholder="Find path or symbol" aria-label="Filter graph nodes" /><select value={graphType} onChange={(event) => setGraphType(event.target.value)} aria-label="Filter graph node type"><option value="all">All types</option><option value="file">Files</option><option value="package">Packages</option><option value="function">Functions</option></select></div></div>{graph?.nodes?.length ? <><GraphCanvas graph={graph} nodes={visibleNodes.slice(0, 30)} /><div className="graph-list">{visibleNodes.slice(0, 120).map((node) => { const label = String(node.data.label || node.data.path || node.data.id); const match = graphQuery ? label.toLowerCase().indexOf(graphQuery.toLowerCase()) : -1; return <span key={String(node.data.id)} className={`graph-node graph-${String(node.data.type)}`}>{match >= 0 ? <>{label.slice(0, match)}<mark>{label.slice(match, match + graphQuery.length)}</mark>{label.slice(match + graphQuery.length)}</> : label}</span> })}</div></> : <div className="empty-state">No graph snapshot is available. Run an analysis first, or check diagnostics if Neo4j is unavailable.</div>}<div className="export-actions"><button onClick={() => graph && download(`${selected.repo}-graph.json`, JSON.stringify(graph, null, 2), 'application/json')} disabled={!graph?.nodes?.length}><Icon name="download" size={14} /> JSON</button><button onClick={() => graph && download(`${selected.repo}-graph.md`, `# ${selected.owner}/${selected.repo} graph\n\nNodes: ${graph.nodes.length}\nEdges: ${graph.edges.length}\n`, 'text/markdown')} disabled={!graph?.nodes?.length}><Icon name="download" size={14} /> Markdown</button><a href={`/visualize/${selected.owner}/${selected.repo}/export.png`} target="_blank" rel="noreferrer" className={!graph?.nodes?.length ? 'disabled' : ''}><Icon name="download" size={14} /> PNG</a></div></div><aside className="side-stack"><div className="panel"><div className="panel-header compact"><div><h2>Issue triage</h2><p>Local-only decisions</p></div></div>{Array.isArray(issues) && issues.slice(0, 5).map((issue: any, index: number) => { const key = String(issue.id || issue.symbol || issue.title || index); return <label className="triage-item" key={key}><input type="checkbox" checked={triaged.includes(key)} onChange={() => toggleTriage(key)} /><span>{issue.title || issue.symbol || issue.message || 'Finding'}</span></label> })}{(!Array.isArray(issues) || issues.length === 0) && <div className="empty-state">No historical issue list is available.</div>}</div><div className="panel monitoring-card"><div className="monitoring-heading"><span className="live-icon"><Icon name="compare" size={17} /></span><div><h2>Comparison</h2><p>Compare saved analyses</p></div></div><button className="text-button" onClick={async () => { try { setCompare(await api.compare(selected.owner, selected.repo)); navigate('Compare') } catch (reason) { setError(reason instanceof Error ? reason.message : 'Comparison unavailable') } }}>Open comparison <Icon name="arrow" size={14} /> </button></div></aside></div>
        </section> : page === 'Compare' ? <section><div className="page-heading"><div><p className="eyebrow">Historical snapshots</p><h1>Comparison</h1><p>Review health changes between the two latest available analyses.</p></div></div><div className="panel detail-panel">{compare?.available ? <><div className="compare-grid"><div><span>Before</span><strong>{compare.left.commit || '�'}</strong><small>{compare.left.health_score ?? '�'} health</small></div><div><span>After</span><strong>{compare.right.commit || '�'}</strong><small>{compare.right.health_score ?? '�'} health</small></div></div>{compare.changes.map((change: any) => <div className="change-row" key={change.metric}><span>{change.metric}</span><b>{change.before ?? '�'}</b><Icon name="arrow" size={14} /><b>{change.after ?? '�'}</b><em>{change.delta == null ? 'changed' : `${change.delta > 0 ? '+' : ''}${change.delta}`}</em></div>)}</> : <div className="empty-state">{compare?.message || 'No comparison data available.'}</div>}</div></section> : page === 'Reports' ? <ReportsPage history={history} health={overview?.health} migration={migration} refreshing={refreshing} onRefresh={loadReports} onMigration={loadMigration} onOpenRepository={() => selected && void openRepository(selected)} /> : page === 'Monitoring' ? <MonitoringPage data={monitoring} refreshing={refreshing} onRefresh={loadMonitoring} /> : page === 'Admin' ? <AdminPage metrics={adminMetrics} observability={adminObservability} refreshing={refreshing} onRefresh={loadAdmin} /> : page === 'Diagnostics' ? <Diagnostics /> : <section><div className="page-heading"><div><p className="eyebrow">Authenticated workspace</p><h1>{title}</h1><p>{page === 'Overview' ? 'Live repository health from RepoHeal analysis and GitHub metadata.' : 'Repositories connected to your GitHub workspace.'}</p></div><div className="heading-actions"><button className="button secondary-button" onClick={() => { setRefreshing(true); void loadDashboard().finally(() => setRefreshing(false)) }}><Icon name="refresh" className={refreshing ? 'spin' : ''} size={16} /> Refresh</button></div></div><section className="metrics-grid"><article className="metric-card featured"><span className="metric-icon mint"><Icon name="heart" size={18} /></span><div className="metric-value-row"><strong>{metrics?.average_health_score ?? '�'}</strong><span className="score-unit">/100</span></div><p>Average health score</p></article><article className="metric-card"><span className="metric-icon violet"><Icon name="code" size={18} /></span><div className="metric-value-row"><strong>{metrics?.active_repositories ?? 0}</strong></div><p>Active repositories</p></article><article className="metric-card"><span className="metric-icon amber"><Icon name="alert" size={18} /></span><div className="metric-value-row"><strong>{metrics?.open_issues ?? 0}</strong></div><p>Open issues � {metrics?.critical_issues ?? 0} critical</p></article><article className="metric-card"><span className="metric-icon blue"><Icon name="activity" size={18} /></span><div className="metric-value-row"><strong>{metrics?.active_analyses ?? 0}</strong></div><p>Analyses in progress</p></article></section><div className="panel repositories-panel"><div className="panel-header"><div><h2>Repositories</h2><p>Live metadata and analysis state</p></div></div><div className="repo-table"><div className="table-head"><span>Repository</span><span>Health score</span><span>Last analysis</span><span>Status</span><span /></div>{repos.map((repo) => <RepositoryRow key={repo.name} repo={repo} onOpen={() => void openRepository(repo)} />)}{repos.length === 0 && <div className="empty-state">{dashboard?.repositories.length ? 'No repositories match your search.' : 'No installed repositories are available.'}</div>}</div></div></section>}
      </div>
    </main>
  </div>
}

function ReportsPage({ history, health, migration, refreshing, onRefresh, onMigration, onOpenRepository }: { history: Record<string, any> | null; health: Record<string, any> | undefined; migration: Record<string, any> | null; refreshing: boolean; onRefresh: () => void; onMigration: (analysisId?: string) => void; onOpenRepository: () => void }) {
  const timeline = Array.isArray(history?.timeline) ? history.timeline : []
  const score = health?.score ?? health?.overall_health_score
  return <section>
    <div className="page-heading">
      <div><p className="eyebrow">Evidence from completed analyses</p><h1>Reports</h1><p>Health reports and analysis history loaded from GitHub metadata.</p></div>
      <div className="heading-actions"><button className="button secondary-button" onClick={onRefresh}><Icon name="refresh" className={refreshing ? 'spin' : ''} size={16} /> Refresh</button><button className="button primary-button" onClick={onOpenRepository}><Icon name="code" size={16} /> Open repository</button></div>
    </div>
    <section className="metrics-grid">
      <article className="metric-card featured"><span className="metric-icon mint"><Icon name="heart" size={18} /></span><div className="metric-value-row"><strong>{score ?? '�'}</strong><span className="score-unit">/100</span></div><p>Latest health score</p></article>
      <article className="metric-card"><span className="metric-icon violet"><Icon name="report" size={18} /></span><div className="metric-value-row"><strong>{timeline.length}</strong></div><p>Saved analyses</p></article>
      <article className="metric-card"><span className="metric-icon blue"><Icon name="branch" size={18} /></span><div className="metric-value-row"><strong>{history?.current_head?.slice(0, 7) || '�'}</strong></div><p>Current repository head</p></article>
      <article className="metric-card"><span className="metric-icon amber"><Icon name="shield" size={18} /></span><div className="metric-value-row"><strong>{health?.overall_risk_score ?? '�'}</strong></div><p>Latest risk score</p></article>
    </section>
    <div className="panel repositories-panel">
      <div className="panel-header"><div><h2>Analysis history</h2><p>{history?.repository || 'Select a repository to load report history.'}</p></div></div>
      <div className="repo-table">
        <div className="table-head"><span>Analysis</span><span>Branch</span><span>Commit</span><span>Health</span><span /></div>
        {timeline.map((item: any) => <div className="repo-row" key={item.analysis_id || item.timestamp}>
          <div className="repo-name-cell"><span className="repo-icon"><Icon name="report" size={17} /></span><div><strong className="repo-name">{item.analysis_id || 'Analysis'}</strong><span>{item.timestamp ? new Date(item.timestamp).toLocaleString() : 'Unknown date'}</span></div></div>
          <div className="analysis-cell"><strong>{item.branch || '�'}</strong></div>
          <div className="analysis-cell"><span>{item.commit?.slice(0, 7) || '�'}</span></div>
          <div><span className="status-pill healthy"><i />{item.health_score ?? '�'}</span></div>
          <button className="row-action" onClick={() => onMigration(item.analysis_id)} aria-label="Load migration report"><Icon name="chevron" size={17} /></button>
        </div>)}
        {timeline.length === 0 && <div className="empty-state">No saved analyses or health reports are available for this repository.</div>}
      </div>
    </div>
    <div className="panel detail-panel migration-panel">
      <div className="panel-header"><div><h2>Migration report</h2><p>Loaded from the persisted repository metadata branch.</p></div></div>
      {migration?.content ? <pre className="migration-content">{migration.content}</pre> : <div className="empty-state">Select an analysis row to load its migration document. If none exists, the backend will report that honestly.</div>}
    </div>
  </section>
}

function MonitoringPage({ data, refreshing, onRefresh }: { data: Record<string, any> | null; refreshing: boolean; onRefresh: () => void }) {
  const alerts = Array.isArray(data?.active_alerts) ? data.active_alerts : []
  const watchlist = Array.isArray(data?.watchlist) ? data.watchlist : []
  const history = Array.isArray(data?.health_history) ? data.health_history : []
  return <section>
    <div className="page-heading">
      <div><p className="eyebrow">Live MongoDB monitoring data</p><h1>Monitoring</h1><p>Alerts, dependency watchlist, health snapshots, and schedule settings.</p></div>
      <div className="heading-actions"><button className="button secondary-button" onClick={onRefresh}><Icon name="refresh" className={refreshing ? 'spin' : ''} size={16} /> Refresh</button></div>
    </div>
    <section className="metrics-grid">
      <article className="metric-card featured"><span className="metric-icon mint"><Icon name="activity" size={18} /></span><div className="metric-value-row"><strong>{alerts.length}</strong></div><p>Active alerts</p></article>
      <article className="metric-card"><span className="metric-icon amber"><Icon name="alert" size={18} /></span><div className="metric-value-row"><strong>{watchlist.length}</strong></div><p>Watched dependencies</p></article>
      <article className="metric-card"><span className="metric-icon violet"><Icon name="trend" size={18} /></span><div className="metric-value-row"><strong>{history.length}</strong></div><p>Health snapshots</p></article>
      <article className="metric-card"><span className="metric-icon blue"><Icon name="monitor" size={18} /></span><div className="metric-value-row"><strong>{data?.schedule?.frequency || '�'}</strong></div><p>Monitoring schedule</p></article>
    </section>
    <div className="dashboard-grid">
      <div className="panel repositories-panel"><div className="panel-header"><div><h2>Active alerts</h2><p>Only persisted, undismissed alerts are shown.</p></div></div>{alerts.length ? alerts.slice(0, 10).map((alert: any) => <div className="risk-item" key={alert.id || alert.created_at}><span className="risk-severity critical"><Icon name="alert" size={15} /></span><div><strong>{alert.title || alert.category || 'Alert'}</strong><p>{alert.message || alert.description || 'No description available.'}</p><span>{alert.severity || 'unknown'} � {alert.created_at ? new Date(alert.created_at).toLocaleString() : 'Unknown time'}</span></div></div>) : <div className="empty-state">No active alerts are recorded.</div>}</div>
      <aside className="side-stack"><div className="panel"><div className="panel-header compact"><div><h2>Dependency watchlist</h2><p>Persisted packages under observation</p></div></div>{watchlist.length ? watchlist.slice(0, 8).map((item: any) => <div className="risk-item" key={item.package_name}><span className="risk-severity moderate"><Icon name="code" size={15} /></span><div><strong>{item.package_name || 'Dependency'}</strong><p>{item.current_version || 'Current version unknown'}</p><span>{item.risk_level || 'unclassified'}</span></div></div>) : <div className="empty-state">No dependencies are being watched.</div>}</div><div className="panel monitoring-card"><div className="monitoring-heading"><span className="live-icon"><Icon name="monitor" size={17} /></span><div><h2>Schedule</h2><p>Configured monitoring cadence</p></div></div><div className="monitoring-stats"><div><span>Frequency</span><strong>{data?.schedule?.frequency || '�'}</strong></div><div><span>Next run</span><strong>{data?.schedule?.next_run ? new Date(data.schedule.next_run).toLocaleString() : 'Not scheduled'}</strong></div></div></div></aside>
    </div>
  </section>
}

function AdminPage({ metrics, observability, refreshing, onRefresh }: { metrics: Record<string, any> | null; observability: Record<string, any> | null; refreshing: boolean; onRefresh: () => void }) {
  const dependencies = metrics?.dependency_status || {}
  const metricStatus = metrics?.metrics_status || {}
  const platform = metrics || {}
  const cards = [
    ['Repositories analyzed', platform.repositories_analyzed],
    ['Analyses performed', platform.analyses_performed],
    ['Commits analyzed', platform.commits_analyzed],
    ['Graph nodes', platform.total_nodes],
    ['Graph relationships', platform.total_edges],
    ['Dependencies detected', platform.dependencies_detected],
    ['Active jobs', observability?.active_jobs_count],
    ['Total analyses', observability?.total_analyses],
  ]
  return <section>
    <div className="page-heading">
      <div><p className="eyebrow">Owner-only operational view</p><h1>Admin</h1><p>Live service health and persisted platform metrics. Nothing is estimated or fabricated.</p></div>
      <div className="heading-actions"><button className="button secondary-button" onClick={onRefresh}><Icon name="refresh" className={refreshing ? 'spin' : ''} size={16} /> Refresh</button></div>
    </div>
    <div className="panel admin-status-panel">
      <div className="panel-header"><div><h2>Dependency status</h2><p>Checked live when this page loads</p></div><span className={`status-pill ${dependencies.status === 'healthy' ? 'healthy' : 'attention'}`}><i />{dependencies.status || 'unknown'}</span></div>
      <div className="admin-status-grid"><div><span>MongoDB</span><strong>{dependencies.mongodb || 'unknown'}</strong></div><div><span>Neo4j</span><strong>{dependencies.neo4j || 'unknown'}</strong></div><div><span>Checked at</span><strong>{dependencies.checked_at ? new Date(dependencies.checked_at).toLocaleString() : 'unknown'}</strong></div></div>
    </div>
    <section className="metrics-grid admin-metrics-grid">{cards.map(([label, value]) => <article className="metric-card" key={label}><span className="metric-icon violet"><Icon name="activity" size={18} /></span><div className="metric-value-row"><strong>{value == null ? '�' : typeof value === 'number' ? value.toLocaleString() : value}</strong></div><p>{label}</p></article>)}</section>
    <div className="dashboard-grid">
      <div className="panel detail-panel"><div className="panel-header"><div><h2>Metric collection</h2><p>Whether persisted platform metrics are complete</p></div></div><div className="admin-metric-state"><strong>{metricStatus.state || 'unknown'}</strong><span>{metricStatus.message || 'No collection status available.'}</span>{Array.isArray(metricStatus.missing_metrics) && metricStatus.missing_metrics.length > 0 && <small>Missing: {metricStatus.missing_metrics.join(', ')}</small>}</div></div>
      <aside className="side-stack"><div className="panel monitoring-card"><div className="monitoring-heading"><span className="live-icon"><Icon name="monitor" size={17} /></span><div><h2>Runtime</h2><p>Current worker state</p></div></div><div className="monitoring-stats"><div><span>Success rate</span><strong>{observability?.success_rate_pct == null ? '�' : `${observability.success_rate_pct}%`}</strong></div><div><span>Cache size</span><strong>{observability?.cache_size_mb == null ? '�' : `${observability.cache_size_mb} MB`}</strong></div></div></div><div className="panel monitoring-card"><div className="monitoring-heading"><span className="live-icon"><Icon name="shield" size={17} /></span><div><h2>Access</h2><p>Restricted administrator view</p></div></div><p className="admin-access-note">Visible only to ArvindNandigam.</p></div></aside>
    </div>
  </section>
}

function Diagnostics() {
  const [data, setData] = useState<Record<string, any> | null>(null)
  const [error, setError] = useState('')
  useEffect(() => { api.diagnostics().then(setData).catch((reason) => setError(reason instanceof Error ? reason.message : 'Diagnostics unavailable')) }, [])
  return <section><div className="page-heading"><div><p className="eyebrow">Service health</p><h1>Diagnostics</h1><p>Safe, read-only dependency checks. Credentials and configuration values are never shown.</p></div></div><div className="panel detail-panel">{error ? <div className="error-banner" role="alert">{error}</div> : <pre className="diagnostics">{JSON.stringify(data || { status: 'checking' }, null, 2)}</pre>}</div></section>
}

export default App

