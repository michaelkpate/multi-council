"""Antigravity CLI transport (Gemini).

CRITICAL: `--print` takes the prompt as its VALUE. The prompt must always be
the final element of argv, immediately after `--print`. Appending any flag
after it silently replaces the question with that flag's name and returns a
confident wrong answer with exit code 0.
"""

from __future__ import annotations

import json
import subprocess
import time

from .base import Job, Result, resolve_executable


def build_argv(job: Job) -> list[str]:
    # --print and the prompt MUST stay last, in this order. See test_agy.py.
    return [
        "agy",
        "--model",
        job.model,
        "--output-format",
        "json",
        "--print-timeout",
        f"{job.timeout_s}s",
        "--print",
        job.prompt,
    ]


def _default_runner(argv: list[str], timeout: int):
    return subprocess.run(
        argv,
        capture_output=True,
        text=True,
        timeout=timeout,
        encoding="utf-8",
        errors="replace",
        stdin=subprocess.DEVNULL,
    )


def run(job: Job, _runner=None) -> Result:
    start = time.monotonic()
    runner = _runner or _default_runner

    argv = build_argv(job)
    # Windows CreateProcess appends .exe but not .cmd, so a bare name never
    # reaches a shim-installed CLI. Resolve here, after build_argv, so the
    # argv-shape invariants stay assertable on build_argv's own output.
    exe = resolve_executable(argv[0])
    if exe is None:
        return Result.failure(
            job, f"{argv[0]} not found on PATH", time.monotonic() - start
        )
    argv[0] = exe

    try:
        completed = runner(argv, timeout=job.timeout_s + 15)
    except subprocess.TimeoutExpired:
        return Result.failure(job, "timeout expired", time.monotonic() - start)
    except FileNotFoundError:
        return Result.failure(job, "agy not found on PATH", time.monotonic() - start)
    except OSError as exc:
        # Windows .cmd shims can raise PermissionError and friends. FileNotFoundError
        # is an OSError subclass, so it must be caught above this clause.
        return Result.failure(
            job, f"{type(exc).__name__}: {exc}", time.monotonic() - start
        )

    if completed.returncode != 0:
        detail = (completed.stderr or "").strip()[:200]
        return Result.failure(
            job, f"exit {completed.returncode}: {detail}", time.monotonic() - start
        )

    try:
        body = json.loads(completed.stdout)
        text = body["response"]
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        return Result.failure(
            job, f"malformed agy output: {exc}", time.monotonic() - start
        )

    # `status` is the only field that distinguishes a real answer from a fluent
    # answer to the wrong question. Dropping it makes a non-success invisible.
    status = body.get("status")
    if status is not None and status != "SUCCESS":
        return Result.failure(
            job, f"agy reported status {status}", time.monotonic() - start
        )

    return Result.success(job, text, time.monotonic() - start)
