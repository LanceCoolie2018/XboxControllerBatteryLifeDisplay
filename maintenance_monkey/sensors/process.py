"""Optional process supervisor — capture stderr for incidents."""

from __future__ import annotations

import logging
import subprocess
import threading
from pathlib import Path

from maintenance_monkey.config import Config
from maintenance_monkey.patterns import (
    DEFAULT_INCLUDE,
    StackAssembler,
    compile_patterns,
    line_matches,
)
from maintenance_monkey.pipeline.fingerprint import fingerprint_stack, fingerprint_text
from maintenance_monkey.pipeline.queue import enqueue_incident
from maintenance_monkey.state import State

log = logging.getLogger("mm.process")


class ProcessSupervisor:
    def __init__(self, cfg: Config, state: State) -> None:
        self.cfg = cfg
        self.state = state
        include = cfg.patterns.include or DEFAULT_INCLUDE
        self.include = compile_patterns(include)
        self.exclude = compile_patterns(cfg.patterns.exclude)
        self._proc: subprocess.Popen[str] | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._assembler = StackAssembler()
        self._window: list[str] = []

    def start(self) -> None:
        if not self.cfg.process.enabled or not self.cfg.process.command:
            return
        self._stop.clear()
        self._spawn()
        self._thread = threading.Thread(target=self._reader, name="mm-proc", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._proc and self._proc.poll() is None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._proc.kill()
        if self._thread:
            self._thread.join(timeout=3)

    def _spawn(self) -> None:
        cwd = Path(self.cfg.process.cwd)
        if not cwd.is_absolute():
            cwd = self.cfg.project.root / cwd
        log.info("starting process: %s (cwd=%s)", self.cfg.process.command, cwd)
        self._proc = subprocess.Popen(
            self.cfg.process.command,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )

    def _reader(self) -> None:
        while not self._stop.is_set():
            proc = self._proc
            if proc is None:
                break
            assert proc.stdout is not None
            for line in proc.stdout:
                if self._stop.is_set():
                    break
                self._handle_line(line.rstrip("\n"))
            rc = proc.poll()
            if rc is not None:
                log.info("process exited rc=%s", rc)
                if self.cfg.process.incident_on_crash and rc != 0:
                    self._emit_crash(rc)
                if self.cfg.process.restart_on_exit and not self._stop.is_set():
                    self._spawn()
                    continue
                break

    def _handle_line(self, line: str) -> None:
        self._window.append(line)
        if len(self._window) > 50:
            del self._window[:-50]
        stack = self._assembler.feed(line)
        if stack:
            self._emit_stack(stack)
            return
        if line_matches(line, self.include, self.exclude) and not self._assembler._active:
            fp = fingerprint_text("proc", line)
            body = (
                f"# Process stderr/stdout match\n\n"
                f"**Command:** `{self.cfg.process.command}`\n\n"
                f"**Line:** {line}\n\n"
                f"## Recent window\n```\n" + "\n".join(self._window[-40:]) + "\n```\n"
            )
            enqueue_incident(
                self.state,
                self.cfg,
                source="process",
                fingerprint=fp,
                title=line.strip()[:100],
                body=body,
            )

    def _emit_stack(self, stack: str) -> None:
        fp = fingerprint_stack(stack)
        title = "Process stack trace"
        for ln in stack.splitlines():
            if "Error" in ln or "Exception" in ln:
                title = ln.strip()[:100]
                break
        body = (
            f"# Process stack\n\n"
            f"**Command:** `{self.cfg.process.command}`\n\n"
            f"## Stack\n```\n{stack}\n```\n"
        )
        enqueue_incident(
            self.state,
            self.cfg,
            source="process_stack",
            fingerprint=fp,
            title=title,
            body=body,
        )

    def _emit_crash(self, rc: int) -> None:
        fp = fingerprint_text("crash", f"{self.cfg.process.command}:{rc}")
        body = (
            f"# Process crashed\n\n"
            f"**Command:** `{self.cfg.process.command}`\n"
            f"**Exit code:** {rc}\n\n"
            f"## Recent output\n```\n" + "\n".join(self._window[-50:]) + "\n```\n"
        )
        enqueue_incident(
            self.state,
            self.cfg,
            source="process_crash",
            fingerprint=fp,
            title=f"Process exited {rc}",
            body=body,
        )
