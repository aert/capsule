"""Commands that create, open, list, rebuild and delete VMs."""

from __future__ import annotations

import argparse
import difflib
import os
import shlex
import subprocess
import sys

from capsule.config import config_vms, host_path, parse_mount, resolve
from capsule.defaults import COMMANDS, NAME_RE, SIZES
from capsule.errors import CapsuleError, die
from capsule.incus import exists, incus, instances, is_running, need_vm, vm_ip, vm_user, wait_agent
from capsule.paths import config_path
from capsule.provision import create
from capsule.register import add_to_config
from capsule.ui import TTY, ask, bold, confirm, step


def guided_new() -> None:
    """`capsule new` with no name: ask the few things that matter."""
    if not sys.stdin.isatty():
        die("usage: capsule new <name> [--size small|medium|large]")
    print(bold("Let's create a VM.") + " Press Enter to accept the value in [brackets].\n")
    while True:
        name = ask("Name (lowercase letters, digits, dashes; e.g. acme)")
        if not NAME_RE.fullmatch(name):
            print("  that is not a valid name")
        elif exists(name):
            print(f"  '{name}' already exists")
        else:
            break
    c = resolve(name)
    over = {}
    sizes = ", ".join(f"{k} = {v[0]} CPU/{v[1]}" for k, v in SIZES.items())
    pick = ask(f"Size: {sizes}", f"keep config ({c['cpu']} CPU/{c['memory']})")
    if pick in SIZES:
        over["size"] = pick
    elif not pick.startswith("keep"):
        die(f"'{pick}' is not a size", "choose small, medium or large")
    extra = [m for m in c["mounts"] if m.get("optional")]
    mounts = [m for m in c["mounts"] if not m.get("optional")]
    if mounts:
        print("Host folders from your config:")
        mounts = [m for m in mounts if confirm(f"  share {m['source']}  ->  {m['path']}", default=True)]
    while True:
        folder = ask("Share another host folder with the VM? (path, or Enter for none)")
        if not folder:
            break
        if not host_path(folder).is_dir():
            print("  that folder does not exist")
            continue
        mounts.append(parse_mount(folder, c["home"], len(mounts)))
    over["mounts"] = mounts + extra
    print()
    create(name, over)


def cmd_new(a: argparse.Namespace) -> None:
    if not a.name:
        return guided_new()
    create(a.name, {"size": a.size, "cpu": a.cpu, "memory": a.memory, "disk": a.disk})


def cmd_add(a: argparse.Namespace) -> None:
    if a.name in config_vms():
        die(f"{a.name} is already listed under 'vms:' in {config_path()}", "change it with `capsule edit`")
    over = {"size": a.size, "cpu": a.cpu, "memory": a.memory, "disk": a.disk}
    if not exists(a.name) and not any(over.values()):
        print(
            f"({a.name} does not exist yet: adding it with the default settings; give --size/--cpu/--ram/--disk to record others)"
        )
    add_to_config(a.name, over)


def cmd_up(a: argparse.Namespace) -> None:
    names = a.names or list(config_vms())
    if not names:
        die("no VMs defined", f"add some under 'vms:' in {config_path()} (capsule edit), or use: capsule new <name>")
    for n in names:
        if not exists(n):
            create(n)
        elif not is_running(n):
            step(f"Starting {n}")
            incus("start", n)
        else:
            print(f"{n}: already running")


def cmd_rebuild(a: argparse.Namespace) -> None:
    """Recreate a VM from the current config. The old VM is kept, stopped, as <name>-prev."""
    need_vm(a.name)
    old = f"{a.name}-prev"
    if exists(old):
        die(f"{old} already exists", f"delete it first (capsule rm {old}) or restore it")
    c = resolve(a.name)
    cur = next((i.get("expanded_config", {}) for i in instances() if i["name"] == a.name), {})
    now, want = (cur.get("limits.cpu"), cur.get("limits.memory")), (str(c["cpu"]), c["memory"])
    if a.name not in config_vms():
        print(
            f"Note: {a.name} is not listed under 'vms:' in {config_path()}, so it is rebuilt from the defaults "
            f"(flags you gave to `capsule new` are not remembered; record them first with `capsule add {a.name}`)."
        )
    if now[0] and now != want:
        print(f"Size changes from {now[0]} CPU/{now[1]} to {want[0]} CPU/{want[1]}.")
    if not confirm(
        f"Rebuild {a.name} from your config? Its disk is replaced by a fresh one; mounted folders are untouched. "
        f"The old VM is kept stopped as {old}.",
        yes=a.yes,
    ):
        die("aborted")
    if is_running(a.name):
        step(f"Stopping {a.name}")
        incus("stop", a.name)
    incus("rename", a.name, old)
    try:
        create(a.name)
    except CapsuleError:
        print(
            f"\nRebuild failed. Your old VM is intact: capsule rm {a.name}; incus rename {old} {a.name}",
            file=sys.stderr,
        )
        raise
    print(
        f"Old VM kept as {old} (stopped). Copy anything you need from it, then: capsule rm {old}\n"
        "Remove the old Tailscale node in the admin console too."
    )


def cmd_shell(a: argparse.Namespace) -> None:
    if not exists(a.name):
        if a.name in config_vms():
            if not confirm(
                f"'{a.name}' is defined in {config_path().name} but not created yet. Create it now?", default=True
            ):
                die("aborted")
            create(a.name)
        else:
            close = difflib.get_close_matches(a.name, COMMANDS, 1)
            die(
                f"'{a.name}' is neither a command nor a VM",
                f"did you mean `capsule {close[0]}`?"
                if close
                else "see `capsule help`, or create it: capsule new " + a.name,
            )
    if not is_running(a.name):
        step(f"Starting {a.name}")
        incus("start", a.name)
        wait_agent(a.name)
    if a.cmd:
        cmd = " ".join(shlex.quote(x) for x in a.cmd)
    else:
        sh = resolve(a.name)["shell"]
        cmd = (
            f"command -v {shlex.quote(sh.split()[0])} >/dev/null && exec {sh} || "
            f"{{ echo \"capsule: '{sh}' is not installed in this VM; opening bash. "
            f"Add it under 'mise:' in your config, or change 'shell:'.\"; exec bash -l; }}"
        )
    os.execvp("incus", ["incus", "exec", a.name, "--", "su", "-l", vm_user(a.name), "-c", cmd])


def cmd_ls(_: argparse.Namespace) -> None:
    rows, seen = [], set()
    for i in instances():
        seen.add(i["name"])
        cfg = i.get("expanded_config", {})
        snaps = i.get("snapshots") or []
        rows.append(
            (
                i["name"],
                i["status"].lower(),
                vm_ip(i) or "-",
                cfg.get("limits.cpu", "-"),
                cfg.get("limits.memory", "-"),
                snaps[-1]["name"] if snaps else "-",
            )
        )
    for n in config_vms():
        if n not in seen:
            rows.append((n, "not created", "-", "-", "-", "-"))
    if not rows:
        print("No VMs yet. Create one: capsule new")
        return
    head = ("NAME", "STATE", "IP", "CPU", "RAM", "LAST SNAPSHOT")
    w = [max(len(str(r[i])) for r in rows + [head]) for i in range(6)]
    for r in [head] + rows:
        print("  ".join(str(c).ljust(w[i]) for i, c in enumerate(r)).rstrip())
    if TTY:
        print("\nOpen one: capsule <name>    Create: capsule new    Help: capsule help")


def cmd_open(a: argparse.Namespace) -> None:
    need_vm(a.name)
    ip = next((vm_ip(i) for i in instances() if i["name"] == a.name), None)
    if not a.port:
        print(f"ssh {a.name}   |   capsule {a.name}   |   open a dev server: capsule open {a.name} <port>")
        return
    dev = f"fwd-{a.port}"
    if a.unforward:
        incus("config", "device", "remove", a.name, dev, check=False, capture=True)
        print(f"Stopped forwarding localhost:{a.port} on this laptop to {a.name}.")
        return
    print(
        f"http://{a.name}:{a.port}   from any device on your tailnet\n"
        + (f"http://{ip}:{a.port}   from this laptop" if ip else "(VM has no IP: is it running?)")
    )
    print(
        f"As localhost:{a.port} on another machine (OAuth callbacks, localhost-only apps): ssh -L {a.port}:localhost:{a.port} {a.name}"
    )
    if a.forward:
        incus("config", "device", "remove", a.name, dev, check=False, capture=True)
        incus(
            "config",
            "device",
            "add",
            a.name,
            dev,
            "proxy",
            f"listen=tcp:127.0.0.1:{a.port}",
            f"connect=tcp:127.0.0.1:{a.port}",
        )
        print(
            f"Forwarding localhost:{a.port} on this laptop to {a.name}:{a.port}. Stop it with: capsule open {a.name} {a.port} --unforward"
        )
    if a.browser and ip:
        subprocess.run(["xdg-open", f"http://{ip}:{a.port}"], check=False)
    print("The server must listen on 0.0.0.0 (or 127.0.0.1 when forwarding) inside the VM.")


def cmd_power(a: argparse.Namespace) -> None:
    for n in a.names:
        need_vm(n)
        incus(a.command, n)
        print(f"{n}: {a.command} done")


def cmd_rm(a: argparse.Namespace) -> None:
    need_vm(a.name)
    i = next((x for x in instances() if x["name"] == a.name), {})
    used = ((i.get("state") or {}).get("disk") or {}).get("root", {}).get("usage")
    snaps = len(i.get("snapshots") or [])
    print(
        f"{a.name} will be deleted with {snaps} snapshot(s)"
        + (f" and {used / 2**30:.1f} GiB of data" if used else "")
        + ". Mounted host folders are not touched."
    )
    if not a.yes and input(f"Type '{a.name}' to confirm: ") != a.name:
        die("aborted")
    incus("delete", "--force", a.name)
    print(f"Deleted {a.name}. If it was on Tailscale, remove the node in the admin console.")
