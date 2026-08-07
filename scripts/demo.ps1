$ErrorActionPreference = "Stop"

function Invoke-Candle([string[]]$Arguments) {
    if ($env:CANDLE_CLI_BIN) {
        & $env:CANDLE_CLI_BIN @Arguments
    } else {
        cargo run --quiet -- @Arguments
    }
    if ($LASTEXITCODE -ne 0) {
        throw "candle-cli command failed: $($Arguments -join ' ')"
    }
}

Write-Host "[1/5] environment"
Invoke-Candle @("doctor")
Write-Host "[2/5] API mapping evidence"
Invoke-Candle @("migrate", "map", "torch.add", "--pretty")
Write-Host "[3/5] static migration scan"
Invoke-Candle @("migrate", "scan", "examples/migration_demo", "--pretty")
Write-Host "[4/5] deterministic patch preview (source is not modified)"
Invoke-Candle @("migrate", "rewrite", "examples/migration_demo", "--pretty")
Write-Host "[5/5] frozen security heldout"
Invoke-Candle @("security-heldout")
