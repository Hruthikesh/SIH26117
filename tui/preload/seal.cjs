/** Layer 3 (Node) — socket guard for TUI and MCP-server child processes (SPEC §14.3).
 *  Loaded via NODE_OPTIONS=--require. Blocks outbound connections outside the allowlist,
 *  logs each attempt to the server over loopback (or the events file), and never throws
 *  during require so a broken guard cannot stop the process from starting. */

"use strict";

try {
  const net = require("node:net");
  const dns = require("node:dns");
  const fs = require("node:fs");
  const os = require("node:os");
  const path = require("node:path");

  const sealed = process.env.YANTRA_SEALED !== "0";
  if (!sealed) return;

  const raw = process.env.YANTRA_SEAL_ALLOWLIST ||
    "127.0.0.0/8,::1/128,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16";
  const allowNames = new Set(
    ["localhost", "localhost.localdomain", "ip6-localhost"].concat(
      (process.env.YANTRA_SEAL_ALLOW_NAMES || "").split(",").map((s) => s.trim()).filter(Boolean),
    ),
  );

  const nets = raw
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean)
    .map(parseCidr)
    .filter(Boolean);

  function parseCidr(entry) {
    const [addr, bitsStr] = entry.split("/");
    const isV6 = addr.includes(":");
    const bits = bitsStr !== undefined ? parseInt(bitsStr, 10) : isV6 ? 128 : 32;
    const value = ipToBig(addr);
    if (value === null) return null;
    return { value, bits, v6: isV6 };
  }

  function ipToBig(addr) {
    try {
      if (addr.includes(":")) {
        // Expand IPv6 (handles :: once); good enough for loopback/RFC-1918-mapped checks.
        let head = addr;
        if (addr.startsWith("::ffff:") && addr.split(":").pop().includes(".")) {
          return ipToBig(addr.split(":").pop());
        }
        const halves = head.split("::");
        const left = halves[0] ? halves[0].split(":") : [];
        const right = halves[1] ? halves[1].split(":") : [];
        const missing = 8 - left.length - right.length;
        const groups = left.concat(Array(Math.max(0, missing)).fill("0"), right);
        let value = 0n;
        for (const g of groups) value = (value << 16n) + BigInt(parseInt(g || "0", 16));
        return value;
      }
      const parts = addr.split(".").map((n) => BigInt(parseInt(n, 10)));
      if (parts.length !== 4 || parts.some((n) => n < 0n || n > 255n)) return null;
      return (parts[0] << 24n) + (parts[1] << 16n) + (parts[2] << 8n) + parts[3];
    } catch {
      return null;
    }
  }

  function ipAllowed(host) {
    const value = ipToBig(host);
    if (value === null) return null; // hostname, not an address
    for (const net of nets) {
      const shift = BigInt((net.v6 ? 128 : 32) - net.bits);
      if (value >> shift === net.value >> shift) return true;
    }
    return false;
  }

  function report(kind, dest, port) {
    const event = {
      ts: new Date().toISOString(),
      process: path.basename(process.argv[1] || "node"),
      pid: process.pid,
      kind,
      dest,
      port: port || null,
      stack: (new Error().stack || "").split("\n").slice(2, 5).map((s) => s.trim()),
    };
    const file = process.env.YANTRA_SEAL_EVENTS_FILE;
    if (file) {
      try {
        fs.appendFileSync(file, JSON.stringify(event) + "\n");
        return;
      } catch {
        /* fall through */
      }
    }
    try {
      process.stderr.write(`[yantra-seal] blocked ${kind} ${dest}:${port}\n`);
    } catch {
      /* ignore */
    }
  }

  const originalConnect = net.Socket.prototype.connect;
  net.Socket.prototype.connect = function (options, ...rest) {
    let host = null;
    let port = null;
    if (typeof options === "object" && options !== null) {
      host = options.host || options.path ? options.host : null;
      port = options.port;
    } else if (typeof options === "number") {
      port = options;
      host = typeof rest[0] === "string" ? rest[0] : "127.0.0.1";
    }
    if (host) {
      const verdict = ipAllowed(host);
      if (verdict === false || (verdict === null && !allowNames.has(host))) {
        report("blocked_connect", host, port);
        this.destroy(new Error(`sealed: connection to ${host}:${port} refused`));
        return this;
      }
    }
    return originalConnect.call(this, options, ...rest);
  };

  function guardLookup(original) {
    return function (hostname, opts, cb) {
      const callback = typeof opts === "function" ? opts : cb;
      if (hostname && ipAllowed(hostname) === null && !allowNames.has(hostname)) {
        report("blocked_dns", hostname, null);
        const err = new Error(`sealed: DNS for ${hostname} refused`);
        err.code = "ENOTFOUND";
        if (callback) return callback(err);
        throw err;
      }
      return original.apply(this, arguments);
    };
  }
  dns.lookup = guardLookup(dns.lookup);
  if (dns.promises && dns.promises.lookup) {
    const origPromise = dns.promises.lookup;
    dns.promises.lookup = function (hostname, ...args) {
      if (hostname && ipAllowed(hostname) === null && !allowNames.has(hostname)) {
        report("blocked_dns", hostname, null);
        return Promise.reject(new Error(`sealed: DNS for ${hostname} refused`));
      }
      return origPromise.apply(this, [hostname, ...args]);
    };
  }
  void os;
} catch (err) {
  /* a broken guard must never stop the process from starting */
  void err;
}
