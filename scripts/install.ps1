param(
    [switch]$InstallPythonDependencies
)

$ErrorActionPreference = "Stop"

if (-not (Get-Command cargo -ErrorAction SilentlyContinue)) {
    throw "cargo is required; install Rust stable from https://rustup.rs"
}

cargo install --path . --locked
if ($LASTEXITCODE -ne 0) {
    throw "cargo install failed"
}

if ($InstallPythonDependencies) {
    $Python = if ($env:CANDLE_CLI_PYTHON) { $env:CANDLE_CLI_PYTHON } else { "python" }
    & $Python -m pip install -r requirements.txt
    if ($LASTEXITCODE -ne 0) {
        throw "Python dependency installation failed"
    }
}

Write-Host "installed candle-cli; run: candle-cli doctor"
