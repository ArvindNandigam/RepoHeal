$ErrorActionPreference = 'Stop'

Write-Host 'Running backend tests…'
python -m pytest -q
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host 'Checking frontend TypeScript…'
npm run typecheck --prefix frontend
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host 'Building frontend…'
npm run build --prefix frontend
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host 'All local verification steps passed.'
