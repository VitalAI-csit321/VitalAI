import { apiGet } from "../lib/apiClient";
import type { DetailedHealth } from "./types";

interface RawService {
  name: string; detail: string; status: DetailedHealth["services"][number]["status"];
  latency_ms: number | null; note: string | null;
}

interface RawHealth {
  services: RawService[];
  uptime_seconds: number | null;
  latency: { count: number; avg_ms: number | null; p95_ms: number | null };
  active_sessions: number;
}

export async function getDetailedHealth(): Promise<DetailedHealth> {
  const r = await apiGet<RawHealth>("/api/v1/health/detailed");
  return {
    services: r.services.map(s => ({
      name: s.name, detail: s.detail, status: s.status,
      latencyMs: s.latency_ms, note: s.note,
    })),
    uptimeSeconds: r.uptime_seconds,
    latency: { count: r.latency.count, avgMs: r.latency.avg_ms, p95Ms: r.latency.p95_ms },
    activeSessions: r.active_sessions,
  };
}
