import pytest

from capsule import register
from capsule.config import resolve
from capsule.errors import CapsuleError


@pytest.fixture(autouse=True)
def vm_does_not_exist(monkeypatch):
    monkeypatch.setattr(register, "exists", lambda name: False)


def test_add_keeps_comments_and_layout(cfg):
    cfg("# my config\ndefaults: {size: medium}\n\nvms:\n  # examples\n  # x: {}\n")
    register.add_to_config("acme", {"size": "large"})
    text = cfg.path.read_text()
    assert text.startswith("# my config\n")
    assert "  # examples\n" in text
    assert text.rstrip().endswith("acme: {size: large}")
    assert resolve("acme")["cpu"] == 8


def test_add_creates_the_vms_section_and_refuses_duplicates(cfg):
    cfg("defaults: {disk: 50GiB}\n")
    register.add_to_config("one", {"cpu": "2"})
    assert "vms:\n  one:" in cfg.path.read_text()
    with pytest.raises(CapsuleError, match="already listed"):
        register.add_to_config("one", {})


def test_add_inserts_into_a_vms_block_that_comes_first(cfg):
    cfg("vms:\n  x: {size: small}\ndefaults: {disk: 50GiB}\n")
    register.add_to_config("y", {"size": "large"})
    assert cfg.path.read_text() == "vms:\n  x: {size: small}\n  y: {size: large}\ndefaults: {disk: 50GiB}\n"


def test_add_replaces_an_empty_inline_vms(cfg):
    cfg("vms: {}\n")
    register.add_to_config("one", {"size": "small"})
    assert cfg.path.read_text() == "vms:\n  one: {size: small}\n"


def test_add_refuses_an_inline_vms_with_entries(cfg):
    cfg("vms: {x: {}}\n")
    with pytest.raises(CapsuleError, match="inline"):
        register.add_to_config("y", {})


def test_a_result_that_does_not_validate_is_rolled_back(cfg):
    original = cfg("vms:\n  x: {size: small}\n")
    with pytest.raises(CapsuleError):
        register.add_to_config("y", {"disk": "lots"})
    assert original.read_text() == "vms:\n  x: {size: small}\n"
