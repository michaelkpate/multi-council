"""Codex CLI transport (GPT). Authenticates via ChatGPT OAuth, no API key."""

from __future__ import annotations

import subprocess
import tempfile
import time
from pathlib import Path

from .base import Job, Result


def build_argv(job: Job, out_file: str, effort: str = "high") -> list[str]:
    return [
        "codex",
        "exec",
        "--json",
        "--skip-git-repo-check",
        "--sandbox",
        "read-only",
        "--color",
        "never",
        "-c",
        f"model={job.model}",
        "-c",
        f"model_reasoning_effort={effort}",
        "-o",
        out_file,
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

    # ignore_cleanup_errors: on Windows a surviving grandchild process can still
    # hold the output file, and __exit__ would raise PermissionError out of
    # run() — the one path where this adapter could break the never-raise rule.
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        out_file = str(Path(tmpdir) / "codex-out.txt")
        try:
            completed = runner(build_argv(job, out_file), timeout=job.timeout_s)
        except subprocess.TimeoutExpired:
            return Result.failure(job, "timeout expired", time.monotonic() - start)
        except FileNotFoundError:
            return Result.failure(
                job, "codex not found on PATH", time.monotonic() - start
            )
        except OSError as exc:
            # Windows .cmd shims can raise PermissionError and friends.
            # FileNotFoundError is an OSError subclass, so it must be caught
            # above this clause.
            return Result.failure(
                job, f"{type(exc).__name__}: {exc}", time.monotonic() - start
            )

        if completed.returncode != 0:
            detail = (completed.stderr or "").strip()[:200]
            return Result.failure(
                job, f"exit {completed.returncode}: {detail}", time.monotonic() - start
            )

        path = Path(out_file)
        if not path.exists():
            return Result.failure(
                job, "no output file written by codex", time.monotonic() - start
            )
        # errors="replace": a strict decode of non-UTF-8 CLI output would raise
        # UnicodeDecodeError out of run(), breaking the never-raise rule.
        text = path.read_text(encoding="utf-8", errors="replace")

    return Result.success(job, text, time.monotonic() - start)
