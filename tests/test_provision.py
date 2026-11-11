"""`create` against the fake incus: checks what capsule asks Incus to do, not Incus itself."""

import pytest

from capsule.errors import CapsuleError
from capsule.provision import create


def init_call(fake_incus) -> str:
    return next(call for call in fake_incus.calls if call.startswith("init "))


def test_create_builds_the_vm_from_the_config(cfg, fake_incus, tmp_path):
    folder = tmp_path / "proj"
    folder.mkdir()
    cfg(
        f"defaults:\n  size: small\n  disk: 30GiB\n  tailscale: null\n  mounts: ['{folder}:/work:ro']\n  mise: [lazygit@latest]\n  run: ['echo done']\n"
    )
    create("acme")
    init = init_call(fake_incus)
    assert "limits.cpu=2" in init
    assert "limits.memory=4GiB" in init
    assert "root,size=30GiB" in init
    assert f"config device add acme mount-work disk source={folder} path=/work readonly=true" in fake_incus.calls
    assert any("mise use -g -y lazygit@latest" in call for call in fake_incus.calls)
    assert any("echo done" in call for call in fake_incus.calls)


def test_flags_override_the_config_and_mounts_can_be_dropped(cfg, fake_incus, tmp_path):
    folder = tmp_path / "proj"
    folder.mkdir()
    cfg(f"defaults:\n  tailscale: null\n  mounts: ['{folder}']\n")
    create("acme", {"size": "large", "mounts": []})
    assert "limits.cpu=8" in init_call(fake_incus)
    assert not any("device add" in call for call in fake_incus.calls)


def test_a_missing_dotfiles_folder_only_warns(cfg, fake_incus, tmp_path, capsys):
    cfg(f"defaults:\n  tailscale: null\n  dotfiles: {tmp_path}/nowhere/install\n")
    create("acme")
    assert "no dotfiles" in capsys.readouterr().err
    assert not any("device add" in call for call in fake_incus.calls)


def test_a_missing_mount_source_stops_before_creating_anything(cfg, fake_incus, tmp_path):
    cfg(f"defaults:\n  mounts: ['{tmp_path}/nowhere']\n")
    with pytest.raises(CapsuleError, match="does not exist"):
        create("acme")
    assert not any(call.startswith("init ") for call in fake_incus.calls)


def test_names_that_shadow_commands_or_exist_are_refused(cfg, fake_incus):
    with pytest.raises(CapsuleError, match="capsule command"):
        create("ls")
    fake_incus.vm_exists("acme")
    with pytest.raises(CapsuleError, match="already exists"):
        create("acme")


def test_a_failed_build_keeps_the_vm_and_says_so(cfg, fake_incus, monkeypatch, capsys):
    cfg("defaults:\n  tailscale: null\n")
    monkeypatch.setattr("capsule.provision.provision", lambda name, c: (_ for _ in ()).throw(CapsuleError("boom")))
    with pytest.raises(CapsuleError):
        create("acme")
    assert "capsule rm acme" in capsys.readouterr().err
