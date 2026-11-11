import argparse

import pytest

from capsule import cli
from capsule.defaults import COMMANDS
from capsule.errors import CapsuleError, die


def subcommands() -> set[str]:
    parser = cli.build_parser()
    action = next(a for a in parser._actions if isinstance(a, argparse._SubParsersAction))
    return set(action.choices)


def test_every_command_name_is_a_subcommand_and_vice_versa():
    assert subcommands() - {"_complete"} == set(COMMANDS) - {"help"}


def test_no_arguments_means_ls_and_a_vm_name_means_shell():
    assert cli.normalise_argv([]) == ["ls"]
    assert cli.normalise_argv(["acme"]) == ["shell", "acme"]
    assert cli.normalise_argv(["acme", "ls", "-la"]) == ["shell", "acme", "ls", "-la"]
    assert cli.normalise_argv(["new", "acme"]) == ["new", "acme"]


def test_help_prints_and_stops(capsys, cfg):
    assert cli.normalise_argv(["help"]) is None
    assert cli.normalise_argv(["new", "--help"]) is None
    assert "Everyday" in capsys.readouterr().out


def test_failures_become_a_message_hint_and_exit_status_one(monkeypatch, capsys):
    monkeypatch.setattr(cli, "run", lambda argv: die("it broke", "try again"))
    with pytest.raises(SystemExit) as exit_info:
        cli.main()
    assert exit_info.value.code == 1
    assert capsys.readouterr().err == "capsule: it broke\n  try again\n"


def test_capsule_error_carries_its_hint():
    with pytest.raises(CapsuleError) as error:
        die("message", "hint")
    assert (str(error.value), error.value.hint) == ("message", "hint")


def test_unknown_names_suggest_the_closest_command(cfg, fake_incus, monkeypatch, capsys):
    monkeypatch.setattr(cli.os, "getuid", lambda: 1000)
    monkeypatch.setattr("sys.argv", ["capsule", "lss"])
    fake_incus.list_json("[]")
    with pytest.raises(SystemExit):
        cli.main()
    assert "did you mean `capsule ls`" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("text", "bad"),
    [
        ('ID=debian\nVERSION_ID="13"\n', False),
        ('ID=debian\nVERSION_ID="12"\n', True),
        ("ID=debian\n", False),
        ('ID=ubuntu\nVERSION_ID="24.04"\n', False),
        ('ID=ubuntu\nVERSION_ID="22.04"\n', True),
        ('ID=pop\nID_LIKE="ubuntu debian"\nVERSION_ID="24.04"\n', False),
        ('ID=linuxmint\nID_LIKE="ubuntu debian"\nVERSION_ID="22"\n', False),
        ('ID=fedora\nVERSION_ID="41"\n', True),
    ],
)
def test_host_os_problem(tmp_path, text, bad):
    from capsule.commands.host import host_os_problem

    f = tmp_path / "os-release"
    f.write_text(text)
    assert bool(host_os_problem(f)) is bad
    assert host_os_problem(tmp_path / "missing")
