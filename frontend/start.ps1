$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$nodeCommand = Get-Command node -ErrorAction SilentlyContinue
if ($nodeCommand) {
    $stevensNode = $nodeCommand.Source
} else {
    $stevensNode = Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe'
}
if (-not (Test-Path -LiteralPath $stevensNode)) {
    throw 'Node.js 22.12+ is required. Install Node.js and reopen the VS Code terminal.'
}
if (-not (Test-Path -LiteralPath 'node_modules\vite\bin\vite.js')) {
    throw 'Dependencies are missing. Run npm install in the frontend directory first.'
}
& $stevensNode 'node_modules/vite/bin/vite.js' '--host' '127.0.0.1'
exit $LASTEXITCODE
