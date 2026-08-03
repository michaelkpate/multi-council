"""Core data types shared by every transport adapter."""

from __future__ import annotations

import shutil
from dataclasses import asdict, dataclass


def resolve_executable(name: str) -> str | None:
    """Resolve a command name to a full path.

    Windows CreateProcess appends .exe but not .cmd, so npm and shim-installed
    CLIs fail when invoked by bare name even though they are on PATH.
    shutil.which applies PATHEXT and finds them. No-op on POSIX.
    """
    return shutil.which(name)


def redact(text: str, secret: str | None) -> str:
    """Remove a secret from text before it reaches any Result."""
    if not secret:
        return text
    return text.replace(secret, "<redacted>")


@dataclass(frozen=True)
class Job:
    """One advisor seat's work: which model, via which transport, with what prompt."""

    seat: str
    transport: str
    model: str
    prompt: str
    timeout_s: int


@dataclass(frozen=True)
class Result:
    """Normalized outcome of one job. Adapters never raise; they return this."""

    seat: str
    model: str
    ok: bool
    text: str | None
    error: str | None
    elapsed_s: float

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def failure(cls, job: Job, error: str, elapsed_s: float) -> "Result":
        return cls(
            seat=job.seat,
            model=job.model,
            ok=False,
            text=None,
            error=error,
            elapsed_s=round(elapsed_s, 2),
        )

    @classmethod
    def success(cls, job: Job, text: str | None, elapsed_s: float) -> "Result":
        # A provider can return structured content (OpenAI-style content-parts
        # arrays) instead of a string. Guard here, at the chokepoint, so that no
        # adapter can raise on it.
        if text is not None and not isinstance(text, str):
            return cls.failure(
                job, "malformed response: text is not a string", elapsed_s
            )
        # An exit-0 run that produced no text is a failure, not a success.
        # Centralizing this here means every adapter gets the rule for free.
        if text is None or not text.strip():
            return cls.failure(job, "empty response", elapsed_s)
        return cls(
            seat=job.seat,
            model=job.model,
            ok=True,
            text=text.strip(),
            error=None,
            elapsed_s=round(elapsed_s, 2),
        )
