import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { createConsent, getConsentByCase, captureConsent, withdrawConsent } from "../api/consent";
import type { ConsentRecord } from "../types";
import { Btn, Input, Card, Alert, Spinner, Badge, Topbar, C } from "../components/ui";

type BadgeColor = "amber" | "green" | "red" | "gray";

const STATUS_COLOR: Record<string, BadgeColor> = {
  pending:      "amber",
  captured:     "green",
  withdrawn:    "red",
  not_required: "gray",
};

const STATUS_LABEL: Record<string, string> = {
  pending:      "Pending",
  captured:     "Captured",
  withdrawn:    "Withdrawn",
  not_required: "Not Required",
};

export function ConsentPage() {
  // case_id can come from URL param (after redirect from intake) or typed manually
  const params   = new URLSearchParams(window.location.search);
  const [caseId, setCaseId] = useState(params.get("case_id") ?? "");
  const [lookupId, setLookupId] = useState(params.get("case_id") ?? "");
  const [notes, setNotes]     = useState("");
  const [consentType, setType] = useState("administrative");
  const [record, setRecord]   = useState<ConsentRecord | null>(null);

  // Look up existing consent for a case
  const lookupQuery = useQuery({
    queryKey: ["consent", lookupId],
    queryFn: () => getConsentByCase(lookupId),
    enabled: false,   // only runs on explicit search
    retry: false,
  });

  async function doLookup() {
    const result = await lookupQuery.refetch();
    if (result.data) setRecord(result.data);
  }

  // Create consent
  const createMutation = useMutation({
    mutationFn: () => createConsent({ case_id: caseId, consent_type: consentType, notes: notes || null }),
    onSuccess: (data) => setRecord(data),
  });

  // Capture consent
  const captureMutation = useMutation({
    mutationFn: () => captureConsent(record!.id),
    onSuccess: (data) => setRecord(data),
  });

  // Withdraw consent
  const withdrawMutation = useMutation({
    mutationFn: () => withdrawConsent(record!.id),
    onSuccess: (data) => setRecord(data),
  });

  const anyPending = createMutation.isPending || captureMutation.isPending || withdrawMutation.isPending;

  return (
    <div>
      <Topbar />
      <div style={{ padding: 24 }}>
        <h1 style={{ fontSize: 20, fontWeight: 700, color: C.text, margin: "0 0 4px" }}>Consent</h1>
        <p style={{ fontSize: 13, color: C.textMid, margin: "0 0 24px" }}>Create and manage consent records · <code style={{ fontFamily: "monospace", fontSize: 11 }}>POST /api/v1/consent</code></p>

        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16, maxWidth: 860 }}>

          {/* Left: look up existing */}
          <Card>
            <div style={{ fontSize: 14, fontWeight: 600, color: C.text, marginBottom: 14 }}>Look up consent by case</div>
            <div style={{ display: "flex", gap: 8, marginBottom: 12 }}>
              <input
                value={lookupId} onChange={e => setLookupId(e.target.value)}
                placeholder="Paste case UUID…"
                style={{ flex: 1, border: `1px solid ${C.border}`, borderRadius: 6, padding: "8px 12px", fontSize: 13, outline: "none" }}
              />
              <Btn size="sm" onClick={doLookup} disabled={!lookupId || lookupQuery.isFetching}>
                {lookupQuery.isFetching ? "…" : "Look up"}
              </Btn>
            </div>
            {lookupQuery.isError && <Alert type="error" message="No consent record found for that case ID." />}
          </Card>

          {/* Right: create new */}
          <Card>
            <div style={{ fontSize: 14, fontWeight: 600, color: C.text, marginBottom: 14 }}>Create new consent record</div>
            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              <Input label="Case ID" value={caseId} onChange={setCaseId} placeholder="UUID from intake" required />
              <div>
                <label style={{ fontSize: 12, fontWeight: 500, color: C.textMid }}>Consent type</label>
                <select value={consentType} onChange={e => setType(e.target.value)}
                  style={{ width: "100%", border: `1px solid ${C.border}`, borderRadius: 6, padding: "8px 12px", fontSize: 13, marginTop: 4, outline: "none" }}>
                  <option value="administrative">Administrative</option>
                  <option value="clinical">Clinical</option>
                  <option value="research">Research</option>
                </select>
              </div>
              <Input label="Notes (optional)" value={notes} onChange={setNotes} placeholder="Any context…" />
            </div>
            {createMutation.isError && <div style={{ marginTop: 12 }}><Alert type="error" message="Failed to create consent record." /></div>}
            <div style={{ marginTop: 14 }}>
              <Btn onClick={() => createMutation.mutate()} disabled={!caseId || anyPending} style={{ width: "100%" }}>
                {createMutation.isPending ? "Creating…" : "Create consent record"}
              </Btn>
            </div>
          </Card>
        </div>

        {/* Record view + actions */}
        {record && (
          <Card style={{ maxWidth: 520, marginTop: 20 }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16 }}>
              <div style={{ fontSize: 14, fontWeight: 700, color: C.text }}>Consent record</div>
              <Badge color={STATUS_COLOR[record.status] ?? "gray"}>{STATUS_LABEL[record.status] ?? record.status}</Badge>
            </div>

            <div style={{ marginBottom: 16 }}>
              {([
                ["Consent ID",   record.id],
                ["Case ID",      record.case_id],
                ["Type",         record.consent_type],
                ["Created",      new Date(record.created_at).toLocaleString("en-AU")],
                ["Captured at",  record.captured_at ? new Date(record.captured_at).toLocaleString("en-AU") : "—"],
                ["Notes",        record.notes ?? "—"],
              ] as [string, string][]).map(([k, v]) => (
                <div key={k} style={{ display: "flex", justifyContent: "space-between", fontSize: 13, padding: "6px 0", borderBottom: `1px solid ${C.border}` }}>
                  <span style={{ color: C.textMuted }}>{k}</span>
                  <span style={{ color: C.text, fontWeight: 500, fontFamily: k.includes("ID") ? "monospace" : "inherit", fontSize: k.includes("ID") ? 11 : 13 }}>{v}</span>
                </div>
              ))}
            </div>

            {/* Unclear-state banner (Sprint 2 — Ariana's spec) */}
            {record.status === "pending" && (
              <Alert type="warning" title="Consent pending — action required" message="Consent has been created but not yet captured. Capture it below before proceeding to triage." />
            )}

            <div style={{ display: "flex", gap: 10, marginTop: 14 }}>
              {record.status === "pending" && (
                <Btn onClick={() => captureMutation.mutate()} disabled={anyPending} style={{ flex: 1 }}>
                  {captureMutation.isPending ? "Capturing…" : "✓ Capture consent"}
                </Btn>
              )}
              {(record.status === "pending" || record.status === "captured") && (
                <Btn variant="danger" onClick={() => withdrawMutation.mutate()} disabled={anyPending} style={{ flex: 1 }}>
                  {withdrawMutation.isPending ? "Withdrawing…" : "Withdraw"}
                </Btn>
              )}
            </div>

            {captureMutation.isError  && <div style={{ marginTop: 10 }}><Alert type="error" message="Could not capture consent. It may already be captured or withdrawn." /></div>}
            {withdrawMutation.isError && <div style={{ marginTop: 10 }}><Alert type="error" message="Could not withdraw consent." /></div>}
          </Card>
        )}

        {lookupQuery.isFetching && <div style={{ marginTop: 20, display: "flex" }}><Spinner /></div>}
      </div>
    </div>
  );
}
