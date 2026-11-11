"""Built-in defaults and the constants the rest of capsule agrees on."""

from __future__ import annotations

import getpass
import os
import re

from capsule.paths import xdg_config

# Built-in defaults. capsule.yml overrides them: `defaults:` for every VM, `vms.<name>:` for one.
# Mappings merge key by key; `packages`, `mise` and `run` add up; other lists (mounts) and scalars replace.
# "~" and $VARS in host paths (mount source, dotfiles script, key_file) mean the host; in VM paths (mount path)
# "~" means the VM user's home.
DEFAULTS = {
    "image": "images:debian/13/cloud",
    "cpu": 4,
    "memory": "8GiB",
    "disk": "40GiB",
    "user": {
        "name": getpass.getuser(),
        "uid": os.getuid(),
        "gid": os.getgid(),
    },  # your host user: virtiofs does not remap ids
    "mounts": [],  # no host folders are shared unless you list them
    # Path of your dotbot install script on the host (arguments allowed). Its folder is found from the script's
    # location, mounted into the VM (kept, so host changes show up live) and the script runs once there. null = none.
    "dotfiles": None,
    "tailscale": {
        "key_file": str(xdg_config() / "capsule" / "tailscale-key"),
        "tag": "tag:cust-{name}",
    },  # null to skip
    "shell": "herdr",  # what `capsule <vm>` runs
    "packages": [],  # extra apt packages, added to the built-in list
    "mise": [],  # tools installed with mise: "lazygit@latest", "node@22", "github:owner/repo@1"
    "run": [],  # extra shell commands, run once as the VM user after provisioning
}


ADDITIVE = ("packages", "mise", "run")


SIZES = {"small": (2, "4GiB"), "medium": (4, "8GiB"), "large": (8, "16GiB")}


ALIASES = {"ram": "memory", "cpus": "cpu", "mem": "memory"}


MOUNT_KEYS = {"source", "path", "readonly"}


PACKAGES = ["git", "sudo", "docker.io", "build-essential", "curl", "jq", "nodejs", "npm", "ca-certificates"]


NAME_RE = re.compile(r"[a-z0-9]([a-z0-9-]{0,28}[a-z0-9])?")


RESERVE_MIB = 4096  # RAM kept free for the host
CONFIG_VERSION = 1  # the capsule.yml format this release understands; see config.load_config


COMMANDS = [
    "new",
    "add",
    "up",
    "shell",
    "ls",
    "open",
    "start",
    "stop",
    "restart",
    "snap",
    "snaps",
    "restore",
    "rebuild",
    "rm",
    "config",
    "edit",
    "doctor",
    "setup",
    "acl",
    "completion",
    "help",
]
