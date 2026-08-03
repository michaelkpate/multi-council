"""Core data types shared by every transport adapter."""

from __future__ import annotations

from dataclasses import asdict, dataclass


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
