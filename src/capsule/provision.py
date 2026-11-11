"""Creating a VM end to end: validation, `incus init`, boot, tools, dotfiles, mise, Tailscale."""

from __future__ import annotations

import os
import re
import shlex
import shutil
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

from capsule.cloudinit import user_data
from capsule.config import config_vms, covered_by, host_path, resolve
from capsule.defaults import COMMANDS, NAME_RE, RESERVE_MIB, SIZES
from capsule.errors import CapsuleError, die
from capsule.incus import as_user, exists, incus, instances, wait_agent
from capsule.paths import config_path
from capsule.register import add_to_config
from capsule.typedefs import Settings
from capsule.ui import TTY, bold, confirm, green, step, warn
from capsule.units import host_mem_mib, size, to_mib


def wait_provision(vm: str) -> None:
    """Wait for cloud-init, showing elapsed time and the latest install log line."""
    start, last = time.time(), 0.0
    while time.time() - start < 1800:
        r = incus(
            "exec",
            vm,
            "--",
            "sh",
            "-c",
            "cloud-init status 2>&1 | head -n 1; tail -n 1 /var/log/cloud-init-output.log 2>/dev/null",
            check=False,
            capture=True,
        )
        lines = r.stdout.splitlines()
        status = lines[0].replace("status:", "").strip() if lines else ""
        if TTY:
            print("\r\033[K", end="")
        if status.startswith("error"):
            die(f"provisioning failed in {vm}", f"read the log: incus exec {vm} -- cat /var/log/cloud-init-output.log")
        if status.startswith(("done", "degraded")):
            if status.startswith("degraded"):
                warn(f"provisioning in {vm} finished with recoverable errors; see /var/log/cloud-init-output.log")
            return
        elapsed = int(time.time() - start)
        tail = re.sub(r"[^\x20-\x7e]", "", lines[1] if len(lines) > 1 else "")
        msg = f"  [{elapsed // 60}:{elapsed % 60:02d}] {tail}"[: max(20, shutil.get_terminal_size().columns - 1)]
        if TTY:
            print(msg, end="", flush=True)
        elif time.time() - last > 30:
            print(msg, flush=True)
            last = time.time()
        time.sleep(3)
    die(
        f"provisioning of {vm} is taking over 30 minutes",
        f"check: incus exec {vm} -- tail -f /var/log/cloud-init-output.log",
    )


def ram_warning(new_mib: float) -> None:
    total = host_mem_mib()
    if not total:
        return
    used = sum(
        to_mib(i.get("expanded_config", {}).get("limits.memory", 0)) for i in instances() if i["status"] == "Running"
    )
    if used + new_mib > total - RESERVE_MIB:
        warn(
            f"running VMs have {used / 1024:.0f} GiB of RAM reserved; adding {new_mib / 1024:.0f} GiB exceeds the "
            f"{(total - RESERVE_MIB) / 1024:.0f} GiB budget (host {total / 1024:.0f} GiB minus {RESERVE_MIB // 1024} GiB). "
            "Stop a VM or use a smaller size."
        )


def id_warning(user: dict[str, Any]) -> str:
    """uid/gid below 1000 can collide with system accounts and groups in the Debian image (20 = dialout, 33 = www-data...)."""
    low = [f"{k} {user[k]}" for k in ("uid", "gid") if user[k] < 1000]
    return (
        (
            f"the VM user's {' and '.join(low)} are in the system range (below 1000) and may collide with an account or "
            "group in the Debian image; files on mounts could show the wrong owner"
        )
        if low
        else ""
    )


def tailscale_key(c: Settings) -> str:
    kf = host_path(c["tailscale"]["key_file"])
    return os.environ.get("TS_AUTHKEY") or (kf.read_text().strip() if kf.is_file() else "")


def create(name: str, over: dict[str, Any] | None = None) -> None:
    if not NAME_RE.fullmatch(name):
        die(f"invalid VM name '{name}'", "use lowercase letters, digits and dashes (for example: acme-web)")
    if name in COMMANDS or name == "sh":
        die(f"'{name}' is a capsule command, so `capsule {name}` could never open that VM", "pick another name")
    if exists(name):
        die(f"{name} already exists", f"open it: capsule {name}")
    c = resolve(name)
    over = dict(over or {})
    if over.get("size"):
        c["cpu"], c["memory"] = SIZES[over.pop("size")]
    if "mounts" in over:  # the guided flow may drop some (or all) configured mounts
        c["mounts"] = [m for m in over.pop("mounts") if not m.get("optional")]
        if c["dotfiles"]:  # the dotbot folder must stay mounted whatever else was dropped
            dm = {"source": c["dotfiles"]["source"], "path": c["dotfiles"]["path"], "readonly": False}
            if not covered_by(dm, c["mounts"]):
                c["mounts"].append(dict(dm, optional=True))
    c.update({k: v for k, v in over.items() if v})
    c["cpu"], c["memory"], c["disk"] = int(c["cpu"]), size(c["memory"], "memory"), size(c["disk"], "disk")
    for m in list(c["mounts"]):
        if Path(m["source"]).is_dir():
            continue
        if not m.get("optional"):
            die(
                f"mount source {m['source']} does not exist on this machine",
                f"create it, or change 'mounts' in {config_path()}",
            )
        warn(
            f"dotfiles folder {m['source']} does not exist: no dotfiles for {name} (set 'dotfiles' in {config_path()})"
        )
        c["mounts"].remove(m)
        c["dotfiles"] = None
    df = c["dotfiles"]
    if df and not (Path(df["source"]) / df["script"]).is_file():
        warn(
            f"dotfiles script {Path(df['source']) / df['script']} not found: no dotfiles for {name} (set 'dotfiles' in {config_path()})"
        )
        c["mounts"] = [m for m in c["mounts"] if not (m.get("optional") and m["source"] == df["source"])]
        c["dotfiles"] = None
    u = c["user"]["name"]
    if c["mounts"] and (c["user"]["uid"], c["user"]["gid"]) != (os.getuid(), os.getgid()):
        warn(
            f"you are {os.getuid()}:{os.getgid()} but the VM user is {c['user']['uid']}:{c['user']['gid']}: "
            "files on mounts will show wrong ownership"
        )
    ram_warning(to_mib(c["memory"]))
    if id_warning(c["user"]):
        warn(id_warning(c["user"]))
    if c["tailscale"] and not tailscale_key(c):
        warn(
            f"no Tailscale key (put one in {host_path(c['tailscale']['key_file'])} or export TS_AUTHKEY): "
            f"{name} would not join your tailnet. See the README, section 2."
        )
        if sys.stdin.isatty() and not confirm(
            "Create the VM anyway (reachable only with `capsule " + name + "`)?", default=True
        ):
            die("aborted: add the Tailscale key, then run the command again")

    step(
        f"Creating {bold(name)}: {c['cpu']} CPU, {c['memory']} RAM, {c['disk']} disk, "
        f"user {u}:{c['user']['uid']}:{c['user']['gid']}, {len(c['mounts'])} mount(s)"
    )
    incus(
        "init",
        c["image"],
        name,
        "--vm",
        "-p",
        "default",
        "-c",
        f"limits.cpu={c['cpu']}",
        "-c",
        f"limits.memory={c['memory']}",
        "-c",
        f"cloud-init.user-data={user_data(c)}",
        "-c",
        f"user.capsule.user={u}",
        "-d",
        f"root,size={c['disk']}",
    )
    try:
        provision(name, c)
    except (CapsuleError, KeyboardInterrupt):
        print(
            f"\nThe half-built VM was kept so you can inspect it (incus exec {name} -- bash). "
            f"Remove it with `capsule rm {name}`, then retry.",
            file=sys.stderr,
        )
        raise


def provision(name: str, c: Settings) -> None:
    """Everything after the VM exists: mounts, boot, tools, dotfiles, mise, Tailscale."""
    u = c["user"]["name"]
    for m in c["mounts"]:
        dev = "mount-" + (re.sub(r"[^a-zA-Z0-9]+", "-", m["path"]).strip("-") or "root")
        incus(
            "config",
            "device",
            "add",
            name,
            dev,
            "disk",
            f"source={m['source']}",
            f"path={m['path']}",
            *(["readonly=true"] if m["readonly"] else []),
        )

    step(
        f"Booting and installing tools (a few minutes; everything: incus exec {name} -- tail -f /var/log/cloud-init-output.log)"
    )
    incus("start", name)
    wait_agent(name)
    wait_provision(name)
    if incus("exec", name, "--", "id", "-u", u, capture=True).stdout.strip() != str(c["user"]["uid"]):
        die(f"user {u} did not get uid {c['user']['uid']} (the image may ship its own user with that uid)")
    got = incus("exec", name, "--", "id", "-g", u, capture=True).stdout.strip()
    if got != str(c["user"]["gid"]):
        warn(
            f"user {u} got gid {got} instead of {c['user']['gid']} (that gid is probably used by a system group in the "
            "image): files on mounts will show the wrong group. Set user.gid to a free number, such as 1000, in the config."
        )

    df = c["dotfiles"]
    if df:
        step(f"Running dotbot ({df['install']} in {df['path']})")
        if as_user(name, c, df["install"], cwd=df["path"]).returncode != 0:
            warn(
                f"the dotfiles install command failed; check 'dotfiles' in {config_path()}, "
                f"then run it by hand: capsule {name} 'cd {df['path']} && {df['install']}'"
            )
    for spec in c["mise"]:
        step(f"Installing {spec} with mise")
        if as_user(name, c, f"mise use -g -y {shlex.quote(spec)}").returncode != 0:
            warn(
                f"mise could not install '{spec}': check the name with `mise registry`, or use a backend such as "
                f"github:owner/repo ('mise' in {config_path()})"
            )
    as_user(
        name, c, "command -v herdr >/dev/null && herdr integration install claude"
    )  # herdr's Claude hook, if herdr is installed
    for cmd in c["run"]:
        step(f"Running: {cmd}")
        if as_user(name, c, cmd).returncode != 0:
            warn(f"command failed: {cmd}")

    reach = f"capsule {name}"
    ts = c["tailscale"]
    if ts:
        key = tailscale_key(c)
        if key:
            tag = ts["tag"].replace("{name}", name)
            step(f"Joining Tailscale as {tag}")
            with tempfile.NamedTemporaryFile("w") as f:  # created with mode 600
                f.write(key)
                f.flush()
                incus("file", "push", "--mode", "600", f.name, f"{name}/run/ts-authkey")
            incus(
                "exec",
                name,
                "--",
                "tailscale",
                "up",
                "--auth-key=file:/run/ts-authkey",
                f"--hostname={name}",
                f"--advertise-tags={tag}",
                "--ssh",
            )
            incus("exec", name, "--", "rm", "-f", "/run/ts-authkey")
            reach = f"ssh {name}   (from any device on your tailnet)\n    capsule {name}   (from this laptop)"
        else:
            print(
                f"(not on your tailnet; later, in the VM: tailscale up --ssh --advertise-tags={ts['tag'].replace('{name}', name)})"
            )
    print(f"\n{green('✓')} {bold(name)} is ready:\n    {reach}")
    offer_to_record = name not in config_vms() and sys.stdin.isatty()
    if offer_to_record and confirm(
        f"\nAdd {name} to {config_path().name} so `capsule up` and `capsule rebuild` keep its settings?",
        default=True,
    ):
        add_to_config(name)
