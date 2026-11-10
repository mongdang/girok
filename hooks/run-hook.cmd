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
REM Each candidate is launched once. run_hook.py checks the version and,
REM when it is 3.10+, runs the script in that same process; too old is
REM exit 113. A separate probe launch doubled the cost of every hook, and
REM on a machine where each process start takes seconds that alone blew
REM the hook's time budget. `python` comes before `py` for the same
REM reason: the launcher is one more process.
REM
REM Usage: run-hook.cmd <script-name>   (without the .py extension)

if "%~1"=="" (
    echo [girok] run-hook.cmd: missing script name >&2
    exit /b 1
)

set "HOOK_DIR=%~dp0"
set "HOOK_SCRIPT=%HOOK_DIR%%~1.py"
set "BOOT=%HOOK_DIR%run_hook.py"

REM %%~$PATH:I looks the name up on PATH without starting a process.
for %%I in (python.exe) do if "%%~$PATH:I"=="" goto :try_py
python "%BOOT%" "%HOOK_SCRIPT%" %2 %3 %4 %5 %6 %7 %8 %9
if %ERRORLEVEL% equ 49 goto :try_py
if %ERRORLEVEL% equ 113 goto :try_py
exit /b %ERRORLEVEL%

:try_py
for %%I in (py.exe) do if "%%~$PATH:I"=="" goto :no_python
py -3 "%BOOT%" "%HOOK_SCRIPT%" %2 %3 %4 %5 %6 %7 %8 %9
if %ERRORLEVEL% equ 49 goto :no_python
if %ERRORLEVEL% equ 113 goto :no_python
exit /b %ERRORLEVEL%

:no_python
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
# No dirname, no subshell: each would be one more process, and process
# starts are what this wrapper is saving. The registration always passes
# a path with a directory in it - with slashes from `git rev-parse`, but
# a Windows caller may hand bash a backslash path, so both separators
# are handled.
bs='\'
case "$0" in
    */*) SCRIPT_DIR="${0%/*}" ;;
    *"$bs"*) SCRIPT_DIR="${0%"$bs"*}" ;;
    *) SCRIPT_DIR="." ;;
esac
SCRIPT_NAME="$1"
shift

for candidate in python3 python py; do
    command -v "$candidate" >/dev/null 2>&1 || continue
    "$candidate" "${SCRIPT_DIR}/run_hook.py" "${SCRIPT_DIR}/${SCRIPT_NAME}.py" "$@"
    rc=$?
    # 49: the Store alias. 113: too old. 126/127/9009: not runnable at all.
    case "$rc" in 49|113|126|127|9009) continue ;; esac
    exit "$rc"
done

echo "[girok] No usable Python 3.10+: hooks are NOT running. Install Python and restart." >&2
exit 0
