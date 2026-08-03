import io
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from adapters import openrouter
from adapters.base import Job


def _job() -> Job:
    return Job(
        seat="deepseek",
        transport="openrouter",
        model="deepseek/deepseek-v4-flash-0731",
        prompt="What is 2+2?",
        timeout_s=30,
    )


class _FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_payload_includes_model_and_prompt():
    p = openrouter.build_payload(_job(), None)
    assert p["model"] == "deepseek/deepseek-v4-flash-0731"
    assert p["messages"] == [{"role": "user", "content": "What is 2+2?"}]
    assert "seed" not in p


def test_payload_includes_seed_when_given():
    p = openrouter.build_payload(_job(), 42)
    assert p["seed"] == 42


def test_missing_api_key_is_a_clean_failure(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    r = openrouter.run(_job())
    assert r.ok is False
    assert "OPENROUTER_API_KEY" in r.error


def test_successful_call_returns_text(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    body = {"choices": [{"message": {"content": "4"}}]}

    def fake_urlopen(req, timeout=None):
        assert req.get_header("Authorization") == "Bearer test-key"
        return _FakeResponse(json.dumps(body).encode("utf-8"))

    r = openrouter.run(_job(), _urlopen=fake_urlopen)
    assert r.ok is True
    assert r.text == "4"


def test_malformed_response_is_a_clean_failure(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")

    def fake_urlopen(req, timeout=None):
        return _FakeResponse(json.dumps({"unexpected": True}).encode("utf-8"))

    r = openrouter.run(_job(), _urlopen=fake_urlopen)
    assert r.ok is False
    assert "malformed" in r.error


def test_network_error_is_a_clean_failure(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")

    def fake_urlopen(req, timeout=None):
        raise TimeoutError("timed out")

    r = openrouter.run(_job(), _urlopen=fake_urlopen)
    assert r.ok is False
    assert "TimeoutError" in r.error


def test_api_key_never_appears_in_error_text(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "super-secret-value")

    def fake_urlopen(req, timeout=None):
        raise RuntimeError("upstream rejected super-secret-value")

    r = openrouter.run(_job(), _urlopen=fake_urlopen)
    assert r.ok is False
    assert "super-secret-value" not in (r.error or "")
    assert "<redacted>" in r.error


def test_malformed_response_path_also_redacts(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "super-secret-value")

    class _Weird:
        def __getitem__(self, k):
            raise KeyError("choices missing near super-secret-value")

    def fake_urlopen(req, timeout=None):
        import io, json as _json
        class R(io.BytesIO):
            def __enter__(self): return self
            def __exit__(self, *e): return False
        return R(_json.dumps({"unexpected": True}).encode("utf-8"))

    r = openrouter.run(_job(), _urlopen=fake_urlopen)
    assert r.ok is False
    assert "super-secret-value" not in (r.error or "")
