$ErrorActionPreference = 'Stop'

$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) { $python = Get-Command py -ErrorAction SilentlyContinue }

if ($python) {
    & $python.Source "$PSScriptRoot\server.py"
    exit
}

$codexPython = Join-Path $HOME '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
if (Test-Path $codexPython) {
    & $codexPython "$PSScriptRoot\server.py"
    exit
}

Write-Host 'Python 3 não foi encontrado. Instale-o em https://www.python.org/downloads/' -ForegroundColor Yellow
Read-Host 'Pressione Enter para fechar'
