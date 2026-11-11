# capsule

A CLI that creates and manages one Incus VM per project, configured by one YAML file (`~/.config/capsule.yml`). Python package `capsule-vm` (command `capsule`), installed with `uv tool install`. Docs: `README.md` (users, workflow, config reference, risks, first-run checklist) and `CONTRIBUTING.md` (architecture, ADRs, conventions, recipes). Read CONTRIBUTING.md before changing structure.

## Status
Unit-tested, never verified end to end on real hardware. Do not claim otherwise. Supported hosts: Debian 13+ and Ubuntu 24.04+ and derivatives (apt); `host.host_os_problem()` warns, never blocks (ADR 15). Only Pop!_OS 24.04 was used by the maintainer. There is no Incus on the dev machine (a Mac): flows that call `incus` are tested with a fake `incus` script (see `tests/conftest.py`).

## Commands you will use
```bash
uv sync                                   # set up .venv
uv run pytest -q                          # all tests (about 2 s)
uv run pytest tests/test_config.py -k mise   # one test
uvx ruff check . && uvx ruff format .     # lint + format (CI checks both)
CAPSULE_CONFIG=/tmp/c.yml uv run capsule config acme   # exercise the CLI; ALWAYS set CAPSULE_CONFIG
uv run --python 3.9 pytest -q             # check the oldest supported Python
uv build                                  # wheel + sdist into dist/
```

## Layout (`src/capsule/`)
`errors` `paths` `defaults` `units` `ui` `typedefs` (leaf modules) -> `config` (load/validate/`resolve(name)`) -> `incus` (CLI wrapper) -> `cloudinit` (user-data), `register` (`capsule add`), `provision` (`create()` pipeline), `scaffold` (first-run config) -> `commands/{vms,snapshots,host,settings,completion}.py` (one `cmd_<name>(args)` per subcommand) -> `cli` (HELP, parser, `run`, `main`). Lower layers never import higher ones. Diagrams and the per-module table are in CONTRIBUTING.md.

Tests: `tests/test_{config,cloudinit,register,units,cli,provision}.py`; fixtures `cfg` (scratch config) and `fake_incus` in `conftest.py`.

## Rules of the road
- **Errors:** `die(message, hint)` raises `CapsuleError`; only `cli.main()` prints it and exits 1. Never call `sys.exit` elsewhere. The hint should carry the fix.
- **One source of truth:** a VM's effective settings come only from `config.resolve(name)`. Do not read `capsule.yml` elsewhere to decide behaviour.
- **Config format:** `version:` in `capsule.yml` (missing = 1); `config.check_version` + `MIGRATIONS`. Prefer adding optional settings; a breaking change needs `CONFIG_VERSION` bumped and a migration (see CONTRIBUTING.md).
- **Config path:** always `paths.config_path()` (reads `$CAPSULE_CONFIG` each call), never a module-level constant.
- **Prompts** only when `sys.stdin.isatty()`; scripts must not hang. Output via `ui.step/warn/confirm/ask`.
- **Python 3.9+** at runtime (`from __future__ import annotations` is on, so `X | None` in annotations is fine, but not in runtime expressions).
- **Traps:** `cmd_shell` ends in `os.execvp` (replaces the process; never reach it in a test). The first run writes a config file. The fake `incus` must exit non-zero for unknown VMs (`info`).
- A new command needs its name in `defaults.COMMANDS`, a subparser in `cli.build_parser`, a line in `cli.HELP` (a test enforces they agree). A new setting needs `DEFAULTS`, `config.layer/resolve`, `scaffold.sample`, the README settings table and a test. Full recipes: CONTRIBUTING.md.

## Principles (changing them needs the maintainer's say-so)
- Simple and ergonomic: instinctive commands, friendly errors with the fix, strict config validation (unknown keys are errors).
- No template/clone flow (cloud-init provisions each VM), no secrets management, no blocking resource guards (warn, do not refuse), no settings knobs beyond `capsule.yml`.
- Mounts are opt-in; only the dotbot folder is mounted automatically when `dotfiles:` is set. The VM user copies the host user (virtiofs does not remap ids). `capsule acl` only prints the Tailscale policy.
- herdr here is the terminal UI (TUI) from herdr.dev, not a desktop app; it is installed via `mise:`.
- Starter config tools: apt `neovim tig btop`; mise `lazygit herdr github:can1357/oh-my-pi` (all global, `mise use -g`).

## Before you finish
Run pytest and ruff; update README.md (keep its Mermaid diagrams valid) and, for design changes, add or amend an ADR in CONTRIBUTING.md. Never put secrets in the repo. Commit only when asked.
