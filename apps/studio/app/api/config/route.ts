import { json, sameOrigin, settings } from "@/lib/gateway.mjs";
export const dynamic = "force-dynamic";
export function GET(request: Request) {
  if (!sameOrigin(request.headers))
    return json({ message: "Use the local Studio origin." }, 403);
  try {
    const config = settings();
    return json({
      projectId: config.projectId,
      operator: Boolean(config.operatorToken),
      configured: Boolean(config.readToken),
      backend: config.upstream,
    });
  } catch {
    return json({ message: "Check local Studio backend configuration." }, 503);
  }
}
