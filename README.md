# RepoHeal

RepoHeal is a GitHub-connected repository analysis service for inspecting Python code health, dependency usage, and migration risk. It analyzes a repository at a selected branch head or commit, stores versioned analysis artifacts, builds a dependency and code relationship graph, and presents health and migration reports in an authenticated dashboard.

**Install the GitHub App:** [github.com/apps/repoheal](https://github.com/apps/repoheal)

**Open the live dashboard:** [repoheal.onrender.com](https://repoheal.onrender.com/) (the free-tier service and database may need time to wake up.)

To try RepoHeal, install the GitHub App on the repositories you want to analyze, then sign in to the live dashboard with GitHub. The app needs repository access, and the dashboard only lists repositories that your account can access and that have the RepoHeal App installed.

## What it does

- Connects GitHub OAuth user access with GitHub App installation access to discover and read installed repositories.
- Scans Python source with AST-based import and symbol analysis, and reads dependency declarations from common Python packaging files such as `requirements.txt`, `pyproject.toml`, `Pipfile`, `setup.cfg`, and `setup.py`.
- Compares imports with declared dependencies, looks up package versions on PyPI, and creates fingerprints for library API usage.
- Builds a repository graph with file, package, function, class, and relationship nodes. Neo4j is used for graph storage when available; a graph can also be generated from cached analysis artifacts.
- Produces health scores, dependency inventory, migration risk findings, recommendations, and a Markdown migration document. External symbol intelligence is provided through the configured Restricted Webtool service, with local/version-gap checks used as fallback signals where possible. Reports retain an intelligence status so unavailable external data is visible.
- Saves branch- and commit-specific analysis history and supports comparisons between saved analyses.
- Streams analysis progress with Server-Sent Events and supports repository monitoring, watchlists, alerts, and scheduled checks.

The analysis is advisory. A clean report means the configured checks found no actionable issues; it does not prove that every API or migration risk was verified, especially when external intelligence is unavailable.

## Stack

| Area | Technology |
| --- | --- |
| API and workers | Python, FastAPI, Pydantic, Uvicorn, FastAPI background tasks |
| Dashboard | React, TypeScript, Vite |
| Code analysis | Python `ast`, dependency manifest parsers, PyGithub |
| Persistence | MongoDB for sessions, job state, monitoring data, and platform metrics; `repoheal.meta` Git branch for durable analysis/report artifacts |
| Graph | Neo4j with a cached-analysis graph fallback |
| Integrations | GitHub OAuth, GitHub App, PyPI, Restricted Webtool; optional LLM-backed remediation configuration |
| Deployment | Render |

See [Architecture](docs/ARCHITECTURE.md) for data flow, storage boundaries, and API surfaces.
See [Testing and demo workflow](docs/TESTING.md) for local verification, staging checks, and a recording checklist.

GitHub Actions runs the backend checks and frontend typecheck/production build on pushes and pull requests targeting `main`.

## Analysis workflow

1. A user signs in with GitHub and selects a repository available to the RepoHeal GitHub App installation.
2. From the repository page, select a branch. The commit field suggests the latest 50 commits and also accepts a pasted 7–40 character hexadecimal SHA. Leave it blank to analyze the selected branch head; enter a SHA to analyze that exact commit.
3. RepoHeal queues a background job, fetches the selected repository snapshot, scans Python files and dependency manifests, and records progress in MongoDB.
4. The analyzer generates dependency and symbol data. The graph builder attempts to write graph data to Neo4j; metadata artifacts are persisted on the `repoheal.meta` branch.
5. The migration pipeline first calculates and saves a preliminary health score from local code and dependency findings. It then queries external symbol intelligence in bounded parallel batches, enriches the score and risk findings, and writes the migration document. A provider timeout does not block the preliminary score from appearing.
6. The dashboard loads graph data, reports, and history from the saved artifacts. A saved analysis can be compared with another analysis.

On the repository page, **Analyze repository** scans the selected branch or commit and runs the full pipeline, including health and migration reports. **Refresh health & migration** reuses the latest saved code analysis and reruns report generation without rescanning repository files. Both actions show the current task, progress percentage, and worker message; the page receives live updates and polls status as a recovery path if the event stream disconnects. Health refresh requires a saved analysis.

Health scoring uses local dependency and code findings first, so the dashboard can show a score while external API intelligence is still running. External enrichment is requested in small bounded parallel batches; each HTTP request has a 300-second timeout, and duplicate in-flight requests are coalesced. If the provider times out, the saved report retains its local score and indicates that migration intelligence is unavailable or degraded.

The Reports page displays the active task type, progress percentage, and latest worker message. It reloads saved report data when the preliminary score is persisted and when the task finishes. The dependency graph supports filters for files, packages, functions, classes, and APIs; PNG export places graph nodes without a repository-root path in a fallback row so they remain renderable.

The exact mode and target are passed to the analysis API. Use a branch head for an up-to-date view, or select a commit to inspect historical code. Rerunning an analysis creates a new saved record; it does not intentionally overwrite the prior history entry.

## Local development

### Prerequisites

- Python 3.11 or newer (the deployment currently uses the Python runtime configured by Render)
- Node.js and npm
- MongoDB
- A GitHub OAuth app and GitHub App installation for authenticated repository access
- Neo4j for live graph persistence; cached graph rendering can be used as a fallback

### Install and build the dashboard

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
npm install --prefix frontend
npm run build --prefix frontend
```

The FastAPI service serves `frontend/dist` at `/dashboard` when the build exists. During frontend work, run `npm run dev --prefix frontend`; configure the Vite development server to proxy API requests to the FastAPI service if needed.

### Configure environment

Create an untracked `.env` file for local development. Configure the credentials for the services you intend to use; do not put secrets in Git.

| Variable | Purpose |
| --- | --- |
| `GITHUB_OAUTH_CLIENT_ID`, `GITHUB_OAUTH_CLIENT_SECRET` | GitHub user login |
| `GITHUB_APP_ID`, `GITHUB_PRIVATE_KEY`, `GITHUB_WEBHOOK_SECRET` | GitHub App installation and webhook integration |
| `GITHUB_TOKEN_ENCRYPTION_KEY`, `JWT_SECRET_KEY` | Session/token protection; required in production |
| `MONGODB_URI`, `MONGODB_DATABASE` | Persistent job, session, monitoring, and metrics data (`RepoHeal` is the default database name) |
| `NEO4J_URI`, `NEO4J_USERNAME`, `NEO4J_PASSWORD` | Neo4j graph storage |
| `WEBTOOL_API_URL`, `INTERNAL_API_KEY` | Restricted Webtool intelligence service |
| `LLM_PROVIDER`, `LLM_MODEL`, `LLM_API_KEY` | Optional LLM-backed remediation features |
| `MAX_CACHE_SIZE_MB`, `MAX_ANALYSIS_HISTORY`, `CACHE_RETENTION_DAYS` | Local cache retention limits |

The full settings list and defaults are in [`app/config.py`](app/config.py). Production requires `JWT_SECRET_KEY` and `GITHUB_TOKEN_ENCRYPTION_KEY`; the service also needs working GitHub and MongoDB configuration to provide authenticated repository analysis. Never publish actual values in documentation or logs.

### Start the API

```powershell
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

OAuth callback URLs and GitHub App webhooks must match the URL configured for your GitHub applications. The deployed OAuth flow currently uses the public RepoHeal host, so local sign-in may require a separately configured callback or development tunnel.

## Useful endpoints

Most repository endpoints require an authenticated session and repository access.

| Endpoint | Purpose |
| --- | --- |
| `GET /healthz` | Live service and dependency diagnostics |
| `GET /dashboard/data` | Authenticated repository list and dashboard metrics |
| `GET /repos/{owner}/{repo}/branches` | Branch choices for analysis |
| `GET /repos/{owner}/{repo}/commits?branch={branch}` | Recent commits for a branch |
| `GET /analyze/{owner}/{repo}?mode=branch&branch={branch}` | Queue analysis for a branch head |
| `GET /analyze/{owner}/{repo}?mode=commit&branch={branch}&commit_sha={sha}` | Queue analysis for a specific commit |
| `POST /health-refresh/{owner}/{repo}` | Rebuild health and migration reports from a saved analysis without rescanning source files |
| `POST /reanalyze/{owner}/{repo}` | Queue a forced full analysis run |
| `GET /graph/{owner}/{repo}` | Latest dependency/code graph |
| `GET /visualize/{owner}/{repo}/export.png` | Export the latest graph as a PNG image |
| `GET /sse/status/{owner}/{repo}` | Server-Sent Events analysis progress stream |
| `GET /status/{owner}/{repo}` | Current job progress and code-state status |
| `GET /reports/{owner}/{repo}/health` | Latest saved health report |
| `GET /reports/{owner}/{repo}/migration` | Latest saved migration document |
| `GET /reports/{owner}/{repo}/history` | Saved analysis history |
| `GET /reports/{owner}/{repo}/compare` | Compare saved analysis records |
| `GET /reports/{owner}/{repo}/export?format=markdown` | Export a health report |

The complete route list is available from FastAPI's OpenAPI page at `/docs` when the service is running.

## Data and operations

- MongoDB stores sessions, job state, monitoring configuration/history, and persisted platform metrics.
- The GitHub `repoheal.meta` branch stores durable analysis snapshots, graph snapshots, manifests, health reports, and migration documents.
- `.repoheal_cache/` is local working/cache data. On ephemeral hosts, it should not be treated as the sole durable source of analysis artifacts.
- The admin metrics page reports persisted metrics and live MongoDB/Neo4j connectivity. A zero or missing metric should be interpreted in light of its collection status.
- `HEAD /healthz` is suitable for basic uptime checks. `GET /healthz` performs live dependency checks; a reachable web process can return a degraded status if a database is unavailable.
- On Render, the service runs Uvicorn on the platform-provided `$PORT`. `render.yaml` builds the frontend and installs Python dependencies before starting the API.

## Resume-ready project description

**RepoHeal — GitHub Repository Health & Migration Analysis Platform**

Built a full-stack service that analyzes Python repositories at selected branches and commits, detects dependency and API risks, generates health and migration reports, and visualizes code/dependency relationships. Implemented a FastAPI/React dashboard, asynchronous analysis progress, GitHub App integration, MongoDB job and monitoring persistence, Neo4j graph storage with cached-analysis fallback, and versioned analysis/report history on a dedicated Git metadata branch.

For a resume, add only measurements you can verify from production logs or a repeatable benchmark (for example: repositories analyzed, scan time, graph node counts, or report-generation latency). Avoid presenting configured limits or demo data as measured impact.
