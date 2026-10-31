# Testing and demo workflow

RepoHeal has checks at three levels. The local suite is designed to run without GitHub, MongoDB, Neo4j, or the external intelligence provider. A separate staging smoke test verifies those integrations together before recording a product demo.

## Run the local verification suite

From the repository root in PowerShell:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\scripts\verify.ps1
```

The script runs:

1. `python -m pytest -q` — backend unit and mocked API tests.
2. `npm run typecheck --prefix frontend` — TypeScript type checking.
3. `npm run build --prefix frontend` — production dashboard build.

GitHub Actions also runs Ruff and a repository-wide mypy audit. Ruff is a blocking check. The mypy audit is currently non-blocking while existing annotation and third-party stub issues are cleaned up; it remains visible in the Actions log.

You can run each step independently. The backend tests use fake collections, mock GitHub/Neo4j clients, and local in-memory source fixtures. They do not prove that production credentials, network services, GitHub permissions, or the deployed Render service work.

## What the local suite covers

- Job creation, deduplication, and repository status behavior.
- Branch and exact commit target resolution.
- Offline Python AST/dependency analysis with a deterministic in-memory fixture and mocked PyPI versions.
- Local health scoring without external intelligence, bounded concurrent Webtool batches, and analysis progress recovery.
- Graph generation from analysis data, including the saved dependency-only fallback, package-type promotion, and PNG rendering of orphaned nodes.
- Report generation, migration artifact persistence, comparison, Markdown export, and repository authorization.
- Dashboard/admin/health route behavior and configuration checks.

When a bug is fixed, add a regression test at the narrowest layer that reproduces it. Keep unit tests independent of credentials and external network calls.

## Staging end-to-end checklist

Use a disposable GitHub repository with no sensitive source and a staging deployment. Install the RepoHeal GitHub App on that repository, sign into the staging dashboard, and configure the staging MongoDB, Neo4j, and Restricted Webtool services.

1. Open the repository and verify the branch list loads.
2. Select a non-default branch, leave the commit SHA blank, and queue an analysis. Verify the progress stream reaches a terminal status and the saved analysis identifies the chosen branch and commit.
3. Paste a known commit SHA and run another analysis. Verify the new report/history entry uses that exact SHA.
4. While external intelligence is pending, open Reports. Verify the preliminary health score appears before the lookup finishes and the active task message and percentage are visible. Confirm the final enriched report reloads when the task completes.
5. Use **Refresh health & migration**. Verify that the task is labeled as a health/migration refresh, displays its progress percentage and worker message, and completes without rescanning source files. Confirm it is disabled before any analysis exists.
6. Open the graph. Confirm the API returns nodes/edges and the UI shows the same counts. Check that package and class filters include their matching nodes, including saved package nodes. Repeat with Neo4j unavailable to confirm the saved-analysis fallback works when cache/artifacts are available. Export a PNG and confirm nodes with missing parent links still render.
7. Open the health report and migration document. Confirm the analysis ID and commit match the run, and check that external intelligence availability is clearly reported.
8. Open analysis history and compare two saved runs.
9. Check the service logs and MongoDB job record for failures; confirm the source branch has not been modified. Analysis artifacts are written to the `repoheal.meta` metadata branch.

For progress recovery, disconnect or block the SSE request while a job runs. Verify that the ten-second status poll still updates task progress and reloads repository details after completion. Confirm the top bar offers Log out and has no Change account action.

For Admin reset behavior, verify the counters return to zero and `Last reset` updates. Confirm old job, report, alert, and monitoring records remain available.

Do not use a personal production repository for this checklist: each analysis can write history artifacts to the repository's metadata branch. Keep secrets and private repository details out of captured video.

## Recording a GitHub demo

Record only after the staging checklist passes. A short 45–75 second walkthrough can show:

1. RepoHeal sign-in and the disposable demo repository.
2. Selecting a branch and entering a commit SHA.
3. Analysis progress reaching completion.
4. The resulting health/migration summary and relationship graph.
5. A second history entry or comparison to show commit-aware history.

Use a clean browser profile with no personal tabs, tokens, or private repository names visible. Prefer a short animated GIF for inline README playback and keep a higher-quality MP4 as a GitHub Release or linked demo asset. Label the recording as a staging demo; do not imply the displayed sample values are platform-wide production metrics.

## Current baseline

Local verification on 2026-10-31: **45 backend tests passed**, frontend TypeScript typecheck passed, Vite production build passed, and Ruff passed. The run emitted two dependency deprecation warnings (Starlette's `TestClient`/httpx integration and `astor`'s use of deprecated `ast.Num`); neither caused a failure. The broad mypy audit remains non-blocking and reports existing annotation/stub errors in package normalization, AST transforms, dependency parsing, and graph visualization.

Treat live integration checks as a separate result and include the staging date, tested branch/commit, and service configuration class (for example, Neo4j available/unavailable), never secret values.
