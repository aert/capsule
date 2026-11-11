"""capsule: one Incus VM per project, configured by a YAML file.

The package is split by responsibility; see CONTRIBUTING.md for the architecture. `capsule.cli.main` is the
console-script entry point.
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

from capsule.cli import main

try:
    __version__ = version("capsule-vm")
except PackageNotFoundError:  # running from a source tree that was never installed
    __version__ = "0.0.0"

__all__ = ["__version__", "main"]
