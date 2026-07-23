// Mock data — replace with API calls when backend is ready

export const dashboardStats = [
  { id: 1, label: "OPEN CASES", value: "42", sub: "in review" },
  { id: 2, label: "AWAITING APPROVAL", value: "14", sub: "human review" },
  { id: 3, label: "ESCALATIONS", value: "6", sub: "routed" },
  { id: 4, label: "AUDIT EVENTS", value: "87", sub: "last 24h" },
];

export const pendingReviews = [
  { id: 1, label: "Patient intake — James M.", tag: "NEW" },
  { id: 2, label: "Consent update — Sarah T.", tag: "NEW" },
  { id: 3, label: "Record request — Unit 4B", tag: "NEW" },
  { id: 4, label: "Escalation flagged — Dr. Lee", tag: "NEW" },
];

export const patients = [
  { id: "P-1042", name: "James Morrison", dob: "12/03/1978", mrn: "MRN-00101", status: "Active" },
  { id: "P-1041", name: "Sarah Thompson", dob: "05/11/1990", mrn: "MRN-00102", status: "Pending" },
  { id: "P-1040", name: "Michael Chen", dob: "22/07/1965", mrn: "MRN-00103", status: "Active" },
];

export const reviewQueue = [
  { id: "#C-1042", submitted: "1h ago", type: "Intake Review", priority: "High", owner: "Owner 1", reviewed: "—", status: "OPEN" },
  { id: "#C-1041", submitted: "2h ago", type: "Intake Review", priority: "Medium", owner: "Owner 2", reviewed: "Approved", status: "OPEN" },
  { id: "#C-1040", submitted: "3h ago", type: "Intake Review", priority: "High", owner: "Owner 3", reviewed: "—", status: "REVIEW" },
  { id: "#C-1039", submitted: "4h ago", type: "Intake Review", priority: "Low", owner: "Owner 4", reviewed: "Approved", status: "OPEN" },
  { id: "#C-1038", submitted: "5h ago", type: "Intake Review", priority: "Medium", owner: "Owner 5", reviewed: "—", status: "REVIEW" },
  { id: "#C-1037", submitted: "6h ago", type: "Intake Review", priority: "High", owner: "Owner 6", reviewed: "Approved", status: "OPEN" },
  { id: "#C-1036", submitted: "7h ago", type: "Intake Review", priority: "Low", owner: "Owner 7", reviewed: "—", status: "DONE" },
];

export const escalationColumns = [
  {
    id: "submitted", label: "Submitted", count: 12,
    items: [
      { id: "#T-0101", priority: "Low", date: "Apr 28", desc: "Intake form incomplete" },
      { id: "#T-0202", priority: "Low", date: "Apr 28", desc: "Missing insurance details" },
      { id: "#T-0303", priority: "Low", date: "Apr 28", desc: "Consent not captured" },
    ]
  },
  {
    id: "under_review", label: "Under Review", count: 8,
    items: [
      { id: "#T-1101", priority: "Medium", date: "Apr 28", desc: "Record access requested" },
      { id: "#T-1202", priority: "Medium", date: "Apr 28", desc: "Patient re-consent needed" },
      { id: "#T-1303", priority: "Medium", date: "Apr 28", desc: "Duplicate entry flagged" },
    ]
  },
  {
    id: "escalated", label: "Escalated", count: 3,
    items: [
      { id: "#T-2101", priority: "High", date: "Apr 28", desc: "Urgent clinical flag" },
      { id: "#T-2202", priority: "High", date: "Apr 28", desc: "Data breach risk" },
      { id: "#T-2303", priority: "High", date: "Apr 28", desc: "Compliance violation" },
    ]
  },
  {
    id: "resolved", label: "Resolved", count: 24,
    items: [
      { id: "#T-3101", priority: "Low", date: "Apr 28", desc: "Intake complete" },
      { id: "#T-3202", priority: "Low", date: "Apr 28", desc: "Consent finalised" },
      { id: "#T-3303", priority: "Low", date: "Apr 28", desc: "Record delivered" },
    ]
  },
];

export const messages = [
  { id: 1, sender: "Dr. A. Patel", preview: "Regarding patient #P-1042 intake...", time: "2h", tag: "URG", read: false },
  { id: 2, sender: "Admin Team", preview: "New consent form submitted for review...", time: "2h", tag: "NEW", read: false },
  { id: 3, sender: "Reception Desk", preview: "Patient arrived for 10am appointment...", time: "2h", tag: null, read: true },
  { id: 4, sender: "Compliance Office", preview: "Monthly audit report attached...", time: "2h", tag: null, read: true },
  { id: 5, sender: "Dr. L. Kim", preview: "Follow-up on escalation #T-2101...", time: "2h", tag: null, read: true },
  { id: 6, sender: "Scheduling", preview: "Room 3B is available from 2pm...", time: "2h", tag: null, read: true },
];

export const auditLogs = [
  { time: "14:30:12", user: "user1", action: "View record", resource: "P-1042", risk: "High", status: "OK" },
  { time: "14:29:12", user: "user2", action: "Edit record", resource: "P-1041", risk: "Med", status: "OK" },
  { time: "14:28:12", user: "user3", action: "Approve record", resource: "P-1040", risk: "Low", status: "OK" },
  { time: "14:27:12", user: "user4", action: "Export record", resource: "P-1039", risk: "High", status: "OK" },
  { time: "14:26:12", user: "user5", action: "Login", resource: "P-1038", risk: "Med", status: "OK" },
  { time: "14:25:12", user: "user6", action: "View record", resource: "P-1037", risk: "Low", status: "OK" },
  { time: "14:24:12", user: "user7", action: "Edit record", resource: "P-1036", risk: "High", status: "OK" },
  { time: "14:23:12", user: "user8", action: "Approve record", resource: "P-1035", risk: "Med", status: "OK" },
  { time: "14:22:12", user: "user9", action: "Export record", resource: "P-1034", risk: "Low", status: "OK" },
];

export const users = [
  { id: 1, name: "User 1", role: "ADMIN", department: "Operations", permissions: "Full access", lastActive: "1h ago", active: true },
  { id: 2, name: "User 2", role: "CLINICIAN", department: "Cardiology", permissions: "Read/Write", lastActive: "2h ago", active: true },
  { id: 3, name: "User 3", role: "COMPLIANCE", department: "Legal", permissions: "Read + Audit", lastActive: "3h ago", active: true },
  { id: 4, name: "User 4", role: "MANAGER", department: "Nursing", permissions: "Approve", lastActive: "4h ago", active: true },
  { id: 5, name: "User 5", role: "CLINICIAN", department: "Pediatrics", permissions: "Read/Write", lastActive: "5h ago", active: false },
  { id: 6, name: "User 6", role: "OPERATOR", department: "Front Desk", permissions: "Limited", lastActive: "6h ago", active: true },
  { id: 7, name: "User 7", role: "AUDITOR", department: "External", permissions: "Audit only", lastActive: "7h ago", active: true },
];

export const records = [
  { id: 1, title: "Patient intake form — P-1042", type: "Intake", date: "Apr 26", confidentiality: "Standard" },
  { id: 2, title: "Consent record — Sarah T.", type: "Consent", date: "Apr 25", confidentiality: "High" },
  { id: 3, title: "Insurance verification — P-1040", type: "Insurance", date: "Apr 24", confidentiality: "Standard" },
  { id: 4, title: "Medical history — P-1039", type: "History", date: "Apr 23", confidentiality: "High" },
  { id: 5, title: "Referral letter — Dr. Lee", type: "Referral", date: "Apr 22", confidentiality: "Standard" },
];
