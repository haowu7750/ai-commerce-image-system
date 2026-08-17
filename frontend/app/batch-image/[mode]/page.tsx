import { notFound } from "next/navigation";

import { BatchImageWorkspace } from "@/components/batch-image-workspace";
import { isSupportedBatchMode } from "@/lib/batch-image-tools";

export default async function BatchImageToolPage({
  params,
}: {
  params: Promise<{ mode: string }>;
}) {
  const { mode } = await params;
  if (!isSupportedBatchMode(mode)) notFound();
  return <BatchImageWorkspace mode={mode} />;
}
