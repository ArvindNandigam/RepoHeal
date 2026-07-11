# RepoHeal

RepoHeal analyzes installed GitHub repositories, builds dependency graphs, and generates health reports without exposing internal workspace URLs in the user dashboard.
Link : https://repoheal.onrender.com/ (Note the render instance takes time to turn on and neo4j instances also run on free tier aqnd might be asleep)
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
