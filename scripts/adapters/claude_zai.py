"""Claude Code CLI pointed at Z.ai, for GLM under a GLM Coding Plan.

The Z.ai environment variables repoint Claude Code at a different provider.
They are built into a COPY and passed to the subprocess only — never applied
to os.environ, which would silently repoint the running session.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
import time
from pathlib import Path

from .base import Job, Result, redact, resolve_executable

ZAI_BASE_URL = "https://api.z.ai/api/anthropic"


def build_env(
    base_env: dict, api_key: str, model: str, config_dir: str | None = None
) -> dict:
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
    if config_dir is not None:
        # Isolate from the user's global ~/.claude/settings.json, whose env
        # block can override ANTHROPIC_* values we set here.
        env["CLAUDE_CONFIG_DIR"] = config_dir
    return env


def build_argv(job: Job) -> list[str]:
    # --model must be explicit: a global settings.json env block can set
    # ANTHROPIC_MODEL, which outranks the ANTHROPIC_DEFAULT_OPUS_MODEL we pass
    # in the subprocess environment. The prompt stays last, after -p.
    return ["claude", "--model", job.model, "-p", job.prompt]


def _default_runner(argv: list[str], timeout: int, env: dict):
    exe = resolve_executable(argv[0])
    if exe is None:
        # Windows CreateProcess appends .exe but not .cmd, so npm and shim
        # installed CLIs are unfindable by bare name. Raise the same error
        # subprocess would, so run()'s existing handler reports it uniformly.
        raise FileNotFoundError(argv[0])
    return subprocess.run(
        [exe, *argv[1:]],
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

    argv = build_argv(job)
    # Executable resolution belongs to the runner that actually executes.
    # An injected _runner supplies its own execution mechanism and must not
    # be second-guessed here. See _default_runner.

    # The outer handler only sees failures from creating the temp config dir or
    # writing settings.json — every error inside the block returns instead of
    # propagating. Without it, a disk failure here would raise out of run().
    try:
        # ignore_cleanup_errors: on Windows a surviving grandchild process can
        # still hold a file under the temp dir, and __exit__ would raise
        # PermissionError out of run() — breaking the never-raise rule.
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as config_dir:
            # An empty settings.json means the spawned claude has no env block
            # to inherit; CLAUDE_CONFIG_DIR points it here instead of ~/.claude.
            (Path(config_dir) / "settings.json").write_text("{}", encoding="utf-8")
            env = build_env(os.environ, api_key, job.model, config_dir=config_dir)

            try:
                completed = runner(argv, timeout=job.timeout_s, env=env)
            except subprocess.TimeoutExpired:
                return Result.failure(job, "timeout expired", time.monotonic() - start)
            except FileNotFoundError:
                return Result.failure(
                    job, "claude not found on PATH", time.monotonic() - start
                )
            except OSError as exc:
                # Windows .cmd shims can raise PermissionError and friends.
                # FileNotFoundError is an OSError subclass, so it must be caught
                # above this clause.
                detail = redact(str(exc), api_key)
                return Result.failure(
                    job, f"{type(exc).__name__}: {detail}", time.monotonic() - start
                )

            if completed.returncode != 0:
                # claude writes API errors to stdout, not stderr. Include both,
                # or every upstream API failure arrives as an empty message.
                # Redact BEFORE truncating: truncating first can slice through
                # the key and leave a partial secret in the error.
                combined = (
                    (completed.stderr or "") + " " + (completed.stdout or "")
                ).strip()
                detail = redact(combined, api_key)[:200]
                return Result.failure(
                    job,
                    f"exit {completed.returncode}: {detail}",
                    time.monotonic() - start,
                )

            return Result.success(job, completed.stdout, time.monotonic() - start)
    except OSError as exc:
        detail = redact(str(exc), api_key)
        return Result.failure(
            job, f"{type(exc).__name__}: {detail}", time.monotonic() - start
        )
