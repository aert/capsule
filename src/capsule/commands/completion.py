"""Shell completion scripts and the hidden helper that feeds them."""

from __future__ import annotations

import argparse
import json
import os
import shutil

from capsule.config import config_vms
from capsule.defaults import COMMANDS
from capsule.incus import incus

COMPLETION = """\
_capsule() {
  local cur="${COMP_WORDS[COMP_CWORD]}"
  if [ "$COMP_CWORD" -eq 1 ]; then
    COMPREPLY=( $(compgen -W "$(capsule _complete commands) $(capsule _complete vms)" -- "$cur") )
  else
    COMPREPLY=( $(compgen -W "$(capsule _complete vms)" -- "$cur") )
  fi
}
complete -F _capsule capsule
"""


ZSH_COMPLETION = """\
_capsule() {
  local -a items
  if (( CURRENT == 2 )); then
    items=( ${(z)"$(capsule _complete commands) $(capsule _complete vms)"} )
  else
    items=( ${(z)"$(capsule _complete vms)"} )
  fi
  compadd -- $items
}
compdef _capsule capsule
"""


def cmd_completion(a: argparse.Namespace) -> None:
    shell = a.shell or os.path.basename(os.environ.get("SHELL", "bash"))
    print(ZSH_COMPLETION if shell == "zsh" else COMPLETION, end="")


def cmd_complete(a: argparse.Namespace) -> None:  # hidden: feeds the completion script
    if a.what == "commands":
        print(" ".join(c for c in COMMANDS if c != "help"))
        return
    names = set(config_vms())
    if shutil.which("incus"):
        r = incus("list", "-f", "json", check=False, capture=True)
        if r.returncode == 0:
            names |= {i["name"] for i in json.loads(r.stdout or "[]")}
    print(" ".join(sorted(names)))
