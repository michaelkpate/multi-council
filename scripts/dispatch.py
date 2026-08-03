#!/usr/bin/env python3
"""Parallel fan-out for multi-council.

Knows nothing about councils, advisors, roles, or synthesis. Given a list of
jobs it runs them concurrently and emits normalized JSON. All judgment lives
in SKILL.md.

Usage:
    python dispatch.py --jobs jobs.json          # run, print results JSON
    python dispatch.py --jobs jobs.json --dry-run  # print plan, spend nothing
"""

from __future__ import annotations

import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor

from adapters import agy, openrouter
from adapters.base import Job, Result

DEFAULT_TIMEOUTS = {
    "openrouter": 30,
    "agy": 60,
    "claude_zai": 90,
    "codex": 300,
}

TRANSPORTS = {
    "openrouter": openrouter.run,
    "agy": agy.run,
}


def load_jobs(raw: dict) -> list[Job]:
    jobs = []
    for entry in raw["jobs"]:
        transport = entry["transport"]
        jobs.append(
            Job(
                seat=entry["seat"],
                transport=transport,
                model=entry["model"],
                prompt=entry["prompt"],
                timeout_s=entry.get("timeout_s", DEFAULT_TIMEOUTS.get(transport, 60)),
            )
        )
    return jobs


def _run_one(job: Job, transports: dict) -> Result:
    adapter = transports.get(job.transport)
    if adapter is None:
        return Result.failure(job, f"unknown transport: {job.transport}", 0.0)
    try:
        return adapter(job)
    except Exception as exc:
        # An adapter that raises must not take the council down with it.
        return Result.failure(job, f"{type(exc).__name__}: {exc}", 0.0)


def run_jobs(jobs: list[Job], transports: dict | None = None) -> list[Result]:
    active = transports if transports is not None else TRANSPORTS
    if not jobs:
        return []
    with ThreadPoolExecutor(max_workers=len(jobs)) as pool:
        return list(pool.map(lambda j: _run_one(j, active), jobs))


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="multi-council parallel dispatcher")
    parser.add_argument("--jobs", required=True, help="path to jobs JSON file")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print what would be dispatched, without running anything",
    )
    args = parser.parse_args(argv)

    with open(args.jobs, encoding="utf-8") as handle:
        jobs = load_jobs(json.load(handle))

    if args.dry_run:
        for job in jobs:
            print(
                f"{job.seat:<12} {job.transport:<12} {job.model:<44} "
                f"timeout={job.timeout_s}s prompt={len(job.prompt)}ch"
            )
        return 0

    results = run_jobs(jobs)
    json.dump([r.to_dict() for r in results], sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
