"""The polyglot wrapper.

Two things it must get right, and both were wrong at first:

- pick an interpreter that actually runs. On Windows `python3` normally
  resolves to the Microsoft Store app execution alias, which prints
  "Python" and exits 49 — resolving a name is not the same as finding an
  interpreter, and picking that one leaves the hooks silently dead on a
  machine that has Python installed.
- when there is no usable Python, say so. Exiting quietly would leave a
  session that looks supervised and is not.
"""
import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

WRAPPER = Path(__file__).resolve().parent.parent / "hooks" / "run-hook.cmd"

bash = shutil.which("bash")
needs_bash = pytest.mark.skipif(bash is None, reason="bash로 unix 절반을 실행할 수 없음")


def run_wrapper(script: str, env: dict | None = None, stdin: str = "{}"):
    return subprocess.run(
        [bash, str(WRAPPER), script],
        input=stdin,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env={**os.environ, **(env or {})},
    )


def _fake_bin(tmp_path: Path, names: dict[str, str]) -> Path:
    """A PATH directory holding stand-ins for the interpreters."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name, body in names.items():
        script = bin_dir / name
        script.write_text(body, encoding="utf-8", newline="\n")
        script.chmod(script.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return bin_dir


@needs_bash
def test_runs_the_hook_with_a_real_interpreter(tmp_path):
    result = run_wrapper("session-start", stdin='{"cwd": "%s"}' % tmp_path.as_posix())

    assert result.returncode == 0


@needs_bash
def test_skips_a_stub_that_resolves_but_is_not_an_interpreter(tmp_path):
    """The Microsoft Store alias, reproduced: on PATH, prints Python, exits
    49. The wrapper has to walk past it to the real one."""
    real = shutil.which("python") or shutil.which("python3")
    bin_dir = _fake_bin(
        tmp_path,
        {
            "python3": '#!/bin/sh\necho Python >&2\nexit 49\n',
            "python": f'#!/bin/sh\nexec "{real}" "$@"\n',
        },
    )

    result = run_wrapper(
        "session-start",
        env={"PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}"},
        stdin='{"cwd": "%s"}' % tmp_path.as_posix(),
    )

    assert result.returncode == 0
    assert "exit 49" not in result.stderr


@needs_bash
def test_says_so_loudly_when_there_is_no_usable_python(tmp_path):
    bin_dir = _fake_bin(
        tmp_path,
        {
            "python3": '#!/bin/sh\necho Python >&2\nexit 49\n',
            "python": '#!/bin/sh\nexit 9009\n',
        },
    )
    sh_dir = Path(shutil.which("sh") or "/bin/sh").parent

    result = run_wrapper(
        "session-start",
        env={"PATH": f"{bin_dir}{os.pathsep}{sh_dir}"},
    )

    assert result.returncode == 0
    assert "hooks are NOT running" in result.stderr


@needs_bash
def test_the_no_python_message_is_ascii(tmp_path):
    """It is printed by a console that may be cp949; non-ASCII would arrive
    as mojibake exactly when the message matters."""
    text = WRAPPER.read_text(encoding="utf-8")

    for line in text.splitlines():
        if "NOT running" in line:
            assert line.isascii(), line


def test_the_wrapper_has_no_carriage_returns():
    """bash reads the unix half; a \\r would end up in every command."""
    assert b"\r" not in WRAPPER.read_bytes()


def test_the_wrapper_is_committed_executable():
    """The same failure as in the snapshot, one layer up. A plugin installed
    on Linux gets this file out of git, and git is where the execute bit
    lives — without it bash refuses to run the wrapper and every hook is
    silently dead on that machine."""
    listed = subprocess.run(
        ["git", "ls-files", "-s", "hooks/run-hook.cmd"],
        cwd=Path(__file__).resolve().parent.parent,
        capture_output=True, text=True,
    ).stdout

    assert listed.startswith("100755"), listed or "(인덱스에 없다)"
