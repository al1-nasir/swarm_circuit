import { forward, json } from "@/lib/gateway.mjs";
export const dynamic = "force-dynamic";

async function handle(
  request: Request,
  context: { params: Promise<{ path: string[] }> },
) {
  try {
    return await forward(request, (await context.params).path);
  } catch {
    return json(
      {
        code: "configuration_error",
        message: "Check local Studio backend configuration.",
      },
      503,
    );
  }
}
export { handle as GET, handle as POST };
