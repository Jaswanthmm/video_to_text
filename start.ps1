$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$sessionPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $sessionPython)) {
    throw 'Create the Python environment using the instructions in README.md first.'
}
& $sessionPython -m streamlit run app.py
