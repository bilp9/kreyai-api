"use client";

import { useEffect, useState } from "react";

export type JobStatus =
  | "pending_verification"
  | "verified"
  | "uploaded"
  | "unknown";

export function useJobStatus(jobId: string | null) {
  const [status, setStatus] = useState<JobStatus>("unknown");
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!jobId) return;

    setLoading(true);

    const fetchStatus = async () => {
      try {
        // Phase 1: reuse verify endpoint safely
        const res = await fetch(
          `http://127.0.0.1:8000/api/verify?job_id=${jobId}&code=__noop__`,
          { method: "POST" }
        );

        if (res.status === 200) {
          const data = await res.json();
          setStatus(data.status);
        }
      } catch {
        setStatus("unknown");
      } finally {
        setLoading(false);
      }
    };

    fetchStatus();
    const interval = setInterval(fetchStatus, 5000);

    return () => clearInterval(interval);
  }, [jobId]);

  return { status, loading };
}
