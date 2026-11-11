"""Loading, validating and resolving `capsule.yml` into the effective settings of one VM."""

from __future__ import annotations

import copy
import difflib
import os
import re
import shlex
from pathlib import Path
from typing import Any, Callable

import yaml

from capsule.defaults import ADDITIVE, ALIASES, CONFIG_VERSION, DEFAULTS, MOUNT_KEYS, SIZES
from capsule.errors import die
from capsule.paths import config_path
from capsule.typedefs import Mount, Settings
from capsule.units import size


def host_path(p: object) -> Path:
    return Path(os.path.expandvars(str(p))).expanduser()


def vm_path(p: object, home: str) -> str:
    p = os.path.expandvars(str(p))
    if p == "~" or p.startswith("~/"):
        p = home + p[1:]
    if not p.startswith("/"):
        die(f"'{p}' must be an absolute path or start with ~")
    return p.rstrip("/") or "/"


def merge(base: dict[str, Any], over: dict[str, Any] | None) -> dict[str, Any]:
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if k in ADDITIVE and isinstance(v, list):
            out[k] = out.get(k, []) + copy.deepcopy(v)
        elif isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def check_keys(d: dict[str, Any], schema: dict[str, Any], where: str) -> None:
    for k, v in d.items():
        if k not in schema:
            close = difflib.get_close_matches(k, schema, 1)
            die(
                f"{where}: unknown setting '{k}'" + (f". Did you mean '{close[0]}'?" if close else ""),
                f"valid settings: size, {', '.join(schema)}",
            )
        if isinstance(schema[k], dict) and isinstance(v, dict):
            check_keys(v, schema[k], f"{where}.{k}")


def layer(d: object, where: str) -> dict[str, Any]:
    """One config layer: accept aliases and shorthands, reject typos."""
    if d is None:
        return {}
    if not isinstance(d, dict):
        die(f"{where}: expected a mapping of settings")
    d = dict(d)
    for old, new in ALIASES.items():
        if old in d:
            d[new] = d.pop(old)
    if "size" in d:  # size: small|medium|large sets cpu and memory
        sz = d.pop("size")
        if sz not in SIZES:
            die(
                f"{where}.size: '{sz}' is not a size",
                f"use one of: {', '.join(f'{k} ({v[0]} CPU, {v[1]})' for k, v in SIZES.items())}",
            )
        d.setdefault("cpu", SIZES[sz][0])
        d.setdefault("memory", SIZES[sz][1])
    if isinstance(d.get("user"), str):  # user: dev  or  dev:1000  or  dev:1000:1000
        n, *ids = d["user"].split(":")
        if len(ids) > 2 or not all(i.isdigit() for i in ids):
            die(f"{where}.user: use name, name:uid or name:uid:gid")
        d["user"] = {"name": n, **dict(zip(("uid", "gid"), map(int, ids)))}
        if len(ids) == 1:
            d["user"]["gid"] = d["user"]["uid"]
    if isinstance(d.get("mise"), dict):  # mise: {lazygit: latest, node: "22"}
        d["mise"] = [f"{k}@{v}" if v else str(k) for k, v in d["mise"].items()]
    for k in ADDITIVE:  # packages: htop  ==  packages: [htop]
        if isinstance(d.get(k), str):
            d[k] = [d[k]]
    check_keys(d, DEFAULTS, where)
    return d


# Upgrades a config written for format version N to N+1, in memory (the file on disk is never rewritten).
# Add `{1: upgrade_v1_to_v2}` here when the format changes, and bump CONFIG_VERSION in defaults.py.
MIGRATIONS: dict[int, Callable[[dict[str, Any]], dict[str, Any]]] = {}


def check_version(cfg: dict[str, Any]) -> dict[str, Any]:
    """Validate the optional `version:` key (a missing key means version 1) and migrate older formats."""
    version = cfg.pop("version", 1)
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        die(f"{config_path()}: 'version' must be a whole number, 1 or higher (got {version!r})")
    if version > CONFIG_VERSION:
        die(
            f"{config_path()} uses config format version {version}, but this capsule understands up to {CONFIG_VERSION}",
            "upgrade capsule: uv tool upgrade capsule-vm",
        )
    while version < CONFIG_VERSION:
        cfg = MIGRATIONS[version](cfg)
        version += 1
    return cfg


def load_config() -> dict[str, Any]:
    """Read capsule.yml (empty if it does not exist) and check its shape. Settings are validated later, per VM."""
    if not config_path().exists():
        return {}
    try:
        cfg = yaml.safe_load(config_path().read_text()) or {}
    except yaml.YAMLError as e:
        die(f"{config_path()} is not valid YAML", str(e).replace("\n", "\n  "))
    if not isinstance(cfg, dict) or set(cfg) - {"version", "defaults", "vms"}:
        die(f"{config_path()}: top-level keys must be 'version', 'defaults' and 'vms'")
    cfg = check_version(cfg)
    if not isinstance(cfg.get("vms") or {}, dict):
        die(f"{config_path()}: 'vms' must map VM names to settings")
    return cfg


def config_vms() -> dict[str, Any]:
    return load_config().get("vms") or {}


def parse_mount(m: object, home: str, i: object) -> Mount:
    if isinstance(m, str):  # "src", "src:dest", "src:dest:ro"
        parts = m.split(":")
        ro = parts[-1] in ("ro", "rw") and len(parts) > 1 and parts.pop() == "ro"
        m = {"source": parts[0], **({"path": parts[1]} if len(parts) > 1 else {}), "readonly": ro}
    if not isinstance(m, dict) or "source" not in m or set(m) - MOUNT_KEYS:
        die(f"mounts[{i}]: use 'source', optional 'path' and 'readonly' (or the string form src:dest[:ro])")
    src = host_path(m["source"])
    if "path" in m:
        path = vm_path(m["path"], home)
    else:  # same place relative to the VM home
        try:
            path = f"{home}/{src.relative_to(Path.home())}"
        except ValueError:
            path = str(src)
    return {"source": str(src), "path": path, "readonly": bool(m.get("readonly", False))}


def covered_by(m: Mount, mounts: list[Mount]) -> bool:
    """True if an existing mount already exposes m's folder at m's path."""
    for o in mounts:
        try:
            rel = Path(m["path"]).relative_to(o["path"])
        except ValueError:
            continue
        if Path(o["source"]) / rel == Path(m["source"]):
            return True
    return False


def resolve(name: str) -> Settings:
    """Effective settings: built-in < config `defaults` < config `vms.<name>`."""
    cfg = load_config()
    c = merge(merge(DEFAULTS, layer(cfg.get("defaults"), "defaults")), layer(config_vms().get(name), f"vms.{name}"))
    u = c["user"]
    if not re.fullmatch(r"[a-z_][a-z0-9_-]{0,31}", str(u["name"])):
        die(f"invalid VM user name {u['name']!r}", "set user.name in the config: lowercase letters, digits, - and _")
    for k in ("uid", "gid"):
        if not isinstance(u[k], int) or u[k] < 1:
            die(
                f"user.{k} must be a number >= 1, got {u[k]!r}",
                "capsule copies your host user by default; set user.uid and user.gid in the config if you run it as root",
            )
    if not isinstance(c["cpu"], int) or c["cpu"] < 1:
        die(f"invalid cpu {c['cpu']!r}", "use a whole number, for example 4")
    c["memory"], c["disk"] = size(c["memory"], "memory"), size(c["disk"], "disk")
    for k in ADDITIVE:
        if not all(isinstance(x, str) for x in c[k]):
            die(f"'{k}' must be a list of strings")
    specs = {}
    for t in c["mise"]:  # "lazygit" == "lazygit@latest"; a later entry replaces an earlier one
        name, _, ver = t.rpartition("@") if "@" in t else (t, "", "latest")
        specs[name] = f"{name}@{ver or 'latest'}"
    c["mise"] = list(specs.values())
    c["home"] = home = f"/home/{u['name']}"
    c["mounts"] = [parse_mount(m, home, i) for i, m in enumerate(c["mounts"] or [])]
    if c["dotfiles"]:
        if not isinstance(c["dotfiles"], str):
            die("dotfiles must be the path of your dotbot install script", "for example: dotfiles: ~/dotfiles/install")
        script, *args = shlex.split(c["dotfiles"])  # the folder is wherever the script lives
        script = host_path(script)
        m = parse_mount({"source": str(script.parent)}, home, "dotfiles")
        c["dotfiles"] = {
            "source": m["source"],
            "path": m["path"],
            "script": script.name,
            "install": " ".join([f"./{shlex.quote(script.name)}", *map(shlex.quote, args)]),
        }
        if not covered_by(m, c["mounts"]):
            c["mounts"].append(dict(m, optional=True))  # dotfiles mount; skipped with a warning if missing
    return c
