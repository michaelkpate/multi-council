import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from adapters import codex
from adapters.base import Job


def _job() -> Job:
    return Job(
        seat="gpt",
        transport="codex",
        model="gpt-5.6-luna",
        prompt="Assess this plan.",
        timeout_s=300,
    )


def test_argv_uses_readonly_sandbox_and_json():
    argv = codex.build_argv(_job(), "/tmp/out.txt")
    assert argv[:2] == ["codex", "exec"]
    assert "--sandbox" in argv and argv[argv.index("--sandbox") + 1] == "read-only"
    assert "--json" in argv
    assert "--skip-git-repo-check" in argv


def test_argv_passes_model_and_effort_as_config_overrides():
    # effort must be non-default here, or a hardcoded "high" would pass.
    argv = codex.build_argv(_job(), "/tmp/out.txt", effort="low")
    assert "model=gpt-5.6-luna" in argv
    assert "model_reasoning_effort=low" in argv


def test_prompt_is_last_and_output_file_is_flagged():
    argv = codex.build_argv(_job(), "/tmp/out.txt")
    assert argv[-1] == "-"
    assert argv[argv.index("-o") + 1] == "/tmp/out.txt"


def test_successful_run_reads_the_output_file():
    seen = {}

    def fake_runner(argv, timeout, input_text):
        seen["argv"] = list(argv)
        seen["input"] = input_text
        out_path = argv[argv.index("-o") + 1]
        Path(out_path).write_text("The plan is sound.", encoding="utf-8")
        return subprocess.CompletedProcess(argv, 0, "", "")

    r = codex.run(_job(), _runner=fake_runner)
    assert r.ok is True
    assert r.text == "The plan is sound."
    # Pin the argv that actually reaches the subprocess, not just build_argv's
    # return value — the same guard test_agy.py carries.
    assert seen["argv"][-1] == "-"
    assert seen["input"] == "Assess this plan."


def test_nonzero_exit_is_a_clean_failure():
    def fake_runner(argv, timeout, input_text):
        return subprocess.CompletedProcess(argv, 2, "", "auth expired")

    r = codex.run(_job(), _runner=fake_runner)
    assert r.ok is False
    assert "exit 2" in r.error


def test_missing_output_file_is_a_clean_failure():
    def fake_runner(argv, timeout, input_text):
        return subprocess.CompletedProcess(argv, 0, "", "")

    r = codex.run(_job(), _runner=fake_runner)
    assert r.ok is False
    assert "no output" in r.error


def test_timeout_is_a_clean_failure():
    def fake_runner(argv, timeout, input_text):
        raise subprocess.TimeoutExpired(argv, timeout)

    r = codex.run(_job(), _runner=fake_runner)
    assert r.ok is False
    assert "timeout" in r.error.lower()


def test_missing_binary_is_a_clean_failure():
    def fake_runner(argv, timeout, input_text):
        raise FileNotFoundError("codex")

    r = codex.run(_job(), _runner=fake_runner)
    assert r.ok is False
    assert "not found" in r.error


def test_os_error_is_a_clean_failure():
    def fake_runner(argv, timeout, input_text):
        raise PermissionError("access denied")

    r = codex.run(_job(), _runner=fake_runner)
    assert r.ok is False
    assert "PermissionError" in r.error


def test_default_runner_resolves_the_executable(monkeypatch):
    """Windows CreateProcess will not find a .cmd shim by bare name."""
    seen = {}

    def fake_subprocess_run(argv, **kwargs):
        seen["argv"] = list(argv)
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(codex, "resolve_executable", lambda n: r"C:\resolved\codex.CMD")
    monkeypatch.setattr(codex.subprocess, "run", fake_subprocess_run)
    codex._default_runner(["codex", "exec", "hi"], timeout=10, input_text="hi")
    assert seen["argv"][0] == r"C:\resolved\codex.CMD"
    assert seen["argv"][1:] == ["exec", "hi"]


def test_default_runner_raises_when_unresolvable(monkeypatch):
    monkeypatch.setattr(codex, "resolve_executable", lambda n: None)
    with pytest.raises(FileNotFoundError):
        codex._default_runner(["codex", "exec", "hi"], timeout=10, input_text="hi")


def test_oversized_prompt_never_reaches_argv():
    """cmd.exe caps the command line at ~8191 chars; the prompt must go on stdin."""
    big = "x" * 20000
    job = Job(seat="s", transport="codex", model="m", prompt=big, timeout_s=30)
    seen = {}

    def fake_runner(argv, timeout, input_text):
        seen["argv"] = list(argv)
        seen["input"] = input_text
        out_path = argv[argv.index("-o") + 1]
        Path(out_path).write_text("ok", encoding="utf-8")
        return subprocess.CompletedProcess(argv, 0, "", "")

    codex.run(job, _runner=fake_runner)
    assert seen["input"] == big
    assert big not in " ".join(seen["argv"])
    assert sum(len(a) for a in seen["argv"]) < 1000
