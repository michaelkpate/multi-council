import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from adapters import agy
from adapters.base import Job


def _job() -> Job:
    return Job(
        seat="gemini",
        transport="agy",
        model="gemini-3.1-pro-high",
        prompt="Should I refactor now or ship first?",
        timeout_s=60,
    )


def test_prompt_is_the_value_of_print_and_comes_last():
    """Regression: --print consumes the next token as its prompt.

    If any flag is ever appended after --print, that flag becomes the prompt
    and the real question is silently discarded with exit code 0.
    """
    argv = agy.build_argv(_job())
    assert argv[-2] == "--print"
    assert argv[-1] == "Should I refactor now or ship first?"


def test_argv_contains_no_flag_after_the_prompt():
    argv = agy.build_argv(_job())
    assert not argv[-1].startswith("--")


def test_model_and_json_format_are_passed():
    argv = agy.build_argv(_job())
    assert argv[argv.index("--model") + 1] == "gemini-3.1-pro-high"
    assert argv[argv.index("--output-format") + 1] == "json"


def test_successful_run_extracts_response():
    payload = {"status": "SUCCESS", "response": "Ship first.", "duration_seconds": 7.4}
    seen = {}

    def fake_runner(argv, timeout):
        seen["argv"] = list(argv)
        return subprocess.CompletedProcess(argv, 0, json.dumps(payload), "")

    r = agy.run(_job(), _runner=fake_runner)
    assert r.ok is True
    assert r.text == "Ship first."
    # The invariant must hold on the argv that actually reaches the subprocess,
    # not merely on what build_argv returned. Without this, run() could append
    # a flag after the prompt and every other test would still pass.
    assert seen["argv"][-2] == "--print"
    assert seen["argv"][-1] == "Should I refactor now or ship first?"


def test_nonzero_exit_is_a_clean_failure():
    def fake_runner(argv, timeout):
        return subprocess.CompletedProcess(argv, 1, "", "agent execution terminated")

    r = agy.run(_job(), _runner=fake_runner)
    assert r.ok is False
    assert "exit 1" in r.error


def test_unparseable_stdout_is_a_clean_failure():
    def fake_runner(argv, timeout):
        return subprocess.CompletedProcess(argv, 0, "not json at all", "")

    r = agy.run(_job(), _runner=fake_runner)
    assert r.ok is False
    assert "malformed" in r.error


def test_timeout_is_a_clean_failure():
    def fake_runner(argv, timeout):
        raise subprocess.TimeoutExpired(argv, timeout)

    r = agy.run(_job(), _runner=fake_runner)
    assert r.ok is False
    assert "timeout" in r.error.lower()


def test_non_success_status_is_a_failure():
    payload = {"status": "ERROR", "response": "some plausible text", "duration_seconds": 1.0}

    def fake_runner(argv, timeout):
        return subprocess.CompletedProcess(argv, 0, json.dumps(payload), "")

    r = agy.run(_job(), _runner=fake_runner)
    assert r.ok is False
    assert "ERROR" in r.error


def test_os_error_is_a_clean_failure():
    def fake_runner(argv, timeout):
        raise PermissionError("access denied")

    r = agy.run(_job(), _runner=fake_runner)
    assert r.ok is False
    assert "PermissionError" in r.error


def test_executable_is_resolved_to_a_full_path(monkeypatch):
    """Windows CreateProcess will not find a .cmd shim by bare name."""
    payload = {"status": "SUCCESS", "response": "Ship first.", "duration_seconds": 7.4}
    seen = {}

    def fake_runner(argv, timeout):
        seen["argv"] = list(argv)
        return subprocess.CompletedProcess(argv, 0, json.dumps(payload), "")

    monkeypatch.setattr(agy, "resolve_executable", lambda name: r"C:\resolved\agy.CMD")
    agy.run(_job(), _runner=fake_runner)
    assert seen["argv"][0] == r"C:\resolved\agy.CMD"


def test_unresolvable_executable_is_a_clean_failure(monkeypatch):
    monkeypatch.setattr(agy, "resolve_executable", lambda name: None)
    r = agy.run(_job())
    assert r.ok is False
    assert "not found on PATH" in r.error
