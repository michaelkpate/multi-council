import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from adapters import claude_zai
from adapters.base import Job


def _job() -> Job:
    return Job(
        seat="glm",
        transport="claude_zai",
        model="glm-5.2",
        prompt="Where is this plan weakest?",
        timeout_s=90,
    )


def test_build_env_sets_the_three_required_variables():
    env = claude_zai.build_env({"PATH": "/usr/bin"}, "secret", "glm-5.2")
    assert env["ANTHROPIC_BASE_URL"] == claude_zai.ZAI_BASE_URL
    assert env["ANTHROPIC_AUTH_TOKEN"] == "secret"
    assert env["ANTHROPIC_DEFAULT_OPUS_MODEL"] == "glm-5.2"
    assert env["PATH"] == "/usr/bin"


def test_conflicting_inherited_vars_are_cleared():
    base = {
        "PATH": "/usr/bin",
        "ANTHROPIC_MODEL": "some-other-model",
        "ANTHROPIC_API_KEY": "inherited-key",
    }
    env = claude_zai.build_env(base, "secret", "glm-5.2")
    assert "ANTHROPIC_MODEL" not in env
    assert "ANTHROPIC_API_KEY" not in env
    assert env["ANTHROPIC_DEFAULT_OPUS_MODEL"] == "glm-5.2"
    assert env["ANTHROPIC_AUTH_TOKEN"] == "secret"
    assert env["PATH"] == "/usr/bin"
    # The caller's mapping must still be untouched.
    assert base["ANTHROPIC_MODEL"] == "some-other-model"


def test_build_env_does_not_mutate_the_parent_environment(monkeypatch):
    """Leaking these into the parent repoints the running Claude session."""
    monkeypatch.setenv("ZAI_API_KEY", "secret")
    base = {"PATH": "/usr/bin"}
    before = dict(os.environ)

    claude_zai.build_env(base, "secret", "glm-5.2")
    assert base == {"PATH": "/usr/bin"}

    # The real leak path is run(), which builds the Z.ai env from os.environ.
    # If it applied that mapping instead of copying it, the *running* Claude
    # session would silently repoint at Z.ai. Compare the whole mapping rather
    # than asserting one var is absent: the ambient environment may already
    # legitimately define ANTHROPIC_BASE_URL (pointing at Anthropic).
    claude_zai.run(
        _job(),
        _runner=lambda argv, timeout, env: subprocess.CompletedProcess(
            argv, 0, "ok", ""
        ),
    )
    assert dict(os.environ) == before


def test_prompt_is_the_value_of_dash_p():
    argv = claude_zai.build_argv(_job())
    assert argv[-2] == "-p"
    assert argv[-1] == "Where is this plan weakest?"


def test_argv_passes_model_explicitly():
    argv = claude_zai.build_argv(_job())
    assert argv[argv.index("--model") + 1] == "glm-5.2"
    assert argv[-2] == "-p"
    assert argv[-1] == "Where is this plan weakest?"


def test_build_env_sets_an_isolated_config_dir():
    env = claude_zai.build_env({"PATH": "/usr/bin"}, "secret", "glm-5.2", config_dir="/tmp/cfg")
    assert env["CLAUDE_CONFIG_DIR"] == "/tmp/cfg"


def test_stdout_is_included_in_error_detail(monkeypatch):
    """claude writes API errors to stdout; reporting only stderr hides them."""
    monkeypatch.setenv("ZAI_API_KEY", "secret")

    def fake_runner(argv, timeout, env):
        return subprocess.CompletedProcess(
            argv, 1, "API Error: 400 [1211][Unknown Model]", ""
        )

    r = claude_zai.run(_job(), _runner=fake_runner)
    assert r.ok is False
    assert "Unknown Model" in r.error


def test_run_isolates_the_config_dir(monkeypatch):
    monkeypatch.setenv("ZAI_API_KEY", "secret")
    seen = {}

    def fake_runner(argv, timeout, env):
        seen["env"] = dict(env)
        return subprocess.CompletedProcess(argv, 0, "answer", "")

    claude_zai.run(_job(), _runner=fake_runner)
    assert seen["env"]["CLAUDE_CONFIG_DIR"]
    assert "ANTHROPIC_MODEL" not in seen["env"]


def test_missing_key_is_a_clean_failure(monkeypatch):
    monkeypatch.delenv("ZAI_API_KEY", raising=False)
    r = claude_zai.run(_job())
    assert r.ok is False
    assert "ZAI_API_KEY" in r.error


def test_successful_run_returns_stdout(monkeypatch):
    monkeypatch.setenv("ZAI_API_KEY", "secret")

    seen = {}

    def fake_runner(argv, timeout, env):
        # Capture here, assert after run() returns: an AssertionError raised
        # inside the runner can be swallowed by an except clause in the adapter.
        seen["env"] = dict(env)
        seen["argv"] = list(argv)
        return subprocess.CompletedProcess(argv, 0, "The weakest point is X.", "")

    r = claude_zai.run(_job(), _runner=fake_runner)
    assert r.ok is True
    assert r.text == "The weakest point is X."
    assert seen["env"]["ANTHROPIC_BASE_URL"] == claude_zai.ZAI_BASE_URL
    assert seen["env"]["ANTHROPIC_AUTH_TOKEN"] == "secret"
    assert seen["env"]["ANTHROPIC_DEFAULT_OPUS_MODEL"] == "glm-5.2"
    assert seen["argv"][-2] == "-p"
    assert seen["argv"][-1] == "Where is this plan weakest?"


def test_nonzero_exit_is_a_clean_failure(monkeypatch):
    monkeypatch.setenv("ZAI_API_KEY", "secret")

    def fake_runner(argv, timeout, env):
        return subprocess.CompletedProcess(argv, 1, "", "rate limited")

    r = claude_zai.run(_job(), _runner=fake_runner)
    assert r.ok is False
    assert "exit 1" in r.error


def test_api_key_never_appears_in_error_text(monkeypatch):
    monkeypatch.setenv("ZAI_API_KEY", "super-secret-value")

    def fake_runner(argv, timeout, env):
        return subprocess.CompletedProcess(argv, 1, "", "failed with super-secret-value")

    r = claude_zai.run(_job(), _runner=fake_runner)
    assert "super-secret-value" not in (r.error or "")


def test_long_stderr_cannot_leak_a_straddling_key(monkeypatch):
    """Redaction must happen before truncation, or a sliced key survives."""
    monkeypatch.setenv("ZAI_API_KEY", "super-secret-value")

    def fake_runner(argv, timeout, env):
        # Place the key so it straddles the 200-character truncation boundary.
        # 186 padding leaves 14 of the key's 18 characters inside the cut, so a
        # truncate-then-redact implementation leaks "super-secret-v". At 190 the
        # surviving slice is only "super-secr", which is short enough to sneak
        # past the assertion below -- the padding has to be tuned deliberately.
        stderr = "x" * 186 + "super-secret-value" + " trailing noise"
        return subprocess.CompletedProcess(argv, 1, "", stderr)

    r = claude_zai.run(_job(), _runner=fake_runner)
    assert r.ok is False
    assert "super-secret" not in (r.error or "")


def test_timeout_is_a_clean_failure(monkeypatch):
    monkeypatch.setenv("ZAI_API_KEY", "secret")

    def fake_runner(argv, timeout, env):
        raise subprocess.TimeoutExpired(argv, timeout)

    r = claude_zai.run(_job(), _runner=fake_runner)
    assert r.ok is False
    assert "timeout" in r.error.lower()


def test_os_error_is_a_clean_failure(monkeypatch):
    monkeypatch.setenv("ZAI_API_KEY", "secret")

    def fake_runner(argv, timeout, env):
        raise PermissionError("access denied")

    r = claude_zai.run(_job(), _runner=fake_runner)
    assert r.ok is False
    assert "PermissionError" in r.error


def test_default_runner_resolves_the_executable(monkeypatch):
    """Windows CreateProcess will not find a .cmd shim by bare name."""
    seen = {}

    def fake_subprocess_run(argv, **kwargs):
        seen["argv"] = list(argv)
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(
        claude_zai, "resolve_executable", lambda n: r"C:\resolved\claude.CMD"
    )
    monkeypatch.setattr(claude_zai.subprocess, "run", fake_subprocess_run)
    claude_zai._default_runner(["claude", "-p", "hi"], timeout=10, env={"PATH": "/x"})
    assert seen["argv"][0] == r"C:\resolved\claude.CMD"
    assert seen["argv"][1:] == ["-p", "hi"]


def test_default_runner_raises_when_unresolvable(monkeypatch):
    monkeypatch.setattr(claude_zai, "resolve_executable", lambda n: None)
    with pytest.raises(FileNotFoundError):
        claude_zai._default_runner(
            ["claude", "-p", "hi"], timeout=10, env={"PATH": "/x"}
        )


def test_unresolvable_executable_is_a_clean_failure(monkeypatch):
    """run() must still convert that into a Result, never an exception."""
    monkeypatch.setenv("ZAI_API_KEY", "secret")

    def exploding_runner(argv, timeout, env):
        raise FileNotFoundError("claude")

    r = claude_zai.run(_job(), _runner=exploding_runner)
    assert r.ok is False
    assert "not found on PATH" in r.error
