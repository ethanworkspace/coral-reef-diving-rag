param(
    [switch]$EnableReefCheckLocalResearch
)

$ErrorActionPreference = 'Stop'

$projectRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $projectRoot '.venv\Scripts\python.exe'
$runtimeRoot = Join-Path $projectRoot 'data\runtime\research'
$structuredDb = Join-Path $runtimeRoot 'marine_research.sqlite'
$ragDb = Join-Path $runtimeRoot 'rag.sqlite'

if (-not (Test-Path -LiteralPath $python)) {
    throw 'Local Python runtime is unavailable. The existing research service was not changed.'
}

$portInUse = @(& netstat.exe -ano -p TCP | Select-String -Pattern '^\s*TCP\s+127\.0\.0\.1:8081\s+.*\s+LISTENING\s+[0-9]+\s*$')
if ($portInUse.Count -gt 0) {
    throw 'Local research port 8081 is already in use. Nothing was stopped or replaced.'
}

& $python -m coral_rag verify-raw-data --check-only
if ($LASTEXITCODE -ne 0) {
    throw 'Raw-data verification did not pass. Existing services and databases were not changed.'
}

& $python -m coral_rag build-structured --structured-db $structuredDb
if ($LASTEXITCODE -ne 0) {
    throw 'Research structured build failed. Existing services and databases were not changed.'
}

& $python -m coral_rag ingest --root data/raw --rag-db $ragDb
if ($LASTEXITCODE -ne 0) {
    throw 'Research FTS build failed. Existing services and databases were not changed.'
}

$env:CORAL_RAG_STRUCTURED_DB = $structuredDb
$env:CORAL_RAG_RAG_DB = $ragDb
if ($EnableReefCheckLocalResearch) {
    Write-Host 'Reef Check output is enabled only for this local, non-commercial research process under CC BY-NC 4.0. It must not be used for public deployment or commercial use.'
    $env:REEFCHECK_LOCAL_NONCOMMERCIAL_RESEARCH_MODE = 'enabled'
}
& $python -m uvicorn coral_rag.web:app --host 127.0.0.1 --port 8081
