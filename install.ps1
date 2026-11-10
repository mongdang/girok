# girok bootstrap for a new Windows PC.
#
#   irm https://raw.githubusercontent.com/mongdang/girok/master/install.ps1 | iex
#
# Installs what is missing - git, Python 3.10+, Claude Code - and then the
# girok plugin. Whatever is already there is left alone.
#
# This is a script and not part of the plugin because the plugin cannot do
# it: `claude plugin marketplace add` needs git before the plugin exists on
# the machine, and installing a plugin runs none of its code.
#
# Messages stay ASCII. Windows PowerShell 5.1 reads a script without a BOM
# in the ANSI codepage, and a Korean console would show UTF-8 as mojibake
# at the one moment the text matters.
#
# -DryRun says what would be installed and installs nothing.
param([switch]$DryRun)

$ErrorActionPreference = 'Stop'

function Say($text) { Write-Host "[girok] $text" }

function Update-SessionPath {
    # An installer changes the registry PATH, not this process's copy.
    $env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' +
                [Environment]::GetEnvironmentVariable('Path', 'User')
}

function Test-Command($name) {
    return [bool](Get-Command $name -ErrorAction SilentlyContinue)
}

function Test-Python {
    # Run it, do not just resolve the name: `python` on a fresh Windows is
    # the Microsoft Store alias, which resolves and is not an interpreter.
    # The hook wrapper tries `python` then `py -3`, so the same two here.
    $check = 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)'
    foreach ($candidate in @(@('python'), @('py', '-3'))) {
        $exe = $candidate[0]
        if (-not (Test-Command $exe)) { continue }
        $rest = @($candidate | Select-Object -Skip 1) + @('-c', $check)
        try { & $exe @rest 2>$null | Out-Null } catch { continue }
        if ($LASTEXITCODE -eq 0) { return $true }
    }
    return $false
}

function Install-WithWinget($id, $label) {
    if ($DryRun) { Say "would install $label (winget $id)"; return }
    if (-not (Test-Command 'winget')) {
        throw "winget is not available, so $label cannot be installed automatically. Install it by hand and run this again."
    }
    Say "installing $label ..."
    winget install -e --id $id --accept-package-agreements --accept-source-agreements
    if ($LASTEXITCODE -ne 0) { throw "winget could not install $label (exit $LASTEXITCODE)." }
    Update-SessionPath
}

Update-SessionPath

if (Test-Command 'git') { Say 'git: found' }
else { Install-WithWinget 'Git.Git' 'git' }

if (Test-Python) { Say 'Python 3.10+: found' }
else { Install-WithWinget 'Python.Python.3.13' 'Python 3.13' }

if (Test-Command 'claude') { Say 'Claude Code: found' }
elseif ($DryRun) { Say 'would install Claude Code (https://claude.ai/install.ps1)' }
else {
    Say 'installing Claude Code ...'
    Invoke-RestMethod https://claude.ai/install.ps1 | Invoke-Expression
    Update-SessionPath
}

if ($DryRun) { Say 'would add the marketplace mongdang/girok and install girok@mongdang'; return }

# Verified after installing rather than assumed: an installer that finished
# without putting its program on PATH leaves hooks that find nothing.
$missing = @()
if (-not (Test-Command 'git')) { $missing += 'git' }
if (-not (Test-Python)) { $missing += 'Python 3.10+' }
if (-not (Test-Command 'claude')) { $missing += 'Claude Code' }
if ($missing.Count -gt 0) {
    throw "installed, but not on PATH yet: $($missing -join ', '). Open a new terminal and run this again."
}

# `add` and `install` fail when already done; `update` then brings an
# existing copy to the current version. Only the last state is checked.
# The scope is named: run inside a repository that has its own project-scope
# install, a bare `update` moved that one and left the machine-wide copy old.
$ErrorActionPreference = 'Continue'
claude plugin marketplace add mongdang/girok 2>$null | Out-Null
claude plugin marketplace update mongdang | Out-Null
claude plugin install girok@mongdang --scope user 2>$null | Out-Null
claude plugin update girok@mongdang --scope user | Out-Null
$ErrorActionPreference = 'Stop'

$listed = (claude plugin list | Out-String)
if ($listed -notmatch 'girok@mongdang') { throw 'the girok plugin did not install. Run: claude plugin install girok@mongdang' }

Say 'done.'
Say 'next: open a NEW terminal, cd into your repository, run `claude`, then type /notes'
