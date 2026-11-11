"""Where capsule keeps its files (XDG base directories)."""

from __future__ import annotations

import os
from pathlib import Path


def xdg_config() -> Path:
    """`$XDG_CONFIG_HOME`, or `~/.config` when it is not set."""
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")


def config_path() -> Path:
    """The config file: `$CAPSULE_CONFIG`, else `$XDG_CONFIG_HOME/capsule.yml`. Read on every call, so tests can change it."""
    override = os.environ.get("CAPSULE_CONFIG")
    return Path(override).expanduser() if override else xdg_config() / "capsule.yml"
