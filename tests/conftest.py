"""Shared fixtures: a scratch config file and a fake `incus` executable, so no test needs real Incus."""

import stat

import pytest


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    """Point capsule at a scratch config file. Call `cfg(text)` to fill it; the returned path is the file."""
    path = tmp_path / "capsule.yml"
    monkeypatch.setenv("CAPSULE_CONFIG", str(path))

    def write(text: str):
        path.write_text(text)
        return path

    write.path = path
    return write


FAKE_INCUS = """#!/bin/sh
# Records every call in $FAKE_DIR/calls and answers just enough like incus for capsule.
printf '%s\n' "$(printf '%s' "$*" | tr '\n' ' ')" >> "$FAKE_DIR/calls"   # one line per call, even with multi-line arguments
case "$1" in
  info) [ -f "$FAKE_DIR/$2" ] && exit 0 || exit 1 ;;
  init) touch "$FAKE_DIR/$3" ;;
  list) if [ -f "$FAKE_DIR/list.json" ]; then cat "$FAKE_DIR/list.json"; else echo '[]'; fi ;;
  rename) mv "$FAKE_DIR/$2" "$FAKE_DIR/$3" ;;
  exec)
    case "$*" in
      *"id -u"*) id -u ;;
      *"id -g"*) id -g ;;
      *"cloud-init status"*) echo "status: done"; echo "all good" ;;
    esac ;;
esac
exit 0
"""


class FakeIncus:
    """Handle on the fake `incus`: `calls` returns what capsule ran; `vm_exists`/`list_json` set the world."""

    def __init__(self, directory):
        self.dir = directory

    @property
    def calls(self) -> list[str]:
        file = self.dir / "calls"
        return file.read_text().splitlines() if file.exists() else []

    def vm_exists(self, name: str) -> None:
        (self.dir / name).touch()

    def list_json(self, text: str) -> None:
        (self.dir / "list.json").write_text(text)


@pytest.fixture
def fake_incus(tmp_path, monkeypatch):
    """Put a fake `incus` first on PATH and return a FakeIncus to inspect it."""
    state = tmp_path / "incus-state"
    state.mkdir()
    script = tmp_path / "bin" / "incus"
    script.parent.mkdir()
    script.write_text(FAKE_INCUS)
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{script.parent}:/usr/bin:/bin")
    monkeypatch.setenv("FAKE_DIR", str(state))
    monkeypatch.delenv("TS_AUTHKEY", raising=False)
    return FakeIncus(state)
