"""Parsing and normalising sizes (`8GiB`) and reading host memory."""

from __future__ import annotations

import re
from pathlib import Path

from capsule.errors import die


def size(v: object, what: str) -> str:
    m = re.fullmatch(r"(\d+(?:\.\d+)?)\s*(G|GB|GiB|M|MB|MiB)?", str(v).strip())
    if not m:
        die(f"invalid {what}: {v!r}", "use for example 8GiB or 512MiB (a bare number means GiB)")
    return f"{m.group(1)}{'MiB' if (m.group(2) or 'G')[0] == 'M' else 'GiB'}"


def to_mib(s: object) -> float:
    m = re.fullmatch(r"([\d.]+)\s*(\w+)", str(s).strip())
    if not m:
        return 0
    mult = {
        "B": 1 / 2**20,
        "kB": 1 / 1024,
        "KiB": 1 / 1024,
        "MB": 1e6 / 2**20,
        "MiB": 1,
        "GB": 1e9 / 2**20,
        "GiB": 1024,
        "TB": 1e12 / 2**20,
        "TiB": 2**20,
    }.get(m.group(2), 0)
    return float(m.group(1)) * mult


def host_mem_mib() -> int:
    try:
        return int(re.search(r"MemTotal:\s+(\d+)", Path("/proc/meminfo").read_text()).group(1)) // 1024
    except (OSError, AttributeError):
        return 0
