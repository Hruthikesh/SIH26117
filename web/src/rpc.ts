/** JSON-RPC 2.0 client over the server WebSocket: calls + notification stream. */

export type NoteHandler = (method: string, params: any) => void;

export class RpcClient {
  private ws: WebSocket | null = null;
  private nextId = 1;
  private pending = new Map<number, { resolve: (v: any) => void; reject: (e: Error) => void }>();
  private queue: string[] = [];
  private closed = false;

  constructor(private readonly onNote: NoteHandler, private readonly onState?: (open: boolean) => void) {}

  connect(): void {
    const proto = location.protocol === "https:" ? "wss" : "ws";
    this.ws = new WebSocket(`${proto}://${location.host}/rpc`);
    this.ws.onopen = () => {
      this.onState?.(true);
      for (const frame of this.queue.splice(0)) this.ws?.send(frame);
    };
    this.ws.onmessage = (ev) => {
      let frame: any;
      try {
        frame = JSON.parse(ev.data);
      } catch {
        return;
      }
      if (typeof frame.id === "number" && this.pending.has(frame.id)) {
        const p = this.pending.get(frame.id)!;
        this.pending.delete(frame.id);
        if (frame.error) p.reject(new Error(frame.error.message ?? "rpc error"));
        else p.resolve(frame.result);
        return;
      }
      if (typeof frame.method === "string") this.onNote(frame.method, frame.params ?? {});
    };
    this.ws.onclose = () => {
      this.onState?.(false);
      if (!this.closed) setTimeout(() => this.connect(), 1500);
    };
  }

  call<T = any>(method: string, params: Record<string, unknown>): Promise<T> {
    const id = this.nextId++;
    const frame = JSON.stringify({ jsonrpc: "2.0", id, method, params });
    const promise = new Promise<T>((resolve, reject) => {
      this.pending.set(id, { resolve, reject });
      setTimeout(() => {
        if (this.pending.has(id)) {
          this.pending.delete(id);
          reject(new Error(`${method}: timed out`));
        }
      }, 30000);
    });
    if (this.ws && this.ws.readyState === WebSocket.OPEN) this.ws.send(frame);
    else this.queue.push(frame);
    return promise;
  }

  close(): void {
    this.closed = true;
    this.ws?.close();
  }
}
