#!/usr/bin/env node
/** `yantra` TUI entry. Subcommands are proxied to the Python CLI (ADR 0007). */

import React from "react";
import { render } from "ink";
import { spawnSync } from "node:child_process";
import process from "node:process";
import { App } from "./app.js";
import { RpcClient } from "./rpc/client.js";

const argv = process.argv.slice(2);

if (argv.length > 0 && argv[0] !== "tui") {
  // Proxy `yantra <subcommand> …` to the Python CLI.
  const python = process.env["YANTRA_PYTHON"] ?? "python";
  const result = spawnSync(python, ["-m", "yantra_server.cli", ...argv], {
    stdio: "inherit",
  });
  process.exit(result.status ?? 1);
}

const url = process.env["YANTRA_SERVER_URL"] ?? "ws://127.0.0.1:7331/rpc";
const client = new RpcClient(url);
client.connect();

const { waitUntilExit } = render(
  <App client={client} workspace={process.cwd()} />,
  { exitOnCtrlC: false },
);

await waitUntilExit();
client.close();
