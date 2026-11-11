"""The one exception type capsule uses for user-facing failures."""

from __future__ import annotations

from typing import NoReturn


class CapsuleError(Exception):
    """A failure the user can act on: shown as `capsule: message` plus an optional hint, exit status 1."""

    def __init__(self, message: str, hint: str | None = None) -> None:
        super().__init__(message)
        self.hint = hint


def die(msg: str, hint: str | None = None) -> NoReturn:
    """Abort the current command with a friendly message (and, ideally, the fix as `hint`)."""
    raise CapsuleError(msg, hint)
