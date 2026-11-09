import { Suspense } from "react";
import { notFound } from "next/navigation";
import { Studio } from "@/components/studio";
export default async function Page({
  params,
}: {
  params: Promise<{ runId: string }>;
}) {
  const { runId } = await params;
  if (!/^[0-9a-f-]{36}$/i.test(runId)) notFound();
  return (
    <Suspense fallback={<div className="loading-state">Loading workflow…</div>}>
      <Studio runId={runId} />
    </Suspense>
  );
}
