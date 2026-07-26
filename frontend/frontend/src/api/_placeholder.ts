// PLACEHOLDER SOURCE — the one file to delete/replace when real backends land.
//
// Per the build decision: pages and fields the backend does not serve yet
// (patient MRN/DOB/gender, the Inbox, the dashboard weekly chart) are rendered
// with the exact approved design, fed from here. Each adapter reads from this
// module behind a clearly marked boundary, so wiring a real database later is a
// localized change: point the adapter at the new endpoint and drop the matching
// export below. No component imports this file directly.

import type { Message, PatientStatus } from "./types";

// Deterministic pseudo-fields derived from a stable id, so a given case always
// renders the same synthesized MRN/DOB/gender across reloads (no flicker, no
// random churn) until the real patient record replaces them.
function hashString(input: string): number {
  let h = 2166136261;
  for (let i = 0; i < input.length; i++) {
    h ^= input.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return Math.abs(h);
}

export function placeholderPatientFields(id: string, seedIndex: number): {
  mrn: string;
  dateOfBirth: string;
  gender: string;
  status: PatientStatus;
} {
  const h = hashString(id);
  const mrnNumber = 10847 - seedIndex; // matches the design's descending MRNs
  const genders = ["Female", "Male"];
  const statuses: PatientStatus[] = ["active", "active", "active", "pending", "inactive"];
  const year = 1970 + (h % 30);
  const month = String((h % 12) + 1).padStart(2, "0");
  const day = String((h % 27) + 1).padStart(2, "0");
  return {
    mrn: `MRN-${mrnNumber}`,
    dateOfBirth: `${day}/${month}/${year}`,
    gender: genders[h % genders.length],
    status: statuses[h % statuses.length],
  };
}

// Inbox — no messages backend exists. This is the placeholder thread list that
// matches design 10 exactly. Replace the messages adapter body with real calls
// when a messaging service is added.
export const placeholderMessages: Message[] = [
  {
    id: "m1",
    category: "medical_records_request",
    draftText: null,
    draftApprovalId: null,
    draftSent: false,
    taskStatus: "pending",
    fromName: "Dr Catherine Hines",
    fromInitials: "CH",
    toName: "Dr Sanjay Kapoor",
    subject: "Williams discharge follow-up required",
    body: "Sanjay,\n\nI need your review on the Williams discharge summary before we can proceed. The patient is scheduled for discharge tomorrow morning and we need to ensure all documentation is complete.\n\nPlease prioritize this as the family has made arrangements for home care starting Friday.\n\nThanks,\nCatherine",
    priority: "urgent",
    unread: true,
    receivedLabel: "10 mins ago",
    threadReference: "THREAD-2026-05-22-1422",
    avatarColor: "#7c3aed",
  },
  {
    id: "m2",
    category: "new_patient_onboarding",
    draftText: null,
    draftApprovalId: null,
    draftSent: false,
    taskStatus: "pending",
    fromName: "Maria Alvarez",
    fromInitials: "MA",
    toName: "Dr Sanjay Kapoor",
    subject: "Patient consent forms ready",
    body: "The consent forms for this week's onboarding cohort are ready for your review.",
    priority: "normal",
    unread: true,
    receivedLabel: "1 hour ago",
    threadReference: "THREAD-2026-05-22-1120",
    avatarColor: "#0d9488",
  },
  {
    id: "m3",
    category: "results_enquiry",
    draftText: null,
    draftApprovalId: null,
    draftSent: false,
    taskStatus: "pending",
    fromName: "Dr Lisa Kim",
    fromInitials: "LK",
    toName: "Dr Sanjay Kapoor",
    subject: "Lab results - Zhang",
    body: "Lab results for Emily Zhang are in and attached for your review.",
    priority: "normal",
    unread: false,
    receivedLabel: "2 hours ago",
    threadReference: "THREAD-2026-05-22-0910",
    avatarColor: "#eab308",
  },
  {
    id: "m4",
    category: "general_administrative",
    draftText: null,
    draftApprovalId: null,
    draftSent: false,
    taskStatus: "pending",
    fromName: "System",
    fromInitials: "SY",
    toName: "Dr Sanjay Kapoor",
    subject: "Weekly compliance report",
    body: "Your weekly compliance report is ready to view.",
    priority: "fyi",
    unread: false,
    receivedLabel: "Yesterday",
    threadReference: "THREAD-2026-05-21-1700",
    avatarColor: "#64748b",
  },
  {
    id: "m5",
    category: "urgent_emergency",
    draftText: null,
    draftApprovalId: null,
    draftSent: false,
    taskStatus: "pending",
    fromName: "Dr James Taylor",
    fromInitials: "JT",
    toName: "Dr Sanjay Kapoor",
    subject: "Urgent: Bed allocation request",
    body: "We have an urgent bed allocation request for the incoming transfer.",
    priority: "urgent",
    unread: false,
    receivedLabel: "Yesterday",
    threadReference: "THREAD-2026-05-21-1545",
    avatarColor: "#db2777",
  },
  {
    id: "m6",
    category: "general_administrative",
    draftText: null,
    draftApprovalId: null,
    draftSent: false,
    taskStatus: "pending",
    fromName: "Admin Team",
    fromInitials: "AT",
    toName: "Dr Sanjay Kapoor",
    subject: "Monthly metrics review",
    body: "The monthly metrics review is scheduled. Please confirm your availability.",
    priority: "normal",
    unread: false,
    receivedLabel: "2 days ago",
    threadReference: "THREAD-2026-05-20-1000",
    avatarColor: "#0891b2",
  },
];

// Dashboard weekly workflow bars (design 3). No time-series endpoint exists;
// these values match the approved chart. Replace via the dashboard adapter.
export const placeholderWorkflowByDay = [
  { day: "Mon", value: 24 },
  { day: "Tue", value: 32 },
  { day: "Wed", value: 28 },
  { day: "Thu", value: 35 },
  { day: "Fri", value: 29 },
  { day: "Sat", value: 18 },
  { day: "Sun", value: 22 },
];

// Consent queue form labels + records browser (designs 6 & 9) also have no
// dedicated backend; kept here so the adapters stay declarative.
export const placeholderConsentForms = [
  "General Treatment",
  "Surgical Procedure",
  "Data Sharing",
  "Research Study",
];
