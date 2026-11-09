// Opt-in protocol tests against the running local Studio/backend; no browser automation.
import assert from "node:assert/strict";
import { test } from "node:test";
import { config as dotenv } from "dotenv";
import WebSocket from "ws";

dotenv({ path: "../../.env", quiet: true });
const studio = process.env.STUDIO_URL || "http://127.0.0.1:3000";
const backend = process.env.SWARM_API_URL || "http://127.0.0.1:8000";
const sdk = process.env.SWARM_SDK_PROJECT_TOKEN;
const project = process.env.SWARM_PROJECT_ID;
assert.ok(sdk && project, "Configure the local SDK/project environment first");
const created = await fetch(`${backend}/api/v1/projects/${project}/runs`, {
  method: "POST",
  headers: {
    Authorization: `Bearer ${sdk}`,
    "Content-Type": "application/json",
  },
  body: JSON.stringify({
    name: "Studio gateway verification",
    mode: "observe",
    simulation: true,
  }),
});
assert.equal(created.status, 201);
const run = (await created.json()).run_id;

function socket(after) {
  const ws = new WebSocket(
    studio.replace(/^http/, "ws") +
      `/studio-ws/${run}${after !== undefined ? "?after=" + after : ""}`,
    { origin: studio },
  );
  const queue = [];
  const waits = [];
  ws.on("message", (data) => {
    const value = JSON.parse(data.toString());
    const next = waits.shift();
    if (next) next(value);
    else queue.push(value);
  });
  return {
    ws,
    next: () =>
      queue.length
        ? Promise.resolve(queue.shift())
        : new Promise((resolve, reject) => {
            const timer = setTimeout(
              () => reject(new Error("Stream deadline passed")),
              8000,
            );
            waits.push((value) => {
              clearTimeout(timer);
              resolve(value);
            });
          }),
  };
}

test("Studio responses expose no backend credentials and keep the project scope", async () => {
  const response = await fetch(studio + "/api/config");
  assert.equal(response.status, 200);
  const body = await response.text();
  assert.equal(body.includes(sdk), false);
  if (process.env.SWARM_OPERATOR_TOKEN)
    assert.equal(body.includes(process.env.SWARM_OPERATOR_TOKEN), false);
  assert.equal(
    (
      await fetch(
        studio +
          "/api/backend/projects/00000000-0000-4000-8000-000000000000/runs",
      )
    ).status,
    404,
  );
});

test("live-demo capabilities expose a bounded setup without model credentials", async () => {
  const response = await fetch(
    `${studio}/api/backend/projects/${project}/demo-capabilities`,
  );
  assert.equal(response.status, 200);
  const body = await response.text();
  for (const secret of [
    sdk,
    process.env.SWARM_OPERATOR_TOKEN,
    process.env.SWARM_MODEL_API_KEY,
  ]) {
    if (secret) assert.equal(body.includes(secret), false);
  }
  const capabilities = JSON.parse(body);
  assert.equal(capabilities.fixture, true);
  assert.equal(capabilities.live.call_limit, 3);
  assert.equal(typeof capabilities.live.available, "boolean");
  assert.equal(
    (
      await fetch(
        studio +
          "/api/backend/projects/00000000-0000-4000-8000-000000000000/demo-capabilities",
      )
    ).status,
    404,
  );
});

test("live gateway rejects cross-site and privileged writes", async () => {
  for (const origin of [null, "https://untrusted.example"]) {
    const headers = {
      "Content-Type": "application/json",
      "Idempotency-Key": crypto.randomUUID(),
    };
    if (origin) headers.Origin = origin;
    const response = await fetch(
      `${studio}/api/backend/runs/${run}/control-commands`,
      { method: "POST", headers, body: "{}" },
    );
    assert.equal(response.status, 403);
  }
  for (const path of [
    `mock/runs/${run}/approvals/${run}/resolution`,
    `control-commands/${run}/ack`,
    `runs/${run}/stream-tickets`,
  ]) {
    const response = await fetch(studio + "/api/backend/" + path, {
      method: "POST",
      headers: {
        Origin: studio,
        "Content-Type": "application/json",
        "Idempotency-Key": crypto.randomUUID(),
      },
      body: "{}",
    });
    assert.equal(response.status, 404);
  }
});

test("same-origin WebSocket relays durable invalidations and reconnects without a browser credential", async () => {
  const first = socket();
  const initial = await first.next();
  assert.equal(initial.type, "snapshot_required");
  assert.equal(initial.run_id, run);
  const source = {
    event_id: crypto.randomUUID(),
    source_event_key: crypto.randomUUID(),
    event_kind: "workflow.started",
    occurred_at_ms: Date.now(),
    payload: {},
  };
  const ingest = await fetch(`${backend}/api/v1/runs/${run}/events`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${sdk}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ events: [source] }),
  });
  assert.equal(ingest.status, 200);
  const delta = await first.next();
  assert.equal(delta.type, "notifications");
  assert.ok(delta.cursor > initial.cursor);
  assert.ok(
    delta.notifications.every(
      (n) => n.run_id === run && n.payload.snapshot_required,
    ),
  );
  first.ws.close();
  const replay = socket(initial.cursor);
  const recovered = await replay.next();
  assert.equal(recovered.type, "notifications");
  assert.equal(recovered.cursor, delta.cursor);
  replay.ws.send(JSON.stringify({ command_kind: "hold_task" }));
  const code = await new Promise((resolve) => replay.ws.once("close", resolve));
  assert.equal(code, 1008);
});

test("WebSocket upgrade rejects an unrelated browser origin", async () => {
  const ws = new WebSocket(
    studio.replace(/^http/, "ws") + `/studio-ws/${run}`,
    { origin: "https://untrusted.example" },
  );
  const status = await new Promise((resolve, reject) => {
    ws.once("unexpected-response", (_, response) => {
      response.resume();
      resolve(response.statusCode);
    });
    ws.once("open", () => {
      ws.close();
      reject(new Error("Unexpected upgrade"));
    });
    ws.once("error", () => {});
  });
  assert.equal(status, 403);
});

test("research gateway serves sealed CSV but cannot launch studies", async () => {
  const plan = await fetch(
    `${studio}/api/backend/projects/${project}/experiments?limit=1`,
  );
  assert.equal(plan.status, 200);
  const selected = (await plan.json()).items[0];
  if (selected) {
    const id = selected.experiment_id;
    const csv = await fetch(
      `${studio}/api/backend/experiments/${id}/export.csv`,
    );
    assert.equal(csv.status, 200);
    assert.match(csv.headers.get("content-type"), /text\/csv/);
    assert.match(csv.headers.get("content-disposition"), /attachment/);
    assert.equal(csv.headers.get("cache-control"), "no-store");
    const text = await csv.text();
    assert.match(
      text,
      /^experiment_id,protocol_version,protocol_sha256,source_sha256,/,
    );
    assert.equal(text.includes(sdk), false);
    const trials = await fetch(
      `${studio}/api/backend/experiments/${id}/trials?limit=1`,
    );
    assert.equal(trials.status, 200);
    assert.ok((await trials.json()).items.length <= 1);
  }
  for (const path of ["experiments", `experiments/${run}/trials`]) {
    const response = await fetch(`${studio}/api/backend/${path}`, {
      method: "POST",
      headers: { Origin: studio, "Content-Type": "application/json" },
      body: "{}",
    });
    assert.equal(response.status, 404);
  }
});
