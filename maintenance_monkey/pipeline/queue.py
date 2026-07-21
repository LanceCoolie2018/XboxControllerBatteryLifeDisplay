"""Enqueue incidents as jobs with dedupe/cooldown."""

from __future__ import annotations

import logging
from typing import Any

from maintenance_monkey.config import Config
from maintenance_monkey.state import Incident, Job, State

log = logging.getLogger("mm.queue")


def enqueue_incident(
    state: State,
    cfg: Config,
    *,
    source: str,
    fingerprint: str,
    title: str,
    body: str,
    meta: dict[str, Any] | None = None,
) -> tuple[Incident | None, Job | None, str]:
    """
    Create incident + job unless fingerprint should be skipped.
    Returns (incident, job, message).
    """
    skip, reason = state.should_skip_fingerprint(
        fingerprint, cfg.dispatch.cooldown_seconds
    )
    if skip:
        log.info("skip fingerprint %s: %s", fingerprint, reason)
        return None, None, f"skipped: {reason}"

    incident = state.add_incident(
        source=source,
        fingerprint=fingerprint,
        title=title,
        body=body,
        meta=meta,
    )
    job = state.create_job(incident)
    log.info("enqueued job %s for incident %s (%s)", job.id, incident.id, title)
    return incident, job, f"queued job {job.id}"
