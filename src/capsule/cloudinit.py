"""Generation of the cloud-init user-data that provisions a VM at first boot."""

from __future__ import annotations

import shlex
from pathlib import Path

import yaml

from capsule.defaults import PACKAGES
from capsule.typedefs import Settings


def user_data(c: Settings) -> str:
    u, home = c["user"]["name"], c["home"]
    run, seen = [], set()
    # Mount points: create only the parents (owned by the user inside the home), never the mounted folder itself.
    for m in c["mounts"]:
        for a in reversed(Path(m["path"]).parents):
            s = str(a)
            if s in seen or s == "/" or s == home or a in Path(home).parents:
                continue
            seen.add(s)
            run.append(
                f"install -d -o {u} -g {u} {shlex.quote(s)}"
                if Path(home) in a.parents
                else f"mkdir -p {shlex.quote(s)}"
            )

    def su(cmd):
        return f"su - {u} -c {shlex.quote(cmd)}"

    run += [
        "npm install -g @devcontainers/cli",
        su("curl -fsSL https://mise.run | sh"),
        su("curl -fsSL https://claude.ai/install.sh | bash"),
        f"install -d -o {u} -g {u} {home}/.claude",  # herdr's Claude integration writes hooks here
        "curl -fsSL https://tailscale.com/install.sh | sh",  # installed here, enrolled by `capsule new`
        "systemctl enable docker tailscaled",
        "systemctl disable --now ssh.socket ssh.service || true",  # access is Tailscale SSH or `incus exec`
    ]
    ci = {
        "groups": ["docker", "sudo"],
        "bootcmd": [
            f"getent group {u} >/dev/null || groupadd -g {c['user']['gid']} {u}"
        ],  # runs before users are created
        "users": [
            {
                "name": u,
                "uid": c["user"]["uid"],
                "primary_group": u,
                "groups": ["docker", "sudo"],
                "shell": "/bin/bash",
                "sudo": "ALL=(ALL) NOPASSWD:ALL",
                "lock_passwd": True,
            }
        ],
        "write_files": [
            {
                "path": "/etc/profile.d/capsule.sh",
                "permissions": "0644",
                "content": "# tools installed by mise (shims) and by user installers\n"
                'export PATH="$HOME/.local/share/mise/shims:$HOME/.local/bin:$PATH"\n',
            }
        ],
        "package_update": True,
        "packages": PACKAGES + [p for p in c["packages"] if p not in PACKAGES],
        "runcmd": run,
    }
    return "#cloud-config\n" + yaml.safe_dump(ci, sort_keys=False, width=10**6)
