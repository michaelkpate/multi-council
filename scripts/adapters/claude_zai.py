"""Claude Code CLI pointed at Z.ai, for GLM under a GLM Coding Plan.

The Z.ai environment variables repoint Claude Code at a different provider.
They are built into a COPY and passed to the subprocess only — never applied
to os.environ, which would silently repoint the running session.
"""

from __future__ import annotations

import os
import subprocess
import time

from .base import Job, Result, redact

ZAI_BASE_URL = "https://api.z.ai/api/anthropic"


def build_env(base_env: dict, api_key: str, model: str) -> dict:
    env = dict(base_env)  # copy; never mutate the caller's mapping
    env["ANTHROPIC_BASE_URL"] = ZAI_BASE_URL
    env["ANTHROPIC_AUTH_TOKEN"] = api_key
    env["ANTHROPIC_DEFAULT_OPUS_MODEL"] = model
    # Inherited values outrank the ones we set: ANTHROPIC_MODEL beats
    # ANTHROPIC_DEFAULT_OPUS_MODEL, and ANTHROPIC_API_KEY can beat
    # ANTHROPIC_AUTH_TOKEN. Leaving them would silently answer from the wrong
    # model while Result.model still claims glm-5.2.
    for conflicting in ("ANTHROPIC_MODEL", "ANTHROPIC_API_KEY"):
        env.pop(conflicting, None)
    return env


def build_argv(job: Job) -> list[str]:
    return ["claude", "-p", job.prompt]


def _default_runner(argv: list[str], timeout: int, env: dict):
    return subprocess.run(
        argv,
        capture_output=True,
        text=True,
        timeout=timeout,
        encoding="utf-8",
        env=env,
        stdin=subprocess.DEVNULL,
    )


def run(job: Job, _runner=None) -> Result:
    start = time.monotonic()

    api_key = os.environ.get("ZAI_API_KEY")
    if not api_key:
        return Result.failure(
            job, "ZAI_API_KEY not set in environment", time.monotonic() - start
        )

    runner = _runner or _default_runner
    env = build_env(os.environ, api_key, job.model)

    try:
        completed = runner(build_argv(job), timeout=job.timeout_s, env=env)
    except subprocess.TimeoutExpired:
        return Result.failure(job, "timeout expired", time.monotonic() - start)
    except FileNotFoundError:
        return Result.failure(job, "claude not found on PATH", time.monotonic() - start)
    except OSError as exc:
        # Windows .cmd shims can raise PermissionError and friends. FileNotFoundError
        # is an OSError subclass, so it must be caught above this clause.
        detail = redact(str(exc), api_key)
        return Result.failure(
            job, f"{type(exc).__name__}: {detail}", time.monotonic() - start
        )

    if completed.returncode != 0:
        # Redact BEFORE truncating. Truncating first can slice through the key
        # and leave a partial secret in the error.
        detail = redact((completed.stderr or "").strip(), api_key)[:200]
        return Result.failure(
            job, f"exit {completed.returncode}: {detail}", time.monotonic() - start
        )

    return Result.success(job, completed.stdout, time.monotonic() - start)
