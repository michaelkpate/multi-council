import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from adapters.base import Job, Result


def _job() -> Job:
    return Job(seat="s1", transport="fake", model="m", prompt="p", timeout_s=10)


def test_success_holds_stripped_text():
    r = Result.success(_job(), "  hello  ", 1.234)
    assert r.ok is True
    assert r.text == "hello"
    assert r.error is None
    assert r.elapsed_s == 1.23


def test_blank_text_is_downgraded_to_failure():
    r = Result.success(_job(), "   \n ", 1.0)
    assert r.ok is False
    assert r.text is None
    assert r.error == "empty response"


def test_none_text_is_an_empty_response_failure():
    r = Result.success(_job(), None, 1.0)
    assert r.ok is False
    assert r.text is None
    assert r.error == "empty response"


def test_non_string_text_is_a_malformed_response_failure():
    """A provider returning content-parts must not raise out of the chokepoint."""
    r = Result.success(_job(), [{"type": "text", "text": "hi"}], 1.0)
    assert r.ok is False
    assert r.text is None
    assert "not a string" in r.error


def test_failure_carries_error_and_no_text():
    r = Result.failure(_job(), "boom", 2.0)
    assert r.ok is False
    assert r.text is None
    assert r.error == "boom"


def test_to_dict_shape():
    d = Result.success(_job(), "hi", 0.5).to_dict()
    assert set(d) == {"seat", "model", "ok", "text", "error", "elapsed_s"}
    assert d["seat"] == "s1"
