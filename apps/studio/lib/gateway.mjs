// Server-only module: imported exclusively by route handlers and the local Node server.
export function settings(env = process.env) {
  const upstream = new URL(env.SWARM_API_URL || "http://127.0.0.1:8000");
  if (
    !["http:", "https:"].includes(upstream.protocol) ||
    !["127.0.0.1", "localhost", "[::1]"].includes(upstream.hostname) ||
    upstream.username ||
    upstream.password ||
    upstream.pathname !== "/" ||
    upstream.search
  )
    throw new Error("Studio requires a loopback backend origin");
  return {
    upstream: upstream.origin,
    projectId: env.SWARM_PROJECT_ID || "11111111-1111-4111-8111-111111111111",
    readToken: env.SWARM_SDK_PROJECT_TOKEN || env.SWARM_OPERATOR_TOKEN || "",
    operatorToken:
      env.SWARM_STUDIO_READ_ONLY === "true"
        ? ""
        : env.SWARM_OPERATOR_TOKEN || "",
  };
}

export function sameOrigin(headers, mutating = false) {
  const host = headers.get("host") || "";
  let expected;
  try {
    expected = new URL("http://" + host);
    if (!["localhost", "127.0.0.1", "[::1]"].includes(expected.hostname))
      return false;
  } catch {
    return false;
  }
  if (headers.get("sec-fetch-site") === "cross-site") return false;
  const origin = headers.get("origin");
  return origin ? origin === expected.origin : !mutating;
}

const uuid = "[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}";
export function allowedPath(path, method, projectId) {
  const joined = path.join("/");
  if (method === "GET") {
    if (joined === "health") return "/api/v1/health";
    if (
      [
        `projects/${projectId}/runs`,
        `projects/${projectId}/experiments`,
        `projects/${projectId}/workspace`,
        `projects/${projectId}/demos`,
        `projects/${projectId}/demo-capabilities`,
      ].includes(joined)
    )
      return `/api/v1/${joined}`;
    if (
      new RegExp(
        `^experiments/${uuid}/(?:results|export\\.csv|trials(?:/${uuid}/(?:truth\\.jsonl|observations\\.jsonl|proposals\\.json))?)$`,
        "i",
      ).test(joined)
    )
      return `/api/v1/${joined}`;
    if (
      new RegExp(
        `^demos/${uuid}(?:/artifacts/(?:public-findings|dataset-analysis|final-brief|agent-draft|agent-review|agent-repair|handoff-evidence))?$`,
        "i",
      ).test(joined)
    )
      return `/api/v1/${joined}`;
    if (
      new RegExp(
        `^runs/${uuid}(?:/(?:graph|timeline|incidents|payments|approvals|runtime-sessions|control-commands|backpressure(?:/history)?|brief|evidence/${uuid}))?$`,
        "i",
      ).test(joined)
    )
      return `/api/v1/${joined}`;
    if (new RegExp(`^control-commands/${uuid}$`, "i").test(joined))
      return `/api/v1/${joined}`;
  }
  if (
    method === "POST" &&
    (new RegExp(`^runs/${uuid}/(?:control-commands|backpressure)$`, "i").test(
      joined,
    ) ||
      joined === `projects/${projectId}/demos` ||
      new RegExp(`^demos/${uuid}/decision$`, "i").test(joined))
  )
    return `/api/v1/${joined}`;
  return null;
}

export function json(body, status = 200) {
  return Response.json(body, {
    status,
    headers: { "Cache-Control": "no-store" },
  });
}

export async function forward(request, path) {
  if (!sameOrigin(request.headers, request.method !== "GET"))
    return json(
      { code: "origin_rejected", message: "Use the local Studio origin." },
      403,
    );
  const config = settings();
  const target = allowedPath(path, request.method, config.projectId);
  if (!target)
    return json(
      {
        code: "not_available",
        message: "This operation is not available in Studio.",
      },
      404,
    );
  const token =
    request.method === "POST" ? config.operatorToken : config.readToken;
  if (!token)
    return json(
      {
        code: "read_only",
        message:
          "Configure local credentials; control requires the operator role.",
      },
      403,
    );
  const query = new URL(request.url).searchParams;
  if (
    [...query.keys()].some(
      (key) =>
        !(
          ["backpressure", "demos"].includes(path.at(-1)) &&
          request.method === "GET"
            ? ["key"]
            : [
                "cursor",
                "limit",
                "view",
                "scenario",
                "arm",
                "kind",
                "include_diagnostics",
              ]
        ).includes(key),
    ) ||
    query.toString().length > 1600
  )
    return json({ code: "invalid_query", message: "Unsupported query." }, 422);
  const headers = { Authorization: `Bearer ${token}` };
  let body;
  if (request.method === "POST") {
    if (!request.headers.get("content-type")?.startsWith("application/json"))
      return json(
        { code: "invalid_request", message: "JSON is required." },
        422,
      );
    body = await request.text();
    if (body.length > 4096)
      return json(
        { code: "too_large", message: "Request exceeds the Studio limit." },
        413,
      );
    try {
      JSON.parse(body);
    } catch {
      return json({ code: "invalid_request", message: "Invalid JSON." }, 422);
    }
    const key = request.headers.get("idempotency-key") || "";
    if (key.length < 8 || key.length > 180)
      return json(
        { code: "invalid_key", message: "A stable request key is required." },
        422,
      );
    headers["Content-Type"] = "application/json";
    headers["Idempotency-Key"] = key;
  }
  try {
    const response = await fetch(
      config.upstream + target + (query.size ? "?" + query : ""),
      {
        method: request.method,
        headers,
        body,
        cache: "no-store",
        signal: AbortSignal.timeout(
          path[0] === "experiments" && path.at(-1) === "results"
            ? 120000
            : 15000,
        ),
      },
    );
    if (
      request.method === "GET" &&
      path[0] === "demos" &&
      path[2] === "artifacts" &&
      response.ok
    ) {
      const type = response.headers.get("content-type") || "";
      if (!type.startsWith("text/markdown"))
        throw new Error("Invalid output response");
      return new Response(response.body, {
        status: response.status,
        headers: {
          "Content-Type": type,
          "Content-Disposition":
            response.headers.get("content-disposition") || "attachment",
          "Cache-Control": "no-store",
          "X-Content-Type-Options": "nosniff",
        },
      });
    }
    const file = path.at(-1);
    if (
      request.method === "GET" &&
      [
        "export.csv",
        "truth.jsonl",
        "observations.jsonl",
        "proposals.json",
      ].includes(file) &&
      response.ok
    ) {
      const type = response.headers.get("content-type") || "";
      if (!(
        type.startsWith("text/csv") ||
        type.startsWith("application/x-ndjson") ||
        (file === "proposals.json" && type.startsWith("application/json"))
      ))
        throw new Error("Invalid artifact response");
      return new Response(response.body, {
        status: response.status,
        headers: {
          "Content-Type": type,
          "Content-Disposition":
            response.headers.get("content-disposition") || "attachment",
          "Cache-Control": "no-store",
        },
      });
    }
    if (!response.headers.get("content-type")?.includes("application/json"))
      throw new Error("Invalid upstream response");
    return json(await response.json(), response.status);
  } catch {
    return json(
      {
        code: "backend_unavailable",
        message:
          request.method === "POST"
            ? "Submission outcome unknown. Reconcile command history before another request."
            : "Cannot reach the local SwarmCircuit backend.",
      },
      502,
    );
  }
}
