"""Commands that show or edit the configuration."""

from __future__ import annotations

import argparse
import os
import shlex

import yaml

from capsule.config import resolve
from capsule.paths import config_path


def cmd_config(a: argparse.Namespace) -> None:
    """Effective settings for a VM (built-in defaults + capsule.yml), without creating anything."""
    c = resolve(a.name) if a.name else resolve("<name>")
    print(f"# {config_path()}\n# effective settings for {a.name or 'a VM without overrides'}")
    print(yaml.safe_dump({k: v for k, v in c.items() if k != "home"}, sort_keys=False), end="")


def cmd_edit(_: argparse.Namespace) -> None:
    os.execvp("sh", ["sh", "-c", f'exec "${{VISUAL:-${{EDITOR:-nano}}}}" {shlex.quote(str(config_path()))}'])
