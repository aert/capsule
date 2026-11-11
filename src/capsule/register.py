"""Recording a VM's settings in `capsule.yml` (`capsule add`) without disturbing the file."""

from __future__ import annotations

import re
from typing import Any

import yaml

from capsule.config import config_vms, resolve
from capsule.defaults import SIZES
from capsule.errors import CapsuleError, die
from capsule.incus import exists, instances
from capsule.paths import config_path
from capsule.typedefs import Settings
from capsule.units import size


def config_entry(name: str, c: Settings, over: dict[str, Any]) -> dict[str, Any]:
    """Settings worth recording for a VM: only what differs from the defaults (or what the flags set)."""
    base = resolve(name)
    entry = {}
    cpu, mem = int(over.get("cpu") or c["cpu"]), size(over.get("memory") or c["memory"], "memory")
    if (cpu, mem) != (base["cpu"], base["memory"]):
        preset = next((k for k, v in SIZES.items() if v == (cpu, mem)), None)
        entry.update({"size": preset} if preset else {"cpu": cpu, "ram": mem})
    disk = size(over.get("disk") or c["disk"], "disk")
    if disk != base["disk"]:
        entry["disk"] = disk
    if c["user"]["name"] != base["user"]["name"]:
        entry["user"] = c["user"]["name"]
    want = {(m["source"], m["path"], m["readonly"]) for m in c["mounts"] if not m.get("optional")}
    have = {(m["source"], m["path"], m["readonly"]) for m in base["mounts"] if not m.get("optional")}
    if want != have:
        entry["mounts"] = [f"{src}:{path}" + (":ro" if ro else "") for src, path, ro in sorted(want)]
    return entry


def instance_settings(name: str) -> Settings:
    """Reconstruct the settings of an existing VM from Incus (limits, root size, mounts, user)."""
    i = next(x for x in instances() if x["name"] == name)
    cfg = i.get("expanded_config", {})
    c = resolve(name)
    c["cpu"] = int(cfg.get("limits.cpu", c["cpu"]))
    c["memory"] = cfg.get("limits.memory", c["memory"])
    c["disk"] = ((i.get("expanded_devices") or {}).get("root") or {}).get("size", c["disk"])
    c["user"] = dict(c["user"], name=cfg.get("user.capsule.user", c["user"]["name"]))
    dm = c["dotfiles"] and (c["dotfiles"]["source"], c["dotfiles"]["path"])
    c["mounts"] = [
        {"source": d["source"], "path": d["path"], "readonly": d.get("readonly") in (True, "true")}
        for d in (i.get("expanded_devices") or {}).values()
        if d.get("type") == "disk" and d.get("source") and (d["source"], d["path"]) != dm
    ]
    return c


def add_to_config(name: str, over: dict[str, Any] | None = None) -> None:
    """Append `name` under `vms:` in capsule.yml, keeping the file's comments and layout."""
    if name in config_vms():
        die(f"{name} is already listed under 'vms:' in {config_path()}")
    over = over or {}
    if exists(name) and not any(over.values()):
        entry = config_entry(name, instance_settings(name), {})
    else:
        c = resolve(name)
        if over.get("size"):
            c["cpu"], c["memory"] = SIZES[over["size"]]
        entry = config_entry(name, c, {k: v for k, v in over.items() if k != "size"})
    flow = yaml.safe_dump(entry, default_flow_style=True, width=10**6).strip() if entry else "{}"
    line = f"  {name}: {flow}\n"
    text = config_path().read_text() if config_path().exists() else ""
    lines = text.splitlines(keepends=True)
    start = next((n for n, text_line in enumerate(lines) if re.match(r"vms\s*:", text_line)), None)
    if start is None:
        new = text + ("" if not text or text.endswith("\n") else "\n") + "\nvms:\n" + line
    elif re.match(r"vms\s*:\s*(\{\s*\})?\s*(#.*)?$", lines[start]):
        end = next(
            (n for n in range(start + 1, len(lines)) if re.match(r"\S", lines[n]) and not lines[n].startswith("#")),
            len(lines),
        )
        while end > start + 1 and not lines[end - 1].strip():
            end -= 1
        lines[start] = re.sub(r"\{\s*\}", "", lines[start]).rstrip() + "\n" if "{" in lines[start] else lines[start]
        new = "".join(lines[:end] + [line] + lines[end:])
    else:
        die(f"'vms:' in {config_path()} is written inline", f"add this under it by hand:  {name}: {flow}")
    config_path().write_text(new)
    try:
        resolve(name)
    except CapsuleError:
        config_path().write_text(text)
        raise
    print(f"Added {name} to {config_path()}: {flow}")
