import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import dispatch
from adapters.base import Job, Result


def _job(seat: str, transport: str = "fake") -> Job:
    return Job(seat=seat, transport=transport, model="m", prompt="p", timeout_s=5)


def test_load_jobs_parses_and_defaults_timeout():
    raw = {
        "jobs": [
            {"seat": "a", "transport": "openrouter", "model": "x/y", "prompt": "q"},
            {"seat": "b", "transport": "agy", "model": "g", "prompt": "q", "timeout_s": 99},
        ]
    }
    jobs = dispatch.load_jobs(raw)
    assert jobs[0].timeout_s == dispatch.DEFAULT_TIMEOUTS["openrouter"]
    assert jobs[1].timeout_s == 99


def test_run_jobs_returns_one_result_per_job_in_input_order():
    def fake(job: Job) -> Result:
        return Result.success(job, f"answer from {job.seat}", 0.1)

    jobs = [_job("a"), _job("b"), _job("c")]
    results = dispatch.run_jobs(jobs, transports={"fake": fake})
    assert [r.seat for r in results] == ["a", "b", "c"]
    assert all(r.ok for r in results)


def test_unknown_transport_is_a_clean_failure():
    jobs = [_job("a", transport="nope")]
    results = dispatch.run_jobs(jobs, transports={"fake": lambda j: None})
    assert results[0].ok is False
    assert "unknown transport" in results[0].error


def test_one_adapter_raising_does_not_kill_the_council():
    def flaky(job: Job) -> Result:
        if job.seat == "b":
            raise RuntimeError("adapter blew up")
        return Result.success(job, "fine", 0.1)

    jobs = [_job("a"), _job("b"), _job("c")]
    results = dispatch.run_jobs(jobs, transports={"fake": flaky})
    by_seat = {r.seat: r for r in results}
    assert by_seat["a"].ok is True
    assert by_seat["c"].ok is True
    assert by_seat["b"].ok is False
    assert "RuntimeError" in by_seat["b"].error


def test_jobs_actually_run_in_parallel():
    def slow(job: Job) -> Result:
        time.sleep(0.3)
        return Result.success(job, "done", 0.3)

    jobs = [_job(str(i)) for i in range(5)]
    start = time.monotonic()
    dispatch.run_jobs(jobs, transports={"fake": slow})
    elapsed = time.monotonic() - start
    # Serial would be ~1.5s. Parallel should be well under 1s.
    assert elapsed < 1.0


def test_dry_run_prints_plan_and_spends_nothing(capsys, tmp_path):
    raw = {"jobs": [{"seat": "a", "transport": "openrouter", "model": "x/y", "prompt": "secret prompt"}]}
    jobs_file = tmp_path / "jobs.json"
    jobs_file.write_text(json.dumps(raw), encoding="utf-8")

    rc = dispatch.main(["--jobs", str(jobs_file), "--dry-run"])
    out = capsys.readouterr().out

    assert rc == 0
    assert "openrouter" in out
    assert "x/y" in out
