import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { createIntake } from "../api/intake";
import type { IntakeCreate, IntakeCase } from "../types";
import { Btn, Input, Textarea, Select, Card, Alert, Topbar, C } from "../components/ui";

const CHANNEL_OPTIONS = [
  { label: "Walk-in",  value: "walk_in" },
  { label: "Phone",    value: "phone"   },
  { label: "Email",    value: "email"   },
  { label: "Referral", value: "referral"},
];

const EMPTY: IntakeCreate = { patient_name: "", contact_reason: "", contact_channel: "", notes: "" };

export function IntakePage() {
  const [form, setForm] = useState<IntakeCreate>(EMPTY);
  const [errors, setErrors] = useState<Partial<Record<keyof IntakeCreate, string>>>({});
  const [created, setCreated] = useState<IntakeCase | null>(null);

  const set = (f: keyof IntakeCreate) => (v: string) => setForm(p => ({ ...p, [f]: v }));

  const mutation = useMutation({
    mutationFn: () => createIntake({ ...form, notes: form.notes || null }),
    onSuccess: (data) => setCreated(data),
  });

  function validate() {
    const e: typeof errors = {};
    if (!form.patient_name)    e.patient_name    = "Required";
    if (!form.contact_reason)  e.contact_reason  = "Required";
    if (!form.contact_channel) e.contact_channel = "Required";
    setErrors(e);
    return Object.keys(e).length === 0;
  }

  function submit() {
    if (validate()) mutation.mutate();
  }

  if (created) {
    return (
      <div>
        <Topbar />
        <div style={{ padding: 24 }}>
          <Card style={{ maxWidth: 520 }}>
            <div style={{ width: 44, height: 44, background: C.tealLight, borderRadius: "50%", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 20, margin: "0 auto 16px" }}>✓</div>
            <h2 style={{ textAlign: "center", fontSize: 17, fontWeight: 700, color: C.text, marginBottom: 4 }}>Intake created</h2>
            <p style={{ textAlign: "center", fontSize: 13, color: C.textMid, marginBottom: 20 }}>Case is ready for consent and triage.</p>
            <div style={{ background: C.surfaceDim, borderRadius: 8, padding: 14, marginBottom: 20 }}>
              {([
                ["Case ID",        created.id],
                ["Patient",        created.patient_name],
                ["Reason",         created.contact_reason],
                ["Channel",        created.contact_channel],
                ["Status",         created.status],
                ["Created",        new Date(created.created_at).toLocaleString("en-AU")],
              ] as [string, string][]).map(([k, v]) => (
                <div key={k} style={{ display: "flex", justifyContent: "space-between", fontSize: 13, padding: "6px 0", borderBottom: `1px solid ${C.border}` }}>
                  <span style={{ color: C.textMuted }}>{k}</span>
                  <span style={{ color: C.text, fontWeight: 500, fontFamily: k === "Case ID" ? "monospace" : "inherit", fontSize: k === "Case ID" ? 11 : 13 }}>{v}</span>
                </div>
              ))}
            </div>
            <div style={{ display: "flex", gap: 10 }}>
              <Btn variant="outline" onClick={() => { setForm(EMPTY); setCreated(null); }} style={{ flex: 1 }}>New intake</Btn>
              <Btn onClick={() => window.location.href = `/consent?case_id=${created.id}`} style={{ flex: 1 }}>Add consent →</Btn>
            </div>
          </Card>
        </div>
      </div>
    );
  }

  return (
    <div>
      <Topbar />
      <div style={{ padding: 24 }}>
        <h1 style={{ fontSize: 20, fontWeight: 700, color: C.text, margin: "0 0 4px" }}>Patient intake</h1>
        <p style={{ fontSize: 13, color: C.textMid, margin: "0 0 20px" }}>Register a new patient case · <code style={{ fontFamily: "monospace", fontSize: 11 }}>POST /api/v1/intake</code></p>

        <Card style={{ maxWidth: 520 }}>
          {mutation.isError && (
            <div style={{ marginBottom: 16 }}>
              <Alert type="error" message="Failed to create intake. Check the backend is running." />
            </div>
          )}
          <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
            <Input
              label="Patient name" value={form.patient_name} onChange={set("patient_name")}
              placeholder="Full name" required error={errors.patient_name}
            />
            <Textarea
              label="Reason for contact" value={form.contact_reason} onChange={set("contact_reason")}
              placeholder="Describe the patient's presenting concern…"
            />
            {errors.contact_reason && <span style={{ fontSize: 11, color: C.red, marginTop: -10 }}>{errors.contact_reason}</span>}
            <Select
              label="Contact channel" value={form.contact_channel} onChange={set("contact_channel")}
              options={CHANNEL_OPTIONS} placeholder="Select…"
            />
            {errors.contact_channel && <span style={{ fontSize: 11, color: C.red, marginTop: -10 }}>{errors.contact_channel}</span>}
            <Textarea
              label="Additional notes (optional)" value={form.notes ?? ""} onChange={set("notes")}
              placeholder="Any extra context for the ops team…" rows={2}
            />
          </div>
          <div style={{ marginTop: 20, display: "flex", justifyContent: "flex-end" }}>
            <Btn onClick={submit} disabled={mutation.isPending}>
              {mutation.isPending ? "Submitting…" : "Create intake case"}
            </Btn>
          </div>
        </Card>
      </div>
    </div>
  );
}
