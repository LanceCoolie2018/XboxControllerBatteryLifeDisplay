"""Incident fingerprinting for deduplication."""

from __future__ import annotations

import hashlib
import re


_ADDR = re.compile(r"0x[0-9a-fA-F]+")
_LINE_NO = re.compile(r"line \d+", re.I)
_WS = re.compile(r"\s+")


def normalize_text(text: str) -> str:
    t = text.strip().lower()
    t = _ADDR.sub("0xADDR", t)
    t = _LINE_NO.sub("line N", t)
    t = _WS.sub(" ", t)
    return t


def fingerprint_text(prefix: str, text: str) -> str:
    norm = normalize_text(text)
    digest = hashlib.sha256(norm.encode("utf-8")).hexdigest()[:16]
    return f"{prefix}:{digest}"


def fingerprint_id(prefix: str, stable_id: str) -> str:
    safe = re.sub(r"[^a-zA-Z0-9._-]+", "-", stable_id.strip())[:64]
    return f"{prefix}:{safe}"


def fingerprint_stack(stack: str) -> str:
    # Keep file paths and symbols; drop pure noise
    lines = []
    for line in stack.splitlines():
        line = line.strip()
        if not line:
            continue
        line = _ADDR.sub("0xADDR", line)
        lines.append(line)
    body = "\n".join(lines[:40])
    return fingerprint_text("stack", body)
