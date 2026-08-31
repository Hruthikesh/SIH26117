/** JSON-RPC 2.0 WebSocket client with reconnect and per-run seq replay. */

import WebSocket from "ws";
import { EventEmitter } from "node:events";
import type { NotificationMap, NotificationMethod, RequestParamsMap, RpcMethod } from "./generated.js";

interface PendingCall {
  resolve: (value: unknown) => void;
  reject: (err: Error) => void;
  timer: NodeJS.Timeout;
}

export interface RpcErrorShape {
  code: number;
  message: string;
  data?: unknown;
}

export class RpcCallError extends Error {
  readonly code: number;
  readonly data: unknown;
  constructor(err: RpcErrorShape) {
    super(err.message);
    this.code = err.code;
    this.data = err.data;
  }
}

export type ConnectionState = "connecting" | "open" | "closed" | "reconnecting";

export class RpcClient extends EventEmitter {
  private ws: WebSocket | null = null;
  private nextId = 1;
  private pending = new Map<number, PendingCall>();
  private lastSeq = new Map<string, number>();
  private closedByUser = false;
  private backoffMs = 500;
  state: ConnectionState = "connecting";

  constructor(
    readonly url: string,
    private readonly requestTimeoutMs = 300_000,
  ) {
    super();
  }

  connect(): void {
    this.closedByUser = false;
    this.state = this.state === "closed" ? "reconnecting" : "connecting";
    this.emit("state", this.state);
    const ws = new WebSocket(this.url);
    this.ws = ws;

    ws.on("open", () => {
      this.state = "open";
      this.backoffMs = 500;
      this.emit("state", this.state);
    });

    ws.on("message", (data: WebSocket.RawData) => {
      let frame: Record<string, unknown>;
      try {
        frame = JSON.parse(data.toString()) as Record<string, unknown>;
      } catch {
        return;
      }
      if (typeof frame["id"] === "number") {
        const call = this.pending.get(frame["id"]);
        if (!call) return;
        this.pending.delete(frame["id"]);
        clearTimeout(call.timer);
        if (frame["error"]) call.reject(new RpcCallError(frame["error"] as RpcErrorShape));
        else call.resolve(frame["result"]);
        return;
      }
      const method = frame["method"];
      if (typeof method === "string") {
        const params = (frame["params"] ?? {}) as { run_id?: string | null; seq?: number };
        if (params.run_id && typeof params.seq === "number") {
          const seen = this.lastSeq.get(params.run_id) ?? 0;
          if (params.seq <= seen) return; // replay duplicate
          this.lastSeq.set(params.run_id, params.seq);
        }
        this.emit("notification", method, params);
        this.emit(`n:${method}`, params);
      }
    });

    const onDown = () => {
      if (this.state === "closed") return;
      this.state = "closed";
      this.emit("state", this.state);
      for (const [id, call] of this.pending) {
        clearTimeout(call.timer);
        call.reject(new Error("connection lost"));
        this.pending.delete(id);
      }
      if (!this.closedByUser) {
        setTimeout(() => this.connect(), this.backoffMs);
        this.backoffMs = Math.min(this.backoffMs * 2, 10_000);
      }
    };
    ws.on("close", onDown);
    ws.on("error", onDown);
  }

  lastSeqFor(runId: string): number {
    return this.lastSeq.get(runId) ?? 0;
  }

  onNotification<M extends NotificationMethod>(
    method: M,
    handler: (params: NotificationMap[M]) => void,
  ): () => void {
    const key = `n:${method}`;
    this.on(key, handler);
    return () => this.off(key, handler);
  }

  call<M extends RpcMethod>(method: M, params: RequestParamsMap[M]): Promise<unknown> {
    return new Promise((resolve, reject) => {
      if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
        reject(new Error(`not connected (${this.state})`));
        return;
      }
      const id = this.nextId++;
      const timer = setTimeout(() => {
        this.pending.delete(id);
        reject(new Error(`rpc timeout: ${method}`));
      }, this.requestTimeoutMs);
      this.pending.set(id, { resolve, reject, timer });
      this.ws.send(JSON.stringify({ jsonrpc: "2.0", id, method, params }));
    });
  }

  close(): void {
    this.closedByUser = true;
    this.ws?.close();
  }
}
