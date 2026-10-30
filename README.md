# RepoHeal

RepoHeal analyzes installed GitHub repositories, builds dependency graphs, and generates health reports without exposing internal workspace URLs in the user dashboard.
Link : https://repoheal.onrender.com/ (Note the render instance takes time to turn on and neo4j instances also run on free tier and might be asleep)

The public `/` route redirects browsers to `/auth/login-page`. Monitoring should
use `/healthz`, which performs live dependency checks and returns `healthy` only
when both MongoDB and Neo4j are connected; otherwise it returns `degraded` with
the affected dependency reported as `unavailable`. Dependency URLs and
credentials are never included in the response.

## Local frontend

The redesigned dashboard lives in `frontend/` and is built with Vite. Run:

```text
cd frontend
npm install
npm run build
```

The FastAPI application serves `frontend/dist` at `/dashboard` when it exists and falls back to the existing server-rendered dashboard when it does not. Render builds the frontend before starting Uvicorn.

The authenticated dashboard consumes `/dashboard/data` and the repository overview,
status SSE, graph, report, comparison, and diagnostics endpoints. Repository detail
views provide live metadata, analysis progress, graph filtering/path highlighting,
JSON/Markdown/PNG exports, and browser-local issue triage. Missing analysis history,
Neo4j, or report snapshots are shown as unavailable states rather than replaced with
preview metrics.

## Neo4j Aura setup

1. Create a free Neo4j AuraDB instance at https://console.neo4j.io/.
2. Create or select a database, then copy its connection URI, username, and generated password.
3. Add these Render environment variables to the RepoHeal service:
   - `NEO4J_URI`: the Aura URI, usually `neo4j+s://...`
   - `NEO4J_USERNAME`: usually `neo4j`
   - `NEO4J_PASSWORD`: the generated database password
4. Restart or redeploy the service. Check `/healthz`; the response should report Neo4j as available.

Aura free instances may pause when idle. Start or resume the instance in the Aura console before testing graph visualization. Never commit the Aura password or URI to the repository.
## Dashboard

The dashboard shows installed repositories with:

- Last Analysis
- Last Health Refresh
- Current HEAD
- Last Analyzed
- Status
- Visualize Graph
- View Reports
- Compare Analyses

Repository cards do not display workspace URLs or internal metadata endpoints.

The JSON dashboard response includes aggregate metrics plus per-repository health
and analysis fields. Report exports are available at
`/reports/{owner}/{repo}/export?format=json|markdown`; graph JSON is served by
`/graph/{owner}/{repo}` and server-rendered PNG export by
`/visualize/{owner}/{repo}/export.png`.

## Analysis Workflows

Analyze supports three modes:

- Latest Commit: analyzes the latest commit on the repository default branch.
- Specific Branch: analyzes HEAD for the selected branch, such as `main`, `develop`, `feature/*`, or `release/*`.
- Specific Commit: analyzes an exact commit SHA.

Analysis and health report regeneration accept a branch and optional commit SHA. New runs are stored as separate records and do not overwrite historical results.

## Metadata Storage

RepoHeal stores generated metadata on a single branch:

```text
repoheal.meta/
  metadata.json
  analyses/
    main/
      analysis_<commit>.json
  health_reports/
    main/
      health_<commit>.json
  comparisons/
  migration_reports/
  snapshots/
```

Analysis runs and health reports never create new Git branches. Branches are only created for actual source-code changes and use the `repoheal.changes.<plan>` prefix.

## Records

Analysis records include repository, branch, commit SHA, timestamp, analysis version, health score, dependency count, risk level, and report path.

Health report records include repository, branch, commit SHA, generation timestamp, health score, issues, and recommendations.

## Comparisons

Compare Analyses accepts Branch A + Commit A and Branch B + Commit B, then stores results under `repoheal.meta/comparisons/`. The comparison includes dependency additions/removals, health score changes, risk level changes, breaking API changes, and migration readiness changes.
