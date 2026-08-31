# 0007 — One user-facing `yantra` command, two implementations

**Status:** accepted (M0).

**Context.** SPEC §19.1: the Node binary `yantra` launches the TUI and proxies other
subcommands to the Python CLI; the Python package also needs a headless entry point. Two
packages cannot both own one PATH name cleanly in a dev venv.

**Decision.** The Python console script `yantra` (Typer) is canonical and headless-complete;
invoked with no subcommand it execs the TUI (`node <tui>/dist/index.js`), located via
`YANTRA_TUI_PATH` or the repo/bundle layout. The Node bin (installed by `install.sh` as the
system `yantra`) does the inverse: runs the TUI and proxies unknown subcommands to
`python -m yantra_server.cli`. Either entry point gives the full surface.

**Consequences.** No PATH conflicts in practice; headless hosts need only the wheel, TUI-first
installs need only the Node bin plus the venv.
