import os
import subprocess
import sys
from pathlib import Path

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
        return subprocess.CompletedProcess(argv, 0, "The weakest point is X.", "")

    r = claude_zai.run(_job(), _runner=fake_runner)
    assert r.ok is True
    assert r.text == "The weakest point is X."
    assert seen["env"]["ANTHROPIC_BASE_URL"] == claude_zai.ZAI_BASE_URL
    assert seen["env"]["ANTHROPIC_AUTH_TOKEN"] == "secret"
    assert seen["env"]["ANTHROPIC_DEFAULT_OPUS_MODEL"] == "glm-5.2"


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
