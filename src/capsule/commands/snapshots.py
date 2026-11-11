"""Snapshot commands: snap, snaps, restore."""

from __future__ import annotations

import argparse

from capsule.errors import die
from capsule.incus import incus, instances, need_vm
from capsule.ui import confirm


def cmd_snap(a: argparse.Namespace) -> None:
    need_vm(a.name)
    incus("snapshot", "delete", a.name, a.snapname, check=False, capture=True)
    incus("snapshot", "create", a.name, a.snapname)
    print(f"Snapshot {a.name}/{a.snapname} created. Roll back with: capsule restore {a.name} {a.snapname}")


def cmd_snaps(a: argparse.Namespace) -> None:
    need_vm(a.name)
    incus("snapshot", "list", a.name)


def cmd_restore(a: argparse.Namespace) -> None:
    need_vm(a.name)
    snaps = [x["name"] for i in instances() if i["name"] == a.name for x in (i.get("snapshots") or [])]
    if a.snapname not in snaps:
        die(
            f"{a.name} has no snapshot '{a.snapname}'",
            f"available: {', '.join(snaps)}" if snaps else f"take one first: capsule snap {a.name}",
        )
    if not confirm(f"Roll {a.name} back to '{a.snapname}'? Changes since then are lost.", yes=a.yes):
        die("aborted")
    incus("snapshot", "restore", a.name, a.snapname)
