"""OpenRouter HTTP transport. Stdlib only."""

from __future__ import annotations

import json
import os
import time
import urllib.request

from .base import Job, Result, redact

API_URL = "https://openrouter.ai/api/v1/chat/completions"


def build_payload(job: Job, seed: int | None) -> dict:
    payload: dict = {
        "model": job.model,
        "messages": [{"role": "user", "content": job.prompt}],
    }
    if seed is not None:
        payload["seed"] = seed
    return payload


def run(job: Job, seed: int | None = None, _urlopen=None) -> Result:
    start = time.monotonic()

    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        return Result.failure(
            job, "OPENROUTER_API_KEY not set in environment", time.monotonic() - start
        )

    request = urllib.request.Request(
        API_URL,
        data=json.dumps(build_payload(job, seed)).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    urlopen = _urlopen or urllib.request.urlopen
    try:
        with urlopen(request, timeout=job.timeout_s) as response:
            body = json.loads(response.read().decode("utf-8"))
    except Exception as exc:  # network, timeout, HTTP error, bad JSON
        # Redact BEFORE truncating: truncating first can slice through the key
        # and leave a partial secret in the error.
        detail = redact(str(exc), api_key)[:200]
        return Result.failure(
            job, f"{type(exc).__name__}: {detail}", time.monotonic() - start
        )

    try:
        text = body["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        # The exception text can echo the response body, which can echo the key.
        detail = redact(str(exc), api_key)[:200]
        return Result.failure(
            job, f"malformed response: {detail}", time.monotonic() - start
        )

    return Result.success(job, text, time.monotonic() - start)
