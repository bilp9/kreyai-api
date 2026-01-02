"use client";

import { useJobStatus } from "@/app/hooks/useJobStatus";

export default function JobStatus({ jobId }: { jobId: string }) {
  const { status, loading } = useJobStatus(jobId);

  const labelMap: Record<string, string> = {
    pending_verification: "Waiting for email verification…",
    verified: "Email verified ✔",
    uploaded: "File uploaded ✔",
    unknown: "Checking job status…",
  };

  return (
    <div className="mt-6 rounded-md border border-gray-700 p-4 text-sm text-gray-300">
      {loading ? "Checking status…" : labelMap[status]}
    </div>
  );
}
