import pytest

from capsule.config import resolve
from capsule.errors import CapsuleError


def test_defaults_without_a_config_file(cfg):
    c = resolve("acme")
    assert (c["cpu"], c["memory"], c["disk"]) == (4, "8GiB", "40GiB")
    assert c["mounts"] == []
    assert c["dotfiles"] is None


def test_size_preset_and_explicit_override(cfg):
    cfg("defaults: {size: large}\nvms:\n  a: {size: small}\n  b: {ram: 6}\n")
    assert (resolve("x")["cpu"], resolve("x")["memory"]) == (8, "16GiB")
    assert (resolve("a")["cpu"], resolve("a")["memory"]) == (2, "4GiB")
    assert resolve("b")["memory"] == "6GiB"  # an explicit ram beats the inherited size


def test_packages_mise_and_run_add_up(cfg):
    cfg(
        "defaults: {packages: [htop], mise: [lazygit@latest, node], run: [echo hi]}\n"
        "vms:\n  a: {packages: tmux, mise: {lazygit: '0.44.1'}, run: [echo bye]}\n"
    )
    c = resolve("a")
    assert c["packages"] == ["htop", "tmux"]
    assert c["mise"] == ["lazygit@0.44.1", "node@latest"]  # a later entry wins; a bare name means latest
    assert c["run"] == ["echo hi", "echo bye"]


def test_typos_are_errors_with_a_suggestion(cfg):
    cfg("vms:\n  a: {cpuu: 2}\n")
    with pytest.raises(CapsuleError, match="Did you mean 'cpu'"):
        resolve("a")


def test_invalid_yaml_and_unknown_top_level_keys(cfg):
    cfg("defaults: [unclosed\n")
    with pytest.raises(CapsuleError, match="not valid YAML"):
        resolve("a")
    cfg("hosts: {}\n")
    with pytest.raises(CapsuleError, match="top-level keys"):
        resolve("a")


def test_user_shorthand(cfg):
    cfg("vms:\n  a: {user: 'dev:1500'}\n  b: {user: 'dev:1500:1600'}\n")
    assert resolve("a")["user"] == {"name": "dev", "uid": 1500, "gid": 1500}
    assert resolve("b")["user"] == {"name": "dev", "uid": 1500, "gid": 1600}


def test_mount_forms(cfg, tmp_path):
    src = tmp_path / "docs"
    cfg(
        f"defaults:\n  user: dev:1000:1000\n  mounts: ['{src}:/mnt/docs:ro', '{src}', {{source: '{src}', path: '~/d'}}]\n"
    )
    m = resolve("a")["mounts"]
    assert m[0] == {"source": str(src), "path": "/mnt/docs", "readonly": True}
    assert m[1]["path"] == str(src)
    assert not m[1]["readonly"]
    assert m[2]["path"] == "/home/dev/d"


def test_dotfiles_folder_comes_from_the_script_path(cfg, tmp_path):
    script = tmp_path / "dots" / "install"
    cfg(f"defaults:\n  user: dev:1000:1000\n  dotfiles: '{script} -c my.yaml'\n")
    c = resolve("a")
    assert c["dotfiles"]["source"] == str(tmp_path / "dots")
    assert c["dotfiles"]["install"] == "./install -c my.yaml"
    assert c["mounts"][-1]["optional"]
    assert c["mounts"][-1]["source"] == str(tmp_path / "dots")


def test_dotfiles_not_mounted_twice_when_inside_another_mount(cfg, tmp_path):
    script = tmp_path / "code" / "dots" / "install"
    cfg(f"defaults:\n  user: dev:1000:1000\n  mounts: ['{tmp_path / 'code'}']\n  dotfiles: '{script}'\n")
    assert len(resolve("a")["mounts"]) == 1


def test_dotfiles_must_be_a_path(cfg):
    cfg("defaults: {dotfiles: {source: x}}\n")
    with pytest.raises(CapsuleError, match="dotbot install script"):
        resolve("a")


def test_config_version_is_optional_and_checked(cfg):
    cfg("defaults: {size: small}\n")  # no version means 1
    assert resolve("a")["cpu"] == 2
    cfg("version: 1\ndefaults: {size: small}\n")
    assert resolve("a")["cpu"] == 2
    cfg("version: 2\n")
    with pytest.raises(CapsuleError, match="up to 1") as error:
        resolve("a")
    assert "uv tool upgrade" in error.value.hint
    for bad in ("version: '1'\n", "version: 0\n", "version: true\n"):
        cfg(bad)
        with pytest.raises(CapsuleError, match="'version'"):
            resolve("a")


def test_older_formats_are_migrated_in_memory(cfg, monkeypatch):
    from capsule import config

    monkeypatch.setattr(config, "CONFIG_VERSION", 2)
    monkeypatch.setitem(config.MIGRATIONS, 1, lambda raw: {**raw, "defaults": {"size": "large"}})
    cfg("version: 1\n")
    assert resolve("a")["cpu"] == 8
    assert "size" not in cfg.path.read_text()  # the file on disk is untouched


def test_the_generated_starter_config_is_valid(cfg):
    from capsule.scaffold import ensure_config

    ensure_config()
    assert cfg.path.read_text().startswith("# capsule config")
    assert "version: 1" in cfg.path.read_text()
    c = resolve("acme")  # must resolve without errors
    assert c["mise"][:2] == ["lazygit@latest", "herdr@latest"]
    assert "neovim" in c["packages"]
