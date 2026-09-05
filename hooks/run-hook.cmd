: << 'CMDBLOCK'
@echo off
REM Cross-platform polyglot wrapper for the hook scripts.
REM On Windows cmd.exe runs the batch half; on Unix the shell reads past it
REM (a leading ':' is a no-op) and runs the tail.
REM
REM Everything here is Python, so Python is the only runtime a machine needs
REM besides git -- no bash, no PowerShell.
REM
REM Candidates are probed by actually running them, not by asking whether
REM the name resolves. On Windows `python3` usually resolves to the
REM Microsoft Store app execution alias, which is not an interpreter: it
REM prints "Python" and exits 49. Picking it would leave the hooks silently
REM dead on a machine that has Python installed.
REM
REM Usage: run-hook.cmd <script-name>   (without the .py extension)

if "%~1"=="" (
    echo [girok] run-hook.cmd: missing script name >&2
    exit /b 1
)

set "HOOK_DIR=%~dp0"
set "HOOK_SCRIPT=%HOOK_DIR%%~1.py"

py -3 -c "import sys; sys.exit(0 if sys.version_info>=(3,10) else 1)" >nul 2>nul
if %ERRORLEVEL% equ 0 (
    py -3 "%HOOK_SCRIPT%" %2 %3 %4 %5 %6 %7 %8 %9
    exit /b %ERRORLEVEL%
)

python -c "import sys; sys.exit(0 if sys.version_info>=(3,10) else 1)" >nul 2>nul
if %ERRORLEVEL% equ 0 (
    python "%HOOK_SCRIPT%" %2 %3 %4 %5 %6 %7 %8 %9
    exit /b %ERRORLEVEL%
)

REM No usable Python. Say so instead of exiting quietly: a session that
REM looks supervised and is not is the failure this whole design is against.
REM The CLAUDE.md gate is the real backstop -- without the readiness marker
REM the session stops on its own.
REM These lines stay ASCII: a Korean Windows console is cp949 and would
REM render UTF-8 text as mojibake, at the exact moment it matters most.
echo [girok] No usable Python 3.10+: hooks are NOT running and no rule >&2
echo [girok] check is being applied. Install Python and restart the session. >&2
exit /b 0
CMDBLOCK

# Unix
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SCRIPT_NAME="$1"
shift

for candidate in python3 python py; do
    command -v "$candidate" >/dev/null 2>&1 || continue
    "$candidate" -c 'import sys; sys.exit(0 if sys.version_info>=(3,10) else 1)' >/dev/null 2>&1 || continue
    exec "$candidate" "${SCRIPT_DIR}/${SCRIPT_NAME}.py" "$@"
done

echo "[girok] No usable Python 3.10+: hooks are NOT running. Install Python and restart." >&2
exit 0
