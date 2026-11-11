"""Thin wrapper around the `incus` command line client and helpers to query VMs."""

from __future__ import annotations

import difflib
import json
import subprocess
import time
from typing import Any

from capsule.config import resolve
from capsule.errors import die
from capsule.typedefs import Settings


def incus(*args: object, check: bool = True, capture: bool = False) -> subprocess.CompletedProcess[str]:
    r = subprocess.run(["incus", *map(str, args)], text=True, capture_output=capture)
    if check and r.returncode != 0:
        die(f"'incus {args[0]}' failed" + (f": {r.stderr.strip()}" if capture else ""))
    return r


def exists(vm: str) -> bool:
    return incus("info", vm, check=False, capture=True).returncode == 0


def instances() -> list[dict[str, Any]]:
    return json.loads(incus("list", "-f", "json", capture=True).stdout or "[]")


def need_vm(vm: str) -> None:
    if exists(vm):
        return
    names = [i["name"] for i in instances()]
    close = difflib.get_close_matches(vm, names, 1)
    die(
        f"no VM named '{vm}'",
        f"did you mean '{close[0]}'?" if close else "see `capsule ls`, or create it: capsule new " + vm,
    )


def is_running(vm: str) -> bool:
    return incus("list", vm, "-f", "csv", "-c", "s", capture=True).stdout.strip() == "RUNNING"


def vm_user(vm: str) -> str:
    r = incus("config", "get", vm, "user.capsule.user", capture=True, check=False)
    return r.stdout.strip() or resolve(vm)["user"]["name"]


def vm_ip(i: dict[str, Any]) -> str | None:
    nets = (i.get("state") or {}).get("network") or {}
    return next(
        (
            x["address"]
            for n, v in nets.items()
            if n != "tailscale0"
            for x in v["addresses"]
            if x["family"] == "inet" and x["scope"] == "global"
        ),
        None,
    )


def wait_agent(vm: str) -> None:
    for _ in range(90):
        if incus("exec", vm, "--", "true", check=False, capture=True).returncode == 0:
            return
        time.sleep(2)
    die(f"{vm} did not become ready in time", f"check: incus info {vm}")


def as_user(vm: str, c: Settings, cmd: str, cwd: str | None = None) -> subprocess.CompletedProcess[str]:
    args = [
        "exec",
        vm,
        "--user",
        str(c["user"]["uid"]),
        "--group",
        str(c["user"]["gid"]),
        "--env",
        f"HOME={c['home']}",
    ] + (["--cwd", cwd] if cwd else [])
    return incus(*args, "--", "bash", "-lc", cmd, check=False)
