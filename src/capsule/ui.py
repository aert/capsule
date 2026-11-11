"""Terminal output and prompts: colours, step/warning lines, confirmation questions."""

from __future__ import annotations

import sys

TTY = sys.stdout.isatty()


def style(code: str, s: str) -> str:
    return f"\033[{code}m{s}\033[0m" if TTY else s


def bold(s: str) -> str:
    return style("1", s)


def green(s: str) -> str:
    return style("32", s)


def step(msg: str) -> None:
    print(f"{bold('==>')} {msg}")


def warn(msg: str) -> None:
    print(f"WARNING: {msg}", file=sys.stderr)


def confirm(question: str, default: bool = False, yes: bool = False) -> bool:
    if yes:
        return True
    a = input(f"{question} [{'Y/n' if default else 'y/N'}] ").strip().lower()
    return default if not a else a.startswith("y")


def ask(question: str, default: str = "") -> str:
    a = input(f"{question}{f' [{default}]' if default else ''}: ").strip()
    return a or default
