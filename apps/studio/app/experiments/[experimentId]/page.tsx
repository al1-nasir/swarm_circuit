import { notFound } from "next/navigation";
import { Experiments } from "@/components/experiments";
export default async function Page({
  params,
}: {
  params: Promise<{ experimentId: string }>;
}) {
  const { experimentId } = await params;
  if (!/^[0-9a-f-]{36}$/i.test(experimentId)) notFound();
  return <Experiments experimentId={experimentId} />;
}
