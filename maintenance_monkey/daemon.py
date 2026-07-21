"""Long-running watcher loop."""

from __future__ import annotations

import logging
import signal
import time
from pathlib import Path

from maintenance_monkey.config import Config
from maintenance_monkey.dispatch.grok_runner import GrokRunner
from maintenance_monkey.sensors.known_bugs import KnownBugMatcher
from maintenance_monkey.sensors.logs import LogTailer
from maintenance_monkey.sensors.process import ProcessSupervisor
from maintenance_monkey.sensors.user_report import UserReportWatcher, scan_user_report
from maintenance_monkey.state import State

log = logging.getLogger("mm.daemon")


class Daemon:
    def __init__(self, cfg: Config, state: State) -> None:
        self.cfg = cfg
        self.state = state
        self._stop = False
        known = None
        if cfg.known_bugs.match_logs:
            known = KnownBugMatcher(cfg.project.root / cfg.known_bugs.path)
        self.logs = LogTailer(cfg, state, known=known) if cfg.logs.paths else None
        self.user_report = UserReportWatcher(cfg, state)
        self.process = ProcessSupervisor(cfg, state)
        self.runner = GrokRunner(cfg, state)

    def request_stop(self, *_args: object) -> None:
        log.info("stop requested")
        self._stop = True

    def run(self) -> None:
        cfg = self.cfg
        cfg.mm_dir.mkdir(parents=True, exist_ok=True)
        cfg.jobs_dir.mkdir(parents=True, exist_ok=True)
        cfg.logs_dir.mkdir(parents=True, exist_ok=True)

        import os

        pidfile = cfg.pidfile
        pidfile.write_text(str(os.getpid()), encoding="utf-8")

        signal.signal(signal.SIGINT, self.request_stop)
        signal.signal(signal.SIGTERM, self.request_stop)

        log.info("Maintenance Monkey started for %s", cfg.project.name)
        # initial user report scan (with optional pull)
        if cfg.user_report.enabled:
            for msg in scan_user_report(cfg, self.state, trigger="daemon_start"):
                log.info("%s", msg)

        self.process.start()
        last_remote_poll = time.time()
        remote_interval = float(cfg.user_report.remote_poll_seconds or 0)

        try:
            while not self._stop:
                now = time.time()
                # Periodic remote sync: laptop pushes to AssIsstant won't change
                # local mtime until we pull. Without this, UserReport never updates.
                if (
                    cfg.user_report.enabled
                    and remote_interval > 0
                    and (now - last_remote_poll) >= remote_interval
                ):
                    last_remote_poll = now
                    # Force pull even if pull_before_scan is false for local edits
                    from maintenance_monkey.dispatch import git_workflow

                    pull_msg = git_workflow.ff_pull(cfg)
                    log.info("remote poll: %s", pull_msg)
                    # Reset mtime baseline so local watcher doesn't double-fire
                    ur_path = cfg.project.root / cfg.user_report.path
                    if ur_path.is_file():
                        try:
                            self.user_report._mtime = ur_path.stat().st_mtime
                            self.user_report._pending_since = None
                        except OSError:
                            pass
                    # Clear Ready-for-Review / Failed when issues resolve or "task complete"
                    try:
                        from maintenance_monkey.pipeline.acknowledge import (
                            clear_resolved_failures,
                            process_task_complete_commits,
                        )

                        for msg in process_task_complete_commits(cfg, self.state):
                            log.info("%s", msg)
                        for msg in clear_resolved_failures(cfg, self.state):
                            log.info("%s", msg)
                    except Exception:
                        log.exception("ack/resolve scan failed")
                    for msg in scan_user_report(
                        cfg, self.state, trigger="remote_poll"
                    ):
                        # scan may pull again if pull_before_scan — harmless
                        log.info("%s", msg)

                if self.logs:
                    for msg in self.logs.poll():
                        log.info("%s", msg)
                for msg in self.user_report.poll(now):
                    log.info("%s", msg)
                for msg in self.runner.process_queue():
                    log.info("%s", msg)
                time.sleep(1.0)
        finally:
            self.process.stop()
            try:
                pidfile.unlink(missing_ok=True)
            except OSError:
                pass
            log.info("Maintenance Monkey stopped")


def run_once(cfg: Config, state: State) -> list[str]:
    """Single pass: user report + logs + process queue."""
    messages: list[str] = []
    known = None
    if cfg.known_bugs.match_logs:
        known = KnownBugMatcher(cfg.project.root / cfg.known_bugs.path)
    if cfg.user_report.enabled:
        messages.extend(scan_user_report(cfg, state, trigger="once"))
    if cfg.logs.paths:
        tailer = LogTailer(cfg, state, known=known)
        # from_start for once if empty positions — force read new content only
        messages.extend(tailer.poll())
    runner = GrokRunner(cfg, state)
    messages.extend(runner.process_queue())
    return messages
