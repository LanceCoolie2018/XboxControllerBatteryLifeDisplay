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
        # initial user report scan
        if cfg.user_report.enabled:
            for msg in scan_user_report(cfg, self.state, trigger="daemon_start"):
                log.info("%s", msg)

        self.process.start()

        try:
            while not self._stop:
                now = time.time()
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
