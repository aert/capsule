"""The commented starter config written on first run."""

from __future__ import annotations

import sys

from capsule.defaults import DEFAULTS
from capsule.paths import config_path
from capsule.ui import warn


def sample() -> str:
    u = DEFAULTS["user"]
    return f"""\
# capsule config, created on first run. Uncommented lines are your starting point; commented lines are hints.
# Changes apply to the next `capsule new` / `capsule up` / `capsule rebuild`.
# `capsule config <vm>` shows what a VM will actually get; `capsule doctor` checks it.

version: 1                  # config format; if a newer capsule changes it, you are told how to upgrade

defaults:                  # applies to every VM
  size: medium             # small = 2 CPU/4GiB, medium = 4/8GiB, large = 8/16GiB. Or set cpu: and ram: yourself
  disk: 40GiB
  user: {u["name"]}:{u["uid"]}:{u["gid"]}   # name:uid:gid, copied from you: files on mounts keep your ownership
  # dotfiles: ~/dotfiles/install               # your dotbot install script (args ok): its folder is mounted (live), the script runs once
  packages: [neovim, tig, btop]                # extra apt packages, added to the built-in ones
  mise:                                        # tools installed globally in each VM (`mise use -g`); name@version, "latest" by default
    - lazygit@latest
    - herdr@latest                             # the default `shell`: keep it here, or change `shell:` below
    - github:can1357/oh-my-pi@latest           # oh-my-pi: installs the `omp` command

  # Host folders to share with every VM (none by default). `~` = your home on the host, and the VM user's home in the VM.
  # mounts:
  #   - ~/Code                                 # same path inside the VM
  #   - ~/Projects
  #   - ~/Docs:/mnt/docs:ro                    # src:dest[:ro]
  # tailscale: {{key_file: ~/.config/capsule/tailscale-key, tag: "tag:cust-{{name}}"}}   # or `tailscale: null`
  # run: ["mise use -g node@22"]               # commands run once in each new VM, as the VM user
  # shell: herdr                               # what `capsule <vm>` runs
  # image: images:debian/13/cloud

vms:                       # one entry per customer VM; `capsule up` creates them all
  # acme:
  #   size: small
  # globex:
  #   mounts: [~/Code/globex]        # only this customer's code
  #   packages: [postgresql-client]
  #   mise: [node@22, python@3.13]   # added to the defaults above
  # initech:
  #   size: large
  #   user: dev:1000:1000
"""


def ensure_config() -> None:
    """First run: write the config file with your detected user and the defaults."""
    if config_path().exists():
        return
    try:
        config_path().parent.mkdir(parents=True, exist_ok=True)
        config_path().write_text(sample())
        print(f"capsule: first run, created {config_path()} (edit it with `capsule edit`)", file=sys.stderr)
    except OSError as e:
        warn(f"could not create {config_path()}: {e}; using built-in defaults")
