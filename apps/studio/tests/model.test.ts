import assert from "node:assert/strict";
import { test } from "node:test";
import {
  closure,
  commandLabel,
  confirmed,
  layout,
  mergePage,
  spanDuration,
} from "../lib/model.ts";
import { allowedPath, sameOrigin, settings, forward } from "../lib/gateway.mjs";
import type { Command, Evidence, Graph } from "../lib/types.ts";
import {
  demoDecisionBody,
  demoDecisionHash,
  demoHeadline,
  demoStartBody,
  demoRestoreStartBody,
  demoReviewLabel,
} from "../lib/demo.ts";

const root = "11111111-1111-4111-8111-111111111111";
test("an uncertain start restores its original mode instead of the current picker", () => {
  assert.equal(demoStartBody("fixture"), "{}");
  assert.equal(demoStartBody("live"), '{"mode":"live"}');
  const liveIntent = { key: root, body: demoStartBody("live") };
  assert.equal(demoRestoreStartBody(liveIntent), '{"mode":"live"}');
  assert.equal(demoRestoreStartBody({ key: root }), "{}");
  assert.equal(
    demoRestoreStartBody({ key: root, body: '{"mode":"unknown"}' }),
    null,
  );
  assert.equal(
    demoRestoreStartBody({
      key: root,
      body: '{"mode":"live","call_limit":999}',
    }),
    null,
  );
  assert.equal(demoRestoreStartBody({ key: root, body: "invalid" }), null);
});
test("a repaired handoff is not presented as having a second model review", () => {
  assert.match(
    demoReviewLabel({ review_status: "repaired" }),
    /no second model review/,
  );
  assert.match(
    demoReviewLabel({ review_status: "rejected" }),
    /no checked brief published/,
  );
  assert.match(demoReviewLabel({ review_status: "draft" }), /review pending/);
});
test("terminal live handoffs do not pretend a writer or review is still pending", () => {
  assert.equal(
    demoReviewLabel({ review_status: "not_started" }, true),
    "No checked model draft was produced",
  );
  assert.equal(
    demoReviewLabel({ review_status: "draft" }, true),
    "Draft retained; the handoff did not finish",
  );
  assert.match(
    demoReviewLabel({ review_status: "repaired" }, true),
    /no second model review/,
  );
});
test("a recovered demo decision must preserve its exact reviewed content", async () => {
  const original = demoDecisionBody("approved", "  Use the local sample.  ");
  assert.equal(
    original,
    '{"decision":"approved","reason":"Use the local sample."}',
  );
  const fingerprint = await demoDecisionHash(original);
  assert.match(fingerprint, /^[0-9a-f]{64}$/);
  assert.equal(
    await demoDecisionHash(
      demoDecisionBody("approved", "Use the local sample."),
    ),
    fingerprint,
  );
  assert.notEqual(
    await demoDecisionHash(demoDecisionBody("denied", "Use the local sample.")),
    fingerprint,
  );
  assert.notEqual(
    await demoDecisionHash(demoDecisionBody("approved", "Use another sample.")),
    fingerprint,
  );
});
test("the walkthrough names completed public work and preserves explicit operator pauses", () => {
  const waiting = {
    state: "waiting",
    permission: "pending",
    active_holds: 0,
    public_completed: true,
  } as const;
  assert.equal(
    demoHeadline(waiting),
    "Public findings are ready. Dataset access needs your review.",
  );
  assert.equal(
    demoHeadline({ ...waiting, permission: "approved", active_holds: 4 }),
    "Some tasks are paused by an operator.",
  );
  assert.equal(
    demoHeadline({ ...waiting, state: "denied", active_holds: 4 }),
    "Access denied. Public findings are still available.",
  );
});
test("read-only configuration blocks control before contacting the backend", async () => {
  const old = process.env.SWARM_STUDIO_READ_ONLY;
  process.env.SWARM_STUDIO_READ_ONLY = "true";
  try {
    assert.equal(settings().operatorToken, "");
    const result = await forward(
      new Request(
        `http://127.0.0.1:3300/api/backend/runs/${root}/control-commands`,
        {
          method: "POST",
          headers: {
            Host: "127.0.0.1:3300",
            Origin: "http://127.0.0.1:3300",
            "Content-Type": "application/json",
          },
          body: "{}",
        },
      ),
      ["runs", root, "control-commands"],
    );
    assert.equal(result.status, 403);
    assert.equal((await result.json()).code, "read_only");
  } finally {
    if (old === undefined) delete process.env.SWARM_STUDIO_READ_ONLY;
    else process.env.SWARM_STUDIO_READ_ONLY = old;
  }
  assert.throws(
    () =>
      settings({ ...process.env, SWARM_API_URL: "https://untrusted.example" }),
    /loopback/,
  );
});
const graph: Graph = {
  nodes: ["root", "child", "independent"].map((id) => ({
    id,
    label: id,
    node_kind: "task",
    evidence_kind: "explicit",
  })),
  edges: [
    {
      id: "e",
      source: "child",
      target: "root",
      relation_kind: "depends_on",
      evidence_kind: "explicit",
    },
  ],
  projection_version: 1,
  coverage: "explicit",
};
test("impact follows explicit reverse dependency closure and preserves independent branches", () => {
  assert.deepEqual([...closure(graph, "root")].sort(), ["child", "root"]);
  assert.deepEqual(
    [
      ...closure(
        { ...graph, edges: [{ ...graph.edges[0], evidence_kind: "inferred" }] },
        "root",
      ),
    ],
    ["root"],
  );
});
test("cyclic graph layout terminates and does not change orchestration data", () => {
  const cyclic = {
    ...graph,
    edges: [
      ...graph.edges,
      { ...graph.edges[0], id: "reverse", source: "root", target: "child" },
    ],
  };
  const before = JSON.stringify(cyclic);
  const positions = layout(cyclic);
  assert.equal(positions.length, 3);
  assert.equal(
    new Set(positions.map((n) => JSON.stringify(n.position))).size,
    3,
  );
  assert.equal(JSON.stringify(cyclic), before);
});
test("span duration keeps nanoseconds exact before computing display milliseconds", () => {
  assert.equal(
    spanDuration({
      start_unix_ns: "1793600000000000000",
      end_unix_ns: "1793600000000000001",
    } as Evidence),
    0.000001,
  );
});
test("an applied label requires matching runtime ACK and fencing epoch", () => {
  const command = {
    state: "applied",
    runtime_session_id: "session",
    session_fencing_epoch: 2,
    acknowledgements: [
      {
        result: "applied",
        runtime_session_id: "session",
        session_fencing_epoch: 1,
      },
    ],
  } as Command;
  assert.equal(confirmed(command), false);
  assert.match(commandLabel(command), /confirmation missing/);
  assert.match(commandLabel({ ...command, state: "queued" }), /Queued/);
  command.acknowledgements[0].session_fencing_epoch = 2;
  assert.equal(confirmed(command), true);
});
test("refresh preserves exhausted older cursors, updates records and exposes gaps", () => {
  const old = {
    items: [
      { id: "a", state: "queued" },
      { id: "b", state: "applied" },
    ],
    next_cursor: null,
  };
  const merged = mergePage(
    old,
    { items: [{ id: "a", state: "applied" }], next_cursor: "duplicate-page" },
    (i) => i.id,
  );
  assert.equal(merged.next_cursor, null);
  assert.equal(merged.items[0].state, "applied");
  const gap = mergePage(
    old,
    { items: [{ id: "new", state: "queued" }], next_cursor: "fill-gap" },
    (i) => i.id,
  );
  assert.equal(gap.next_cursor, "fill-gap");
  assert.equal(gap.items.length, 3);
});
test("gateway disallows runtime ACK, approval, payment and arbitrary upstream writes", () => {
  assert.equal(
    allowedPath(["runs", root, "control-commands"], "POST", root),
    `/api/v1/runs/${root}/control-commands`,
  );
  for (const path of [
    ["control-commands", root, "ack"],
    ["runs", root, "events"],
    ["mock", "runs", root, "approvals", root, "resolution"],
    ["runtime-sessions", root, "heartbeat"],
    ["https:", "evil.example"],
  ])
    assert.equal(allowedPath(path, "POST", root), null);
  assert.equal(allowedPath(["projects", "other", "runs"], "GET", root), null);
});
test("gateway requires the local origin for writes and rejects cross-site or DNS-rebinding hosts", () => {
  assert.equal(
    sameOrigin(
      new Headers({ host: "127.0.0.1:3300", origin: "http://127.0.0.1:3300" }),
      true,
    ),
    true,
  );
  for (const headers of [
    { host: "127.0.0.1:3300" },
    { host: "127.0.0.1:3300", origin: "https://evil.example" },
    { host: "evil.example", origin: "http://evil.example" },
    {
      host: "127.0.0.1:3300",
      origin: "http://127.0.0.1:3300",
      "sec-fetch-site": "cross-site",
    },
  ])
    assert.equal(
      sameOrigin(new Headers(headers as Record<string, string>), true),
      false,
    );
});

test("continuous notifications coalesce without postponing the first refresh", async () => {
  const { createInvalidator } = await import("../lib/invalidation.ts");
  let pending: (() => void) | undefined;
  let scheduled = 0,
    runs = 0,
    cancelled = 0;
  const flush = createInvalidator(
    () => runs++,
    (callback) => {
      scheduled++;
      pending = callback;
      return () => {
        pending = undefined;
        cancelled++;
      };
    },
  );
  for (let i = 0; i < 50; i++) flush.schedule();
  assert.equal(scheduled, 1);
  pending!();
  assert.equal(runs, 1);
  flush.schedule();
  assert.equal(scheduled, 2);
  flush.cancel();
  assert.equal(cancelled, 1);
  assert.equal(pending, undefined);
});
test("slow WebSocket consumers reconnect instead of growing the relay buffer", async () => {
  const { relayFrame } = await import("../lib/relay.mjs");
  const sent: unknown[] = [];
  const closed: unknown[] = [];
  const socket = {
    readyState: 1,
    bufferedAmount: 0,
    send: (data: unknown) => sent.push(data),
    close: (code: number) => closed.push(code),
  };
  assert.equal(relayFrame(socket, Buffer.alloc(8), false, 16), true);
  socket.bufferedAmount = 12;
  assert.equal(relayFrame(socket, Buffer.alloc(8), false, 16), false);
  assert.equal(sent.length, 1);
  assert.deepEqual(closed, [1013]);
});
test("ELK routes prerequisites before dependents without mutating declared evidence", async () => {
  const { arrangeGraph } = await import("../lib/graph-layout.ts");
  const before = JSON.stringify(graph);
  const result = await arrangeGraph(graph);
  const positions = new Map(result.nodes.map((n) => [n.id, n.position]));
  assert.ok(positions.get("root")!.x < positions.get("child")!.x);
  assert.ok(result.routes.e.length >= 2);
  assert.equal(JSON.stringify(graph), before);
  const { flowDirection } = await import("../lib/graph-geometry.ts");
  assert.deepEqual(flowDirection(graph.edges[0]), {
    source: "root",
    target: "child",
  });
});

test("research gateway permits scoped evidence downloads and reviewed policy requests, but never experiment execution", () => {
  const id = "00000000-0000-4000-8000-000000000001";
  assert.equal(
    allowedPath(["experiments", id, "results"], "GET", id),
    `/api/v1/experiments/${id}/results`,
  );
  assert.equal(
    allowedPath(["experiments", id, "export.csv"], "GET", id),
    `/api/v1/experiments/${id}/export.csv`,
  );
  assert.equal(
    allowedPath(["experiments", id, "trials", id, "truth.jsonl"], "GET", id),
    `/api/v1/experiments/${id}/trials/${id}/truth.jsonl`,
  );
  assert.equal(
    allowedPath(["experiments", id, "trials", id, "secrets.json"], "GET", id),
    null,
  );
  assert.equal(allowedPath(["experiments"], "POST", id), null);
  assert.equal(allowedPath(["experiments", id, "trials"], "POST", id), null);
  assert.equal(
    allowedPath(["runs", id, "backpressure"], "POST", id),
    `/api/v1/runs/${id}/backpressure`,
  );
  assert.equal(
    allowedPath(
      ["projects", "00000000-0000-4000-8000-000000000002", "experiments"],
      "GET",
      id,
    ),
    null,
  );
});

test("walkthrough gateway allows only scoped mock decisions and fixed output names", async () => {
  assert.ok(allowedPath(["projects", root, "workspace"], "GET", root));
  assert.ok(allowedPath(["projects", root, "demo-capabilities"], "GET", root));
  assert.equal(
    allowedPath(["projects", root, "demo-capabilities"], "POST", root),
    null,
  );
  assert.ok(allowedPath(["runs", root, "brief"], "GET", root));
  assert.ok(
    allowedPath(["runs", root, "backpressure", "history"], "GET", root),
  );
  assert.ok(allowedPath(["projects", root, "demos"], "POST", root));
  assert.ok(allowedPath(["demos", root, "decision"], "POST", root));
  assert.ok(
    allowedPath(["demos", root, "artifacts", "final-brief"], "GET", root),
  );
  for (const slug of [
    "agent-draft",
    "agent-review",
    "agent-repair",
    "handoff-evidence",
  ]) {
    assert.ok(allowedPath(["demos", root, "artifacts", slug], "GET", root));
    assert.equal(
      allowedPath(["demos", root, "artifacts", slug], "POST", root),
      null,
    );
  }
  assert.equal(
    allowedPath(["demos", root, "artifacts", "../../.env"], "GET", root),
    null,
  );
  assert.equal(
    allowedPath(["demos", root, "artifacts", "unlisted"], "GET", root),
    null,
  );
  assert.equal(allowedPath(["demos", root, "approve"], "POST", root), null);
  assert.equal(
    allowedPath(
      ["projects", "00000000-0000-4000-8000-000000000000", "demos"],
      "POST",
      root,
    ),
    null,
  );
  const old = process.env.SWARM_STUDIO_READ_ONLY;
  process.env.SWARM_STUDIO_READ_ONLY = "true";
  try {
    for (const path of [
      ["projects", root, "demos"],
      ["demos", root, "decision"],
    ]) {
      const r = await forward(
        new Request("http://127.0.0.1:3300/api/backend/" + path.join("/"), {
          method: "POST",
          headers: {
            Host: "127.0.0.1:3300",
            Origin: "http://127.0.0.1:3300",
            "Content-Type": "application/json",
            "Idempotency-Key": "test-demo-readonly",
          },
          body: "{}",
        }),
        path,
      );
      assert.equal(r.status, 403);
      assert.equal((await r.json()).code, "read_only");
    }
  } finally {
    if (old === undefined) delete process.env.SWARM_STUDIO_READ_ONLY;
    else process.env.SWARM_STUDIO_READ_ONLY = old;
  }
});
