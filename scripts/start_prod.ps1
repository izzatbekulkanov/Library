Param(
    [string]$Host = "0.0.0.0",
    [int]$Port = 8000,
    [int]$Workers = 2
)

$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

if (Test-Path ".env") {
    $lines = Get-Content ".env"
    foreach ($lineRaw in $lines) {
        $line = $lineRaw.Trim()
        if (-not $line -or $line.StartsWith("#")) { continue }
        $pair = $line -split "=", 2
        if ($pair.Count -eq 2) {
            [System.Environment]::SetEnvironmentVariable($pair[0].Trim(), $pair[1].Trim())
        }
    }
}

if (-not $env:APP_ENV) { $env:APP_ENV = "production" }
if ($env:APP_HOST) { $Host = $env:APP_HOST }
if ($env:APP_PORT) { $Port = [int]$env:APP_PORT }
if ($env:APP_WORKERS) { $Workers = [int]$env:APP_WORKERS }

if (-not (Test-Path ".venv\\Scripts\\python.exe")) {
    Write-Error ".venv topilmadi. Avval virtualenv yarating."
    exit 1
}

& ".venv\\Scripts\\python.exe" -m uvicorn app.main:app --host $Host --port $Port --workers $Workers
