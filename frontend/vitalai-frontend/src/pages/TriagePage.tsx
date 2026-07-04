import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { runTriage } from "../api/triage";
import type { TriageResponse, TriageCategory, RoutingAction } from "../types";
import { Btn, Input, Card, Alert, Badge, Topbar, C } from "../components/ui";

type BadgeColor = "red" | "amber" | "teal" | "green" | "gray";

const CATEGORY_CONFIG: Record<TriageCategory, { label: string; color: BadgeColor; description: string }> = {
  immediate:                  { label: "Immediate",     color: "red",   description: "Life-threatening — attend within minutes" },
  time_sensitive:             { label: "Time-sensitive", color: "amber", description: "Attend within 30 minutes" },
  routine:                    { label: "Routine",        color: "green", description: "Attend within 2 hours" },
  low_confidence_manual_review: { label: "Manual review", color: "gray",  description: "Low confidence — human review required" },
};

const ROUTING_LABEL: Record<RoutingAction, string> = {
  admin_workflow:    "Admin workflow",
  human_review:     "Human review",
  direct_escalation: "Direct escalation",
};

export function TriagePage() {
  const [caseId, setCaseId]       = useState("");
  const [reason, setReason]       = useState("");
  const [keywords, setKeywords]   = useState("");
  const [flags, setFlags]         = useState("");
  const [result, setResult]       = useState<TriageResponse | null>(null);

  const mutation = useMutation({
    mutationFn: () => runTriage({
      case_id:               caseId,
      contact_reason:        reason,
      keywords:              keywords ? keywords.split(",").map(k => k.trim()).filter(Boolean) : [],
      patient_priority_flags: flags ? flags.split(",").map(f => f.trim()).filter(Boolean) : [],
    }),
    onSuccess: (data) => setResult(data),
  });

  const cfg = result ? CATEGORY_CONFIG[result.category] : null;

  return (
    <div>
      <Topbar />
      <div style={{ padding: 24 }}>
        <h1 style={{ fontSize: 20, fontWeight: 700, color: C.text, margin: "0 0 4px" }}>Triage</h1>
        <p style={{ fontSize: 13, color: C.textMid, margin: "0 0 20px" }}>Run AI triage on a case · <code style={{ fontFamily: "monospace", fontSize: 11 }}>POST /api/v1/triage</code></p>
        <p style={{ fontSize: 12, color: C.amber, marginBottom: 20 }}>⚠ Consent must be captured before triage will succeed.</p>

        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16, maxWidth: 860 }}>
          <Card>
            <div style={{ fontSize: 14, fontWeight: 600, color: C.text, marginBottom: 16 }}>Triage request</div>
            <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
              <Input label="Case ID" value={caseId} onChange={setCaseId} placeholder="UUID from intake" required />
              <div>
                <label style={{ fontSize: 12, fontWeight: 500, color: C.textMid }}>Contact reason *</label>
                <textarea value={reason} onChange={e => setReason(e.target.value)} placeholder="Patient's presenting concern…" rows={3}
                  style={{ width: "100%", border: `1px solid ${C.border}`, borderRadius: 6, padding: "8px 12px", fontSize: 13, outline: "none", resize: "vertical", fontFamily: "inherit", marginTop: 4, boxSizing: "border-box" }} />
              </div>
              <Input label="Keywords (comma-separated, optional)" value={keywords} onChange={setKeywords} placeholder="chest pain, shortness of breath" />
              <Input label="Priority flags (comma-separated, optional)" value={flags} onChange={setFlags} placeholder="elderly, diabetic" />
            </div>
            {mutation.isError && (
              <div style={{ marginTop: 14 }}>
                <Alert type="error" message="Triage failed. Check consent is captured for this case, and the backend is running." />
              </div>
            )}
            <div style={{ marginTop: 16 }}>
              <Btn onClick={() => mutation.mutate()} disabled={mutation.isPending || !caseId || !reason} style={{ width: "100%" }}>
                {mutation.isPending ? "Running triage…" : "Run triage"}
              </Btn>
            </div>
          </Card>

          {/* Result panel */}
          {result && cfg ? (
            <Card>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16 }}>
                <div style={{ fontSize: 14, fontWeight: 700, color: C.text }}>Triage result</div>
                <Badge color={cfg.color}>{cfg.label}</Badge>
              </div>

              <div style={{ background: `${C[cfg.color === "red" ? "red" : cfg.color === "amber" ? "amber" : "teal"]}15`, borderRadius: 8, padding: 12, marginBottom: 16 }}>
                <div style={{ fontSize: 13, fontWeight: 600, color: C.text }}>{cfg.description}</div>
              </div>

              <div style={{ display: "flex", flexDirection: "column", gap: 8, marginBottom: 16 }}>
                {([
                  ["Triage ID",      result.triage_id],
                  ["Case ID",        result.case_id],
                  ["Routing action", ROUTING_LABEL[result.routing_action]],
                  ["Target queue",   result.target_queue],
                  ["Confidence",     `${(result.confidence * 100).toFixed(0)}%`],
                  ["Escalated",      result.escalated ? "Yes" : "No"],
                ] as [string, string][]).map(([k, v]) => (
                  <div key={k} style={{ display: "flex", justifyContent: "space-between", fontSize: 13, padding: "5px 0", borderBottom: `1px solid ${C.border}` }}>
                    <span style={{ color: C.textMuted }}>{k}</span>
                    <span style={{ color: result.escalated && k === "Escalated" ? C.red : C.text, fontWeight: 500 }}>{v}</span>
                  </div>
                ))}
              </div>

              <div style={{ fontSize: 12, fontWeight: 600, color: C.textMid, marginBottom: 6, textTransform: "uppercase" }}>Rationale</div>
              <div style={{ fontSize: 13, color: C.text, lineHeight: 1.7, background: C.surfaceDim, borderRadius: 6, padding: 10 }}>
                {result.rationale}
              </div>

              {result.escalated && (
                <div style={{ marginTop: 12 }}>
                  <Alert type="warning" title="Case escalated" message="This case has been flagged for direct escalation. A senior operator should review immediately." />
                </div>
              )}
            </Card>
          ) : (
            <Card style={{ display: "flex", alignItems: "center", justifyContent: "center", minHeight: 200 }}>
              <div style={{ textAlign: "center", color: C.textMuted }}>
                <div style={{ fontSize: 32, marginBottom: 8 }}>🚑</div>
                <div style={{ fontSize: 13 }}>Fill in the form and run triage to see results</div>
              </div>
            </Card>
          )}
        </div>
      </div>
    </div>
  );
}
