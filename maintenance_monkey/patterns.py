"""Default exception / error line patterns and multi-line stack assembly."""

from __future__ import annotations

import re
from dataclasses import dataclass, field


# Start of multi-line stacks
STACK_STARTS = [
    re.compile(r"Traceback \(most recent call last\):"),
    re.compile(r"Unhandled exception\.?", re.I),
    re.compile(r"Exception in thread ", re.I),
    re.compile(r"---+\s*Exception", re.I),
    re.compile(r"System\.\w*Exception", re.I),
    re.compile(r"^\s*panic:", re.I),
    re.compile(r"Fatal error:", re.I),
]

# Continuation lines while buffering a stack
STACK_CONTINUE = [
    re.compile(r"^\s+File \""),
    re.compile(r"^\s+at\s+"),
    re.compile(r"^\s+\.\.\."),
    re.compile(r"^\s+~*\^~*"),
    re.compile(r"^[A-Za-z_][\w.]*Exception:"),
    re.compile(r"^[A-Za-z_][\w.]*(Error|Exception|Fault):"),
    re.compile(r"^\s+raised\s+"),
    re.compile(r"^Caused by:", re.I),
    re.compile(r"^\s+---"),
    re.compile(r"^goroutine \d+", re.I),
]

DEFAULT_INCLUDE = [
    r"(?i)exception",
    r"(?i)traceback \(most recent call last\)",
    r"Unhandled exception",
    r"(?i)fatal error",
    r"panic:",
    r"(?i)\berror\b.*\bfailed\b",
]


@dataclass
class StackAssembler:
    """Buffer multi-line stack traces from a stream of log lines."""

    max_lines: int = 80
    idle_flush_lines: int = 2  # non-matching lines before flush
    _buf: list[str] = field(default_factory=list)
    _idle: int = 0
    _active: bool = False

    def feed(self, line: str) -> str | None:
        """Feed one line. Returns a completed stack (joined) or None."""
        stripped = line.rstrip("\n")

        if not self._active:
            if any(p.search(stripped) for p in STACK_STARTS):
                self._active = True
                self._buf = [stripped]
                self._idle = 0
            return None

        # active
        if any(p.search(stripped) for p in STACK_CONTINUE) or any(
            p.search(stripped) for p in STACK_STARTS
        ):
            self._buf.append(stripped)
            self._idle = 0
            if len(self._buf) >= self.max_lines:
                return self._flush()
            return None

        # exception title line often follows traceback frames
        if self._buf and re.match(
            r"^[A-Za-z_][\w.]*(Error|Exception|Fault|Panic)", stripped
        ):
            self._buf.append(stripped)
            return self._flush()

        self._idle += 1
        if stripped.strip():
            # include one trailing non-empty context line then flush
            self._buf.append(stripped)
            return self._flush()
        if self._idle >= self.idle_flush_lines:
            return self._flush()
        return None

    def _flush(self) -> str | None:
        if not self._buf:
            self._active = False
            self._idle = 0
            return None
        text = "\n".join(self._buf)
        self._buf = []
        self._active = False
        self._idle = 0
        return text

    def close(self) -> str | None:
        return self._flush()


def compile_patterns(patterns: list[str]) -> list[re.Pattern[str]]:
    out: list[re.Pattern[str]] = []
    for p in patterns:
        try:
            out.append(re.compile(p))
        except re.error:
            out.append(re.compile(re.escape(p)))
    return out


def line_matches(
    line: str,
    include: list[re.Pattern[str]],
    exclude: list[re.Pattern[str]],
) -> bool:
    if exclude and any(p.search(line) for p in exclude):
        return False
    if not include:
        return False
    return any(p.search(line) for p in include)
