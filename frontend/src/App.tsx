import { useEffect, useMemo, useState } from 'react'

type IconName =
  | 'activity'
  | 'alert'
  | 'arrow'
  | 'branch'
  | 'check'
  | 'chevron'
  | 'clock'
  | 'code'
  | 'compare'
  | 'dashboard'
  | 'dots'
  | 'github'
  | 'heart'
  | 'history'
  | 'logout'
  | 'monitor'
  | 'moon'
  | 'refresh'
  | 'report'
  | 'search'
  | 'settings'
  | 'shield'
  | 'spark'
  | 'trend'

const paths: Record<IconName, React.ReactNode> = {
  activity: <><path d="M3 12h3l2.2-6 4 12 2.6-7H21" /></>,
  alert: <><path d="M10.3 3.2 2.6 17a2 2 0 0 0 1.8 3h15.2a2 2 0 0 0 1.8-3L13.7 3.2a2 2 0 0 0-3.4 0Z" /><path d="M12 9v4M12 17h.01" /></>,
  arrow: <><path d="M5 12h14M14 7l5 5-5 5" /></>,
  branch: <><circle cx="6" cy="5" r="2" /><circle cx="18" cy="6" r="2" /><circle cx="6" cy="19" r="2" /><path d="M6 7v10M8 7c5 0 4 7 8 7h2M18 8v6" /></>,
  check: <><path d="m5 12 4 4L19 6" /></>,
  chevron: <><path d="m9 18 6-6-6-6" /></>,
  clock: <><circle cx="12" cy="12" r="9" /><path d="M12 7v5l3 2" /></>,
  code: <><path d="m8 9-3 3 3 3M16 9l3 3-3 3M14 5l-4 14" /></>,
  compare: <><path d="M8 7h11m0 0-3-3m3 3-3 3M16 17H5m0 0 3-3m-3 3 3 3" /></>,
  dashboard: <><rect x="3" y="3" width="7" height="7" rx="2" /><rect x="14" y="3" width="7" height="7" rx="2" /><rect x="3" y="14" width="7" height="7" rx="2" /><rect x="14" y="14" width="7" height="7" rx="2" /></>,
  dots: <><circle cx="5" cy="12" r="1" fill="currentColor" stroke="none" /><circle cx="12" cy="12" r="1" fill="currentColor" stroke="none" /><circle cx="19" cy="12" r="1" fill="currentColor" stroke="none" /></>,
  github: <><path d="M15 22v-4a4.8 4.8 0 0 0-1-3.5c3.3-.4 6.8-1.6 6.8-7A5.4 5.4 0 0 0 19.3 4 5 5 0 0 0 19.2.5S18 0 15 1.8a13.4 13.4 0 0 0-7 0C5 .1 3.8.5 3.8.5A5 5 0 0 0 3.7 4a5.4 5.4 0 0 0-1.5 3.7c0 5.4 3.5 6.6 6.8 7a4.8 4.8 0 0 0-1 3.3v4" /><path d="M8 19c-3 .9-3-1.5-4.2-2" /></>,
  heart: <><path d="M20.8 4.6a5.5 5.5 0 0 0-7.8 0L12 5.7l-1.1-1.1a5.5 5.5 0 0 0-7.8 7.8L12 21l8.8-8.6a5.5 5.5 0 0 0 0-7.8Z" /></>,
  history: <><path d="M3 12a9 9 0 1 0 3-6.7L3 8" /><path d="M3 3v5h5M12 7v5l3 2" /></>,
  logout: <><path d="M10 17l5-5-5-5M15 12H3M14 3h5a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2h-5" /></>,
  monitor: <><rect x="3" y="4" width="18" height="13" rx="2" /><path d="M8 21h8M12 17v4M7 11h2l1.5-3 3 6 1.5-3h2" /></>,
  moon: <><path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8Z" /></>,
  refresh: <><path d="M20 11a8 8 0 1 0-2.3 5.7L20 14" /><path d="M20 8v6h-6" /></>,
  report: <><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8Z" /><path d="M14 2v6h6M8 13h2M8 17h8M14 13h2" /></>,
  search: <><circle cx="11" cy="11" r="7" /><path d="m20 20-4-4" /></>,
  settings: <><circle cx="12" cy="12" r="3" /><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.9l.1.1-2.8 2.8-.1-.1a1.7 1.7 0 0 0-1.9-.3 1.7 1.7 0 0 0-1 1.6v.2h-4V21a1.7 1.7 0 0 0-1-1.6 1.7 1.7 0 0 0-1.9.3l-.1.1L4.2 17l.1-.1a1.7 1.7 0 0 0 .3-1.9A1.7 1.7 0 0 0 3 14H2.8v-4H3a1.7 1.7 0 0 0 1.6-1 1.7 1.7 0 0 0-.3-1.9L4.2 7 7 4.2l.1.1a1.7 1.7 0 0 0 1.9.3 1.7 1.7 0 0 0 1-1.6v-.2h4V3a1.7 1.7 0 0 0 1 1.6 1.7 1.7 0 0 0 1.9-.3l.1-.1L19.8 7l-.1.1a1.7 1.7 0 0 0-.3 1.9 1.7 1.7 0 0 0 1.6 1h.2v4H21a1.7 1.7 0 0 0-1.6 1Z" /></>,
  shield: <><path d="M12 22s8-3.5 8-10V5l-8-3-8 3v7c0 6.5 8 10 8 10Z" /><path d="m9 12 2 2 4-4" /></>,
  spark: <><path d="m12 3 1.2 4.1L17 9l-3.8 1.9L12 15l-1.2-4.1L7 9l3.8-1.9L12 3ZM5 15l.7 2.3L8 18l-2.3.7L5 21l-.7-2.3L2 18l2.3-.7L5 15ZM19 13l.6 1.8 1.9.7-1.9.7L19 18l-.6-1.8-1.9-.7 1.9-.7L19 13Z" /></>,
  trend: <><path d="m3 17 6-6 4 4 8-9" /><path d="M15 6h6v6" /></>,
}

function Icon({ name, size = 18, className = '' }: { name: IconName; size?: number; className?: string }) {
  return <svg className={className} width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{paths[name]}</svg>
}

const sampleRepositories = [
  { name: 'api-gateway', description: 'Core API gateway and authentication layer', lang: 'TypeScript', color: '#5d54e9', score: 92, delta: 4, status: 'Healthy', updated: '12 min ago', branch: 'main', commit: 'a4f9c21', issues: 3, trend: [58, 63, 60, 72, 76, 81, 84, 92] },
  { name: 'data-pipeline', description: 'Event processing and warehouse ingestion', lang: 'Python', color: '#e3b341', score: 78, delta: -2, status: 'Needs attention', updated: '2 hrs ago', branch: 'production', commit: '7dc82be', issues: 8, trend: [82, 84, 81, 80, 82, 80, 79, 78] },
  { name: 'web-client', description: 'Customer-facing web application', lang: 'TypeScript', color: '#5d54e9', score: 88, delta: 6, status: 'Healthy', updated: 'Yesterday', branch: 'main', commit: 'c10ad44', issues: 4, trend: [66, 70, 72, 74, 78, 81, 82, 88] },
]

const navItems: { label: string; icon: IconName }[] = [
  { label: 'Overview', icon: 'dashboard' },
  { label: 'Repositories', icon: 'code' },
  { label: 'Reports', icon: 'report' },
  { label: 'Monitoring', icon: 'monitor' },
]

function Sparkline({ points, down = false }: { points: number[]; down?: boolean }) {
  const coordinates = points.map((point, index) => `${(index / (points.length - 1)) * 110},${34 - ((point - 50) / 50) * 28}`).join(' ')
  return (
    <svg className="sparkline" viewBox="0 0 110 38" preserveAspectRatio="none">
      <defs><linearGradient id={down ? 'down' : 'up'} x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor={down ? '#e2955f' : '#4f9e81'} stopOpacity=".24" /><stop offset="1" stopColor={down ? '#e2955f' : '#4f9e81'} stopOpacity="0" /></linearGradient></defs>
      <polygon points={`0,38 ${coordinates} 110,38`} fill={`url(#${down ? 'down' : 'up'})`} />
      <polyline points={coordinates} fill="none" stroke={down ? '#d68146' : '#3f8d70'} strokeWidth="2" vectorEffect="non-scaling-stroke" />
    </svg>
  )
}

function App() {
  const [activeNav, setActiveNav] = useState('Overview')
  const [repositories, setRepositories] = useState(sampleRepositories)
  const [query, setQuery] = useState('')
  const [filter, setFilter] = useState<'All' | 'Healthy' | 'Needs attention'>('All')
  const [refreshing, setRefreshing] = useState(false)
  const [watching, setWatching] = useState(true)

  useEffect(() => {
    let cancelled = false
    fetch('/dashboard/data', { credentials: 'include' })
      .then((response) => {
        if (!response.ok) throw new Error(`Dashboard request failed (${response.status})`)
        return response.json()
      })
      .then((data) => {
        if (cancelled || !Array.isArray(data.repositories) || data.repositories.length === 0) return
        setRepositories(data.repositories.map((repo: { name: string; owner: string; repo: string }) => ({
          name: repo.repo,
          description: `${repo.owner}/${repo.repo}`,
          lang: 'Repository',
          color: '#5d54e9',
          score: 0,
          delta: 0,
          status: 'Healthy',
          updated: 'Not analyzed',
          branch: 'default',
          commit: '—',
          issues: 0,
          trend: [50, 50, 50, 50, 50, 50, 50, 50],
        })))
      })
      .catch(() => {
        // Keep the design preview data when the authenticated API is unavailable.
      })
    return () => { cancelled = true }
  }, [])

  const filteredRepos = useMemo(() => repositories.filter((repo) => {
    const matchesSearch = repo.name.toLowerCase().includes(query.toLowerCase())
    return matchesSearch && (filter === 'All' || repo.status === filter)
  }), [filter, query])

  const refresh = () => {
    setRefreshing(true)
    window.setTimeout(() => setRefreshing(false), 900)
  }

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <a className="brand" href="#" onClick={(event) => { event.preventDefault(); setActiveNav('Overview') }}>
          <span className="brand-mark"><Icon name="heart" size={19} /></span>
          <span>RepoHeal</span>
        </a>

        <nav className="main-nav" aria-label="Primary navigation">
          <p className="nav-label">Workspace</p>
          {navItems.map((item) => (
            <button key={item.label} className={`nav-item ${activeNav === item.label ? 'active' : ''}`} onClick={() => setActiveNav(item.label)}>
              <Icon name={item.icon} size={18} />
              <span>{item.label}</span>
              {item.label === 'Monitoring' && <span className="nav-dot" />}
            </button>
          ))}
          <p className="nav-label secondary">Manage</p>
          <button className={`nav-item ${activeNav === 'Settings' ? 'active' : ''}`} onClick={() => setActiveNav('Settings')}>
            <Icon name="settings" size={18} /><span>Settings</span>
          </button>
        </nav>

        <div className="sidebar-insight">
          <span className="insight-icon"><Icon name="spark" size={16} /></span>
          <strong>Health is up 8%</strong>
          <p>Across all repositories this month.</p>
          <button onClick={() => setActiveNav('Reports')}>View insights <Icon name="arrow" size={14} /></button>
        </div>

        <div className="profile">
          <div className="avatar">AM</div>
          <div><strong>Alex Morgan</strong><span>@alexmorgan</span></div>
          <button aria-label="Sign out"><Icon name="logout" size={17} /></button>
        </div>
      </aside>

      <main className="main">
        <header className="topbar">
          <div className="mobile-brand"><span className="brand-mark"><Icon name="heart" size={17} /></span><strong>RepoHeal</strong></div>
          <div className="search-wrap">
            <Icon name="search" size={17} />
            <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search repositories..." aria-label="Search repositories" />
            <kbd>⌘ K</kbd>
          </div>
          <div className="top-actions">
            <span className="sync-status"><span /> All systems operational</span>
            <button className="icon-button" aria-label="Toggle appearance"><Icon name="moon" size={18} /></button>
            <button className="icon-button notification" aria-label="Notifications"><Icon name="alert" size={18} /><span /></button>
          </div>
        </header>

        <div className="content">
          <section className="page-heading">
            <div>
              <p className="eyebrow">Tuesday, June 18</p>
              <h1>{activeNav === 'Overview' ? 'Good morning, Alex.' : activeNav}</h1>
              <p>{activeNav === 'Overview' ? 'Here’s how your repositories are doing today.' : `Explore your ${activeNav.toLowerCase()} workspace and repository health.`}</p>
            </div>
            <div className="heading-actions">
              <button className="button secondary-button" onClick={refresh}><Icon name="refresh" className={refreshing ? 'spin' : ''} size={16} />{refreshing ? 'Refreshing…' : 'Refresh health'}</button>
              <button className="button primary-button" onClick={() => setActiveNav('Repositories')}><Icon name="github" size={17} /> Connect repository</button>
            </div>
          </section>

          <section className="metrics-grid" aria-label="Repository health summary">
            <article className="metric-card featured">
              <div className="metric-top"><span className="metric-icon mint"><Icon name="heart" size={18} /></span><span className="period">Last 30 days <Icon name="chevron" size={13} /></span></div>
              <div className="metric-value-row"><strong>86</strong><span className="score-unit">/100</span><span className="delta positive"><Icon name="trend" size={13} /> 8%</span></div>
              <p>Average health score</p>
              <Sparkline points={[59, 63, 61, 68, 70, 74, 72, 78, 82, 86]} />
            </article>
            <article className="metric-card">
              <div className="metric-top"><span className="metric-icon violet"><Icon name="code" size={18} /></span><button aria-label="Repository options"><Icon name="dots" size={18} /></button></div>
              <div className="metric-value-row"><strong>12</strong><span className="delta positive">+2 this month</span></div>
              <p>Active repositories</p>
              <div className="mini-progress"><span style={{ width: '72%' }} /></div>
              <small>9 analyzed this week</small>
            </article>
            <article className="metric-card">
              <div className="metric-top"><span className="metric-icon amber"><Icon name="alert" size={18} /></span><button aria-label="Issue options"><Icon name="dots" size={18} /></button></div>
              <div className="metric-value-row"><strong>15</strong><span className="delta negative">3 critical</span></div>
              <p>Open issues</p>
              <div className="issue-bars"><i /><i /><i /><i /><i /><i /><i /><i /></div>
              <small>5 resolved in the last 7 days</small>
            </article>
            <article className="metric-card">
              <div className="metric-top"><span className="metric-icon blue"><Icon name="clock" size={18} /></span><button aria-label="Analysis options"><Icon name="dots" size={18} /></button></div>
              <div className="metric-value-row"><strong>4m 12s</strong></div>
              <p>Average analysis time</p>
              <div className="analysis-line"><span><Icon name="trend" size={13} /> 18% faster</span><b>98 analyses</b></div>
            </article>
          </section>

          <section className="dashboard-grid">
            <div className="panel repositories-panel">
              <div className="panel-header">
                <div><h2>Repositories</h2><p>Latest health analysis across your workspace</p></div>
                <div className="filter-group">
                  {(['All', 'Healthy', 'Needs attention'] as const).map((value) => <button key={value} className={filter === value ? 'active' : ''} onClick={() => setFilter(value)}>{value === 'Needs attention' ? 'At risk' : value}</button>)}
                </div>
              </div>
              <div className="repo-table">
                <div className="table-head"><span>Repository</span><span>Health score</span><span>Last analysis</span><span>Status</span><span /></div>
                {filteredRepos.map((repo) => (
                  <div className="repo-row" key={repo.name}>
                    <div className="repo-name-cell">
                      <span className="repo-icon"><Icon name="code" size={17} /></span>
                      <div><button className="repo-name" onClick={() => setActiveNav('Repositories')}>{repo.name}</button><span><i style={{ background: repo.color }} />{repo.lang} · {repo.branch}</span></div>
                    </div>
                    <div className="health-cell">
                      <div className={`score-ring ${repo.score < 80 ? 'warning' : ''}`} style={{ '--score': `${repo.score * 3.6}deg` } as React.CSSProperties}><span>{repo.score}</span></div>
                      <span className={repo.delta > 0 ? 'up' : 'down'}>{repo.delta > 0 ? '+' : ''}{repo.delta}</span>
                      <Sparkline points={repo.trend} down={repo.delta < 0} />
                    </div>
                    <div className="analysis-cell"><strong>{repo.updated}</strong><span><Icon name="branch" size={12} />{repo.commit}</span></div>
                    <div><span className={`status-pill ${repo.status === 'Healthy' ? 'healthy' : 'attention'}`}><i />{repo.status}</span></div>
                    <button className="row-action" aria-label={`Open ${repo.name}`}><Icon name="chevron" size={17} /></button>
                  </div>
                ))}
                {filteredRepos.length === 0 && <div className="empty-state">No repositories match “{query}”.</div>}
              </div>
              <button className="view-all" onClick={() => setActiveNav('Repositories')}>View all repositories <Icon name="arrow" size={15} /></button>
            </div>

            <aside className="side-stack">
              <div className="panel risk-panel">
                <div className="panel-header compact"><div><h2>Needs attention</h2><p>Prioritized by impact</p></div><span className="count-badge">5</span></div>
                <div className="risk-item">
                  <span className="risk-severity critical"><Icon name="alert" size={15} /></span>
                  <div><strong>Critical dependency</strong><p>lodash 4.17.15 in <b>data-pipeline</b></p><span>High severity · CVE-2021-23337</span></div>
                  <Icon name="chevron" size={15} />
                </div>
                <div className="risk-item">
                  <span className="risk-severity moderate"><Icon name="branch" size={15} /></span>
                  <div><strong>Branch is drifting</strong><p><b>mobile-sdk</b> is 47 commits behind</p><span>Detected 3 hours ago</span></div>
                  <Icon name="chevron" size={15} />
                </div>
                <div className="risk-item">
                  <span className="risk-severity low"><Icon name="clock" size={15} /></span>
                  <div><strong>Stale dependency</strong><p>React is 2 major versions behind</p><span>Upgrade path available</span></div>
                  <Icon name="chevron" size={15} />
                </div>
                <button className="text-button" onClick={() => setActiveNav('Reports')}>Review all issues <Icon name="arrow" size={14} /></button>
              </div>

              <div className="panel monitoring-card">
                <div className="monitoring-heading"><span className="live-icon"><Icon name="activity" size={17} /></span><div><h2>Health monitoring</h2><p>Continuous checks every 6 hours</p></div><button className={`toggle ${watching ? 'on' : ''}`} onClick={() => setWatching(!watching)} aria-label="Toggle health monitoring"><span /></button></div>
                <div className="monitoring-stats">
                  <div><span>Last check</span><strong>{watching ? '12 min ago' : 'Paused'}</strong></div>
                  <div><span>Next check</span><strong>{watching ? 'in 5h 48m' : '—'}</strong></div>
                </div>
              </div>
            </aside>
          </section>

          <section className="activity-panel panel">
            <div className="panel-header">
              <div><h2>Recent activity</h2><p>Analysis and changes from the last 24 hours</p></div>
              <button className="button tertiary-button" onClick={() => setActiveNav('Reports')}>Open activity log</button>
            </div>
            <div className="activity-list">
              <div className="activity-item"><span className="activity-symbol success"><Icon name="check" size={15} /></span><div><p><b>Analysis completed</b> for <strong>api-gateway</strong></p><span>Health improved from 88 to 92</span></div><time>12 min ago</time></div>
              <div className="activity-item"><span className="activity-symbol purple"><Icon name="compare" size={15} /></span><div><p><b>Comparison report</b> generated for <strong>web-client</strong></p><span>main compared with release/v2.4</span></div><time>1 hr ago</time></div>
              <div className="activity-item"><span className="activity-symbol orange"><Icon name="alert" size={15} /></span><div><p><b>New vulnerability</b> detected in <strong>data-pipeline</strong></p><span>Dependency remediation is available</span></div><time>2 hrs ago</time></div>
            </div>
          </section>
        </div>
      </main>
    </div>
  )
}

export default App
