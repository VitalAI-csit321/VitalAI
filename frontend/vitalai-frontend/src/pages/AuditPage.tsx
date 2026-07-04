import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { getAuditByCase } from "../api/audit";
import type { AuditEvent } from "../types";
import { Card, Spinner, Alert, Topbar, C } from "../components/ui";

export function AuditPage() {
  const [caseId, setCaseId]     = useState("");
  const [lookupId, setLookupId] = useState("");
  const [selected, setSelected] = useState<AuditEvent | null>(null);

  const query = useQuery({
    queryKey: ["audit", lookupId],
    queryFn: () => getAuditByCase(lookupId),
    enabled: !!lookupId,
    retry: false,
  });

  function search() {
    setLookupId(caseId);
    setSelected(null);
  }

  const events = query.data ?? [];

  return (
    <div>
      <Topbar />
      <div style={{ padding: 24 }}>
        <h1 style={{ fontSize: 20, fontWeight: 700, color: C.text, margin: "0 0 4px" }}>Audit log</h1>
        <p style={{ fontSize: 13, color: C.textMid, margin: "0 0 20px" }}>
          View all audit events for a case · <code style={{ fontFamily: "monospace", fontSize: 11 }}>GET /api/v1/audit/by-case/{"{case_id}"}</code>
          <span style={{ color: C.red, marginLeft: 8 }}>Admin only</span>
        </p>

        {/* Search */}
        <div style={{ display: "flex", gap: 10, marginBottom: 20, maxWidth: 560 }}>
          <input value={caseId} onChange={e => setCaseId(e.target.value)}
            placeholder="Paste case UUID…"
            onKeyDown={e => e.key === "Enter" && search()}
            style={{ flex: 1, border: `1px solid ${C.border}`, borderRadius: 6, padding: "8px 12px", fontSize: 13, outline: "none" }} />
          <button onClick={search} disabled={!caseId || query.isFetching}
            style={{ padding: "8px 20px", background: C.teal, color: "#fff", border: "none", borderRadius: 6, fontSize: 13, fontWeight: 600, cursor: "pointer" }}>
            {query.isFetching ? "Searching…" : "Search"}
          </button>
        </div>

        {query.isError && <Alert type="error" message="No audit events found, or you don't have admin access." />}

        {query.isFetching && <div style={{ display: "flex", justifyContent: "center", padding: 40 }}><Spinner size={28} /></div>}

        {!query.isFetching && events.length > 0 && (
          <div style={{ display: "grid", gridTemplateColumns: "1fr 380px", gap: 16 }}>
            {/* Events table */}
            <Card style={{ padding: 0 }}>
              <div style={{ padding: "10px 16px", borderBottom: `1px solid ${C.border}`, fontSize: 12, color: C.textMuted }}>
                {events.length} events for case <code style={{ fontFamily: "monospace" }}>{lookupId.slice(0, 8)}…</code>
              </div>
              <table style={{ width: "100%", borderCollapse: "collapse" }}>
                <thead>
                  <tr style={{ background: C.surfaceDim }}>
                    {["Time", "Actor", "Action", ""].map(h => (
                      <th key={h} style={{ textAlign: "left", padding: "9px 14px", fontSize: 11, fontWeight: 700, color: C.textMuted, textTransform: "uppercase", letterSpacing: "0.05em" }}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {events.map(ev => (
                    <tr key={ev.id} onClick={() => setSelected(selected?.id === ev.id ? null : ev)}
                      style={{ borderTop: `1px solid ${C.border}`, cursor: "pointer", background: selected?.id === ev.id ? C.tealLight : "transparent" }}>
                      <td style={{ padding: "10px 14px", fontSize: 12, color: C.textMid, fontFamily: "monospace", whiteSpace: "nowrap" }}>
                        {new Date(ev.timestamp).toLocaleTimeString("en-AU")}
                      </td>
                      <td style={{ padding: "10px 14px", fontSize: 12, color: C.text }}>{ev.actor_label ?? "system"}</td>
                      <td style={{ padding: "10px 14px" }}>
                        <span style={{ fontSize: 12, fontWeight: 700, color: C.teal }}>{ev.action}</span>
                      </td>
                      <td style={{ padding: "10px 14px", fontSize: 12, color: C.teal }}>
                        {selected?.id === ev.id ? "▲" : "▼"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <div style={{ padding: "10px 16px", borderTop: `1px solid ${C.border}`, fontSize: 12, color: C.teal }}>
                ✓ Read directly from database
              </div>
            </Card>

            {/* Detail panel */}
            {selected ? (
              <Card style={{ alignSelf: "start" }}>
                <div style={{ fontSize: 14, fontWeight: 700, color: C.text, marginBottom: 14 }}>Event detail</div>
                <div style={{ display: "flex", flexDirection: "column", gap: 8, marginBottom: 14 }}>
                  {([
                    ["ID",        selected.id],
                    ["Action",    selected.action],
                    ["Actor",     selected.actor_label ?? "system"],
                    ["Case ID",   selected.case_id ?? "—"],
                    ["Timestamp", new Date(selected.timestamp).toLocaleString("en-AU")],
                  ] as [string, string][]).map(([k, v]) => (
                    <div key={k}>
                      <div style={{ fontSize: 10, color: C.textMuted, textTransform: "uppercase", fontWeight: 600, marginBottom: 2 }}>{k}</div>
                      <div style={{ fontSize: 12, color: C.text, fontFamily: ["ID","Case ID"].includes(k) ? "monospace" : "inherit" }}>{v}</div>
                    </div>
                  ))}
                </div>
                <div style={{ fontSize: 11, color: C.textMuted, fontWeight: 600, marginBottom: 6 }}>DETAILS</div>
                <pre style={{ background: "#1A202C", color: "#E2E8F0", borderRadius: 6, padding: 10, fontSize: 11, overflow: "auto", margin: 0 }}>
                  {JSON.stringify(selected.details, null, 2)}
                </pre>
              </Card>
            ) : (
              <Card style={{ display: "flex", alignItems: "center", justifyContent: "center", minHeight: 200 }}>
                <div style={{ textAlign: "center", color: C.textMuted, fontSize: 13 }}>Click a row to see details</div>
              </Card>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
