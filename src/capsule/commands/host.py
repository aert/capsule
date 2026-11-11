"""Host-level commands: setup, doctor and the Tailscale ACL generator."""

from __future__ import annotations

import argparse
import getpass
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from capsule.config import config_vms, host_path, load_config, resolve
from capsule.defaults import DEFAULTS, RESERVE_MIB
from capsule.errors import CapsuleError, die
from capsule.incus import incus
from capsule.paths import config_path
from capsule.provision import id_warning
from capsule.ui import green, step, warn
from capsule.units import host_mem_mib, to_mib

PRESEED = """\
config: {}
networks:
  - name: incusbr0
    type: bridge
    config: {ipv4.address: 10.77.0.1/24, ipv4.nat: "true", ipv6.address: none}
storage_pools:
  - name: default
    driver: dir
profiles:
  - name: default
    devices:
      eth0: {name: eth0, network: incusbr0, type: nic}
      root: {path: /, pool: default, type: disk}
"""


OS_RELEASE = Path("/etc/os-release")
MIN_DEBIAN = 13
MIN_UBUNTU = (24, 4)


def host_os_problem(path: Path = OS_RELEASE) -> str | None:
    """None when the host is Debian 13+, Ubuntu 24.04+ or a derivative; else why it is unsupported (a warning, never a block)."""
    try:
        text = path.read_text()
    except OSError:
        return f"cannot read {path}, so the host distribution is unknown"
    info = {}
    for line in text.splitlines():
        key, sep, value = line.partition("=")
        if sep:
            info[key.strip()] = value.strip().strip("\"'")
    ident, like = info.get("ID", ""), info.get("ID_LIKE", "").split()
    name = info.get("PRETTY_NAME") or ident or "unknown"
    version = info.get("VERSION_ID", "")
    if ident == "debian":
        major = version.split(".")[0]
        if major.isdigit() and int(major) < MIN_DEBIAN:
            return f"{name} is older than Debian {MIN_DEBIAN} (its repositories have no incus package; bookworm only has it in backports)"
        return None  # Debian testing/sid has no VERSION_ID: assume recent
    if ident == "ubuntu":
        try:
            if tuple(int(x) for x in version.split(".")[:2]) < MIN_UBUNTU:
                return f"{name} is older than Ubuntu 24.04 (its repositories have no incus package)"
        except ValueError:
            pass
        return None
    if "debian" in like or "ubuntu" in like:
        return None  # derivative (Pop!_OS, Mint, ...): version numbers differ, so let apt decide
    return f"{name} is not Debian or Ubuntu based; capsule setup uses apt"


def cmd_setup(_: argparse.Namespace) -> None:
    """One-time host setup: packages, incus-admin group, storage pool and bridge."""

    def sudo(*args, **kw):
        if subprocess.run(["sudo", *args], text=True, **kw).returncode != 0:
            die(
                f"'{' '.join(args)}' failed",
                "if apt cannot find a package, see the Incus install docs for a repository (zabbly)",
            )

    if not shutil.which("sudo"):
        die("sudo is not installed", "as root: apt-get install sudo && usermod -aG sudo <you>, then log in again")
    problem = host_os_problem()
    if problem:
        warn(f"{problem}. Continuing; setup may fail. Supported: Debian {MIN_DEBIAN}+, Ubuntu 24.04+ and derivatives")
    step("Checking virtualisation")
    sudo("apt-get", "install", "-y", "cpu-checker")
    sudo("kvm-ok")
    if shutil.which("docker"):
        warn(
            "Docker is installed on the host; it breaks VM networking. Remove it, or allow the bridge: "
            "sudo iptables -I DOCKER-USER -i incusbr0 -j ACCEPT && "
            "sudo iptables -I DOCKER-USER -o incusbr0 -m conntrack --ctstate RELATED,ESTABLISHED -j ACCEPT"
        )
    step("Installing incus")
    sudo("apt-get", "install", "-y", "incus", "virtiofsd")
    sudo("usermod", "-aG", "incus-admin", getpass.getuser())
    if subprocess.run(["sudo", "incus", "network", "show", "incusbr0"], capture_output=True).returncode == 0:
        step("Incus already initialised")
    else:
        step("Initialising incus (storage pool 'default', bridge incusbr0 on 10.77.0.0/24)")
        sudo("incus", "admin", "init", "--preseed", input=PRESEED)
    print(f"\n{green('✓')} Done. Log out and in again (group change), then: capsule new")


def cmd_doctor(_: argparse.Namespace) -> int:
    """Check the host, the config and the VMs; every problem comes with its fix."""
    bad = [0]

    def ok(m):
        print(f"  {green('ok')}    {m}")

    def meh(m, fix=""):
        print(f"  warn  {m}" + (f"\n        fix: {fix}" if fix else ""))

    def no(m, fix):
        bad[0] = 1
        print(f"  FAIL  {m}\n        fix: {fix}")

    print("Host")
    problem = host_os_problem()
    if problem:
        meh(problem, "supported: Debian 13+, Ubuntu 24.04+ and derivatives; install incus by hand if you know it works")
    else:
        ok("Debian/Ubuntu based host")
    if Path("/dev/kvm").exists():
        ok("/dev/kvm present")
    else:
        no("/dev/kvm missing", "enable VT-x/AMD-V in the firmware, then `capsule setup`")
    if not shutil.which("incus"):
        no("incus is not installed", "capsule setup")
    elif incus("list", "-f", "csv", "-c", "n", check=False, capture=True).returncode == 0:
        ok("incus installed and reachable")
    else:
        no("cannot talk to incus", "capsule setup, then log out and in (incus-admin group)")
    if shutil.which("docker"):
        meh(
            "Docker is installed on the host (it breaks VM networking)",
            "remove it, or see `capsule setup` for the iptables rules",
        )
    try:
        free = shutil.disk_usage("/var/lib/incus" if Path("/var/lib/incus").exists() else "/").free / 2**30
        if free >= 50:
            ok(f"{free:.0f} GiB free disk")
        else:
            meh(
                f"only {free:.0f} GiB free disk (a VM takes {DEFAULTS['disk']} by default)",
                "free space or lower 'disk'",
            )
    except OSError:
        pass

    print("Config")
    try:
        load_config()
        cfgs = {n or "(defaults)": resolve(n or "<name>") for n in [None, *config_vms()]}
        ok(f"{config_path()} " + ("is valid" if config_path().exists() else "will be created on first use"))
    except CapsuleError as error:
        no(f"config is invalid: {error}" + (f" ({error.hint})" if error.hint else ""), "capsule edit")
        return 1
    seen = set()
    for n, c in cfgs.items():
        for m in c["mounts"]:
            if m["source"] in seen:
                continue
            seen.add(m["source"])
            if Path(m["source"]).is_dir():
                ok(f"mount source {m['source']}")
            elif m.get("optional"):
                meh(
                    f"dotfiles folder {m['source']} missing (dotfiles will be skipped)",
                    "create it or set 'dotfiles' in the config",
                )
            else:
                no(
                    f"mount source {m['source']} missing (used by {n})",
                    f"mkdir -p {m['source']}, or remove it from 'mounts'",
                )
        u = c["user"]
        if id_warning(u) and n == "(defaults)":
            meh(
                id_warning(u)[0].upper() + id_warning(u)[1:],
                "set user.uid and user.gid (for example to 1000) in the config",
            )
        if c["mounts"] and (u["uid"], u["gid"]) != (os.getuid(), os.getgid()):
            meh(
                f"{n}: VM user {u['name']}:{u['uid']}:{u['gid']} differs from you ({os.getuid()}:{os.getgid()}): "
                "mounted files will show wrong ownership",
                "remove 'user' from the config to copy yourself",
            )
    keyfiles = {c["tailscale"]["key_file"] for c in cfgs.values() if c["tailscale"]}
    if keyfiles:
        if os.environ.get("TS_AUTHKEY") or any(host_path(k).is_file() for k in keyfiles):
            ok("Tailscale key available")
        else:
            meh(
                "no Tailscale key: new VMs will not join your tailnet",
                f"save an OAuth client secret in {sorted(keyfiles)[0]} (mode 600) or export TS_AUTHKEY",
            )
    total = host_mem_mib()
    defined = sum(to_mib(c["memory"]) for n, c in cfgs.items() if n != "(defaults)")
    if total and defined > total - RESERVE_MIB:
        meh(
            f"VMs in your config reserve {defined / 1024:.0f} GiB RAM in total, host has {total / 1024:.0f} GiB: "
            "they cannot all run at once",
            "use size: small, lower 'ram', or keep some VMs stopped",
        )
    print("\n" + (green("All good.") if not bad[0] else "Fix the FAIL items above."))
    return bad[0]


def cmd_acl(_: argparse.Namespace) -> None:
    """Print the Tailscale policy fragment for the VMs in the config (merge it into your tailnet policy by hand)."""
    names = list(config_vms()) or ["acme"]
    tags, users = [], set()
    for n in names:
        c = resolve(n)
        if c["tailscale"]:
            tags.append(c["tailscale"]["tag"].replace("{name}", n))
            users.add(c["user"]["name"])
    if not tags:
        die("no VM has Tailscale enabled")
    policy = {
        "tagOwners": {t: ["autogroup:admin"] for t in tags},
        "acls": [{"action": "accept", "src": ["autogroup:member"], "dst": [f"{t}:*" for t in tags]}],
        "ssh": [{"action": "accept", "src": ["autogroup:member"], "dst": tags, "users": sorted(users)}],
    }
    print(
        "// Tailscale policy fragment for your VMs. Merge into your tailnet policy; do not paste over it.\n"
        "// Your devices reach every VM; no rule lets a tag:cust-* node reach anything, so VMs are isolated\n"
        "// from each other and from your devices. With an OAuth client allowed to apply tag:cust-*, you\n"
        '// can skip tagOwners. Add "tcp:<port>" destinations if you restrict ports.'
    )
    print(json.dumps(policy, indent=2))
    if not config_vms():
        print("// (no vms: in your config, so 'acme' is an example; run again after adding yours)", file=sys.stderr)
