"""Reading a hook's payload.

The failure this guards against was found by accident: a payload arrived with
a UTF-8 BOM in front of it, `json.loads` refused it, the reader returned an
empty dict, and the hook then reported confidently on the wrong directory –
"the snapshot is missing" for a repository whose snapshot was right there.

A check that answers the wrong question is worse than one that fails, because
nothing about the output says it is wrong.
"""
import io
import json

import hook_io
import pytest


def read(monkeypatch, raw: str) -> dict:
    monkeypatch.setattr(hook_io.sys, "stdin", io.StringIO(raw))
    return hook_io.read_payload()


def test_reads_an_ordinary_payload(monkeypatch):
    payload = read(monkeypatch, json.dumps({"cwd": "/repo", "hook_event_name": "Stop"}))

    assert payload["cwd"] == "/repo"


def test_tolerates_a_utf8_bom(monkeypatch):
    """Windows tooling puts one there. Refusing the payload over a byte order
    mark would take the whole session's checks with it."""
    payload = read(monkeypatch, "﻿" + json.dumps({"cwd": "/repo"}))

    assert payload["cwd"] == "/repo"


def test_tolerates_surrounding_whitespace(monkeypatch):
    payload = read(monkeypatch, "\n  " + json.dumps({"cwd": "/repo"}) + "  \n")

    assert payload["cwd"] == "/repo"


def test_an_empty_payload_is_an_empty_dict(monkeypatch):
    """Hooks are also invoked by hand and by tests with nothing on stdin.
    That is not an error."""
    assert read(monkeypatch, "") == {}
    assert read(monkeypatch, "   \n") == {}


def test_unreadable_input_raises_instead_of_pretending(monkeypatch, capsys):
    """The old behaviour returned {} here, and the caller then resolved cwd
    to "." – a different repository – and reported on that one."""
    with pytest.raises(hook_io.PayloadError):
        read(monkeypatch, "{this is not json")


def test_the_failure_says_what_happened(monkeypatch):
    try:
        read(monkeypatch, "{this is not json")
    except hook_io.PayloadError as exc:
        assert "payload" in str(exc).lower() or "JSON" in str(exc)
    else:
        pytest.fail("예외가 나지 않았다")


def test_cwd_of_requires_the_field(monkeypatch):
    """Falling back to the process directory is how the wrong-directory
    report happened. An absent cwd is the caller's problem to state."""
    with pytest.raises(hook_io.PayloadError):
        hook_io.cwd_of({})


def test_cwd_of_returns_the_path(monkeypatch, tmp_path):
    assert hook_io.cwd_of({"cwd": str(tmp_path)}) == tmp_path
