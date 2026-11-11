"""Type aliases shared across modules."""

from __future__ import annotations

from typing import Any, TypedDict

# The effective, validated settings of one VM, as returned by `config.resolve` (see CONTRIBUTING.md for the keys).
Settings = dict[str, Any]


class Mount(TypedDict, total=False):
    """One host folder shared into a VM. `optional` marks the automatic dotfiles mount, which is skipped if missing."""

    source: str
    path: str
    readonly: bool
    optional: bool
