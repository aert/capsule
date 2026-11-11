"""Command-line interface: help text, argument parsing and the entry point."""

from __future__ import annotations

import argparse
import os
import shutil
import sys

from capsule.commands.completion import cmd_complete, cmd_completion
from capsule.commands.host import cmd_acl, cmd_doctor, cmd_setup
from capsule.commands.settings import cmd_config, cmd_edit
from capsule.commands.snapshots import cmd_restore, cmd_snap, cmd_snaps
from capsule.commands.vms import cmd_add, cmd_ls, cmd_new, cmd_open, cmd_power, cmd_rebuild, cmd_rm, cmd_shell, cmd_up
from capsule.defaults import COMMANDS, SIZES
from capsule.errors import CapsuleError, die
from capsule.incus import incus
from capsule.paths import config_path
from capsule.scaffold import ensure_config
from capsule.ui import confirm

HELP = """\
capsule: customer VMs on Incus

Everyday
  capsule <vm>              open a shell (herdr) in the VM; starts it, or creates it if defined in the config
  capsule new [vm]          create a VM; with no name it asks a few questions
                            [--size small|medium|large] [--cpu N] [--ram 8GiB] [--disk 40GiB]
  capsule up [vm...]        create/start the VMs defined under `vms:` in the config
  capsule add <vm>          record a VM's settings under `vms:` in the config (from the VM itself, or from flags)
  capsule ls                list VMs, state, IP, size, last snapshot
  capsule open <vm> [port]  show the URLs of a dev server in the VM [--browser] [--forward|--unforward to localhost]
  capsule start|stop|restart <vm...>
  capsule shell <vm> [cmd...]   run a command in the VM instead of the shell

Safety net
  capsule snap <vm> [name]  snapshot before something risky (default name: pre-ai)
  capsule snaps <vm>        list snapshots
  capsule restore <vm> [name]   roll back (asks first)
  capsule rebuild <vm>      recreate from the current config; the old VM is kept as <vm>-prev
  capsule rm <vm>           delete a VM and all its data

Setup and help
  capsule setup             one-time host setup (installs incus; uses sudo)
  capsule doctor            check the host, config and VMs, with a fix for every problem
  capsule config [vm]       show the effective settings
  capsule edit              edit the config file ({path})
  capsule acl               print the Tailscale policy for your VMs
  capsule completion [bash|zsh]   tab completion: add  eval "$(capsule completion)"  to ~/.bashrc or ~/.zshrc
"""


class Parser(argparse.ArgumentParser):
    def error(self, message):
        die(message, "see `capsule help`")


def build_parser() -> argparse.ArgumentParser:
    p = Parser(prog="capsule", add_help=False)
    sub = p.add_subparsers(dest="command", required=True, parser_class=Parser)

    def add(name, fn, *positionals, flags=()):
        s = sub.add_parser(name, add_help=False)
        for pos in positionals:
            s.add_argument(pos[0], **(pos[1] if len(pos) > 1 else {}))
        for f in flags:
            s.add_argument(*f.split("|"), action="store_true")
        s.set_defaults(fn=fn)
        return s

    s = add("new", cmd_new, ("name", {"nargs": "?"}))
    s.add_argument("--size", choices=list(SIZES))
    s.add_argument("--cpu"), s.add_argument("--memory", "--ram"), s.add_argument("--disk")
    s = add("add", cmd_add, ("name",))
    s.add_argument("--size", choices=list(SIZES))
    s.add_argument("--cpu"), s.add_argument("--memory", "--ram"), s.add_argument("--disk")
    add("up", cmd_up, ("names", {"nargs": "*"}))
    add("shell", cmd_shell, ("name",), ("cmd", {"nargs": argparse.REMAINDER}))
    add("ls", cmd_ls)
    add("open", cmd_open, ("name",), ("port", {"nargs": "?"}), flags=("--browser", "--forward", "--unforward"))
    for n in ("start", "stop", "restart"):
        add(n, cmd_power, ("names", {"nargs": "+"}))
    add("snap", cmd_snap, ("name",), ("snapname", {"nargs": "?", "default": "pre-ai"}))
    add("snaps", cmd_snaps, ("name",))
    add("restore", cmd_restore, ("name",), ("snapname", {"nargs": "?", "default": "pre-ai"}), flags=("-y|--yes",))
    add("rebuild", cmd_rebuild, ("name",), flags=("-y|--yes",))
    add("rm", cmd_rm, ("name",), flags=("-y|--yes",))
    add("config", cmd_config, ("name", {"nargs": "?"}))
    for n, fn in (("edit", cmd_edit), ("doctor", cmd_doctor), ("setup", cmd_setup), ("acl", cmd_acl)):
        add(n, fn)
    add("completion", cmd_completion, ("shell", {"nargs": "?", "choices": ["bash", "zsh"]}))
    add("_complete", cmd_complete, ("what", {"choices": ["commands", "vms"]}))
    return p


NO_CONFIG_FILE = ("acl", "completion", "_complete")  # do not create the config file on first run
NO_INCUS_NEEDED = ("config", "edit", "setup", "acl", "doctor", "completion", "_complete")


def normalise_argv(argv: list[str]) -> list[str] | None:
    """Apply the CLI conventions; returns None when help was printed and nothing else should run.

    - no arguments means `ls`
    - `capsule acme` means `capsule shell acme`, so a VM name works like a command
    - `capsule <command> --help` prints the command list
    """
    if not argv:
        return ["ls"]
    if argv[0] in ("-h", "--help", "help") or (len(argv) > 1 and argv[0] in COMMANDS and argv[1] in ("-h", "--help")):
        print(HELP.format(path=config_path()))
        return None
    if not argv[0].startswith("-") and argv[0] not in COMMANDS + ["_complete"]:
        return ["shell", *argv]
    return argv


def preflight(args: argparse.Namespace) -> int | None:
    """Checks that must pass before any command that talks to Incus. Returns an exit status to stop early."""
    if not shutil.which("incus"):
        if sys.stdin.isatty() and confirm("Incus is not installed. Run the one-time host setup now?", default=True):
            return cmd_setup(args)
        die("incus is not installed", "run `capsule setup`")
    if incus("list", "-f", "csv", "-c", "n", check=False, capture=True).returncode != 0:
        die(
            "cannot talk to incus",
            "are you in the incus-admin group? Log out and in again after `capsule setup`, or run `capsule doctor`",
        )
    return None


def run(argv: list[str]) -> int | None:
    """Parse and execute one command line. Raises CapsuleError for failures the user can fix."""
    argv = normalise_argv(argv)
    if argv is None:
        return 0
    if os.getuid() == 0:
        die(
            "do not run capsule as root or with sudo",
            "run it as your normal user; `capsule setup` calls sudo itself where needed",
        )
    args = build_parser().parse_args(argv)
    if args.command not in NO_CONFIG_FILE:
        ensure_config()
    if args.command not in NO_INCUS_NEEDED:
        status = preflight(args)
        if status is not None:
            return status
    return args.fn(args)


def main() -> None:
    """Console-script entry point: run the command line and turn failures into a message and an exit status."""
    try:
        sys.exit(run(sys.argv[1:]) or 0)
    except CapsuleError as error:
        print(f"capsule: {error}", file=sys.stderr)
        if error.hint:
            print(f"  {error.hint}", file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        sys.exit(130)
    except EOFError:
        sys.exit("capsule: aborted")
