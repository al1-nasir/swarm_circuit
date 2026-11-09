import { createServer } from "node:http";
import { resolve } from "node:path";
import { config as dotenv } from "dotenv";
import next from "next";
import WebSocket, { WebSocketServer } from "ws";
import { sameOrigin, settings } from "./lib/gateway.mjs";
import { relayFrame } from "./lib/relay.mjs";

dotenv({ path: resolve(process.cwd(), "../../.env"), quiet: true });
const port = Number(process.env.STUDIO_PORT || 3000);
const dev = process.argv.includes("--dev");
const app = next({ dev, hostname: "127.0.0.1", port, webpack: true });
await app.prepare();
const handle = app.getRequestHandler();
const server = createServer((request, response) => {
  response.setHeader("X-Content-Type-Options", "nosniff");
  response.setHeader("Referrer-Policy", "same-origin");
  response.setHeader("X-Frame-Options", "DENY");
  response.setHeader("Content-Security-Policy", "frame-ancestors 'none'");
  handle(request, response);
});
const sockets = new WebSocketServer({ noServer: true, maxPayload: 1024 });
server.on("upgrade", async (request, socket, head) => {
  const url = new URL(request.url || "/", "http://localhost");
  if (!url.pathname.startsWith("/studio-ws/")) {
    // Next installs its own HMR listener. Only this un-routed prefix belongs here.
    return;
  }
  const rid = url.pathname.slice("/studio-ws/".length);
  const after = url.searchParams.get("after");
  if (
    !sameOrigin(new Headers(request.headers), true) ||
    !/^[0-9a-f-]{36}$/i.test(rid) ||
    (after !== null && !/^\d{1,18}$/.test(after))
  ) {
    socket.end("HTTP/1.1 403 Forbidden\r\n\r\n");
    return;
  }
  try {
    const config = settings();
    const response = await fetch(
      `${config.upstream}/api/v1/runs/${rid}/stream-tickets`,
      {
        method: "POST",
        headers: { Authorization: `Bearer ${config.readToken}` },
        signal: AbortSignal.timeout(5000),
      },
    );
    if (!response.ok) throw new Error("Upgrade unavailable");
    const ticket = await response.json();
    sockets.handleUpgrade(request, socket, head, (browser) => {
      const origin = config.upstream.replace(/^http/, "ws");
      const upstream = new WebSocket(
        `${origin}/api/v1/ws/runs/${rid}${after !== null ? "?after=" + after : ""}`,
        [ticket.protocol, ticket.ticket],
        { handshakeTimeout: 5000, maxPayload: 1_048_576 },
      );
      upstream.on("message", (data, binary) => {
        relayFrame(browser, data, binary);
      });
      upstream.on("close", () =>
        browser.close(1012, "Backend stream disconnected"),
      );
      upstream.on("error", () =>
        browser.close(1013, "Backend stream unavailable"),
      );
      browser.on("message", () => browser.close(1008, "Read-only stream"));
      browser.on("close", () => upstream.close());
      browser.on("error", () => upstream.close());
    });
  } catch {
    socket.end("HTTP/1.1 503 Service Unavailable\r\n\r\n");
  }
});
server.listen(port, "127.0.0.1", () =>
  console.log(`Studio ready at http://127.0.0.1:${port}`),
);
async function shutdown() {
  for (const connection of sockets.clients)
    connection.close(1001, "Studio stopping");
  server.close();
  await app.close();
  process.exit(0);
}
process.on("SIGTERM", shutdown);
process.on("SIGINT", shutdown);
