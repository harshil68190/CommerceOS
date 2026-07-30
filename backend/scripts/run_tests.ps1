param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$PytestArgs
)

$ErrorActionPreference = "Stop"
$env:COMMERCEOS_ENV_FILE = ".env.test"

if (-not (Test-Path ".env.test")) {
    throw "Missing .env.test. Configure the test environment first."
}

& .\.venv\Scripts\python.exe -m pytest @PytestArgs
exit $LASTEXITCODE
