// Sample data for local UI preview only (VITE_DEMO_MODE=true).
// Never imported unless that flag is set — see api/appointments.ts and
// api/doctors.ts, which check it before falling back to this module.
import type {
  Appointment, AppointmentDetail, AppointmentStatus, AppointmentType,
  Availability, CalendarMonth, CalendarMonthMarker, CurrentUser, DayView, Doctor, Patient,
} from "../api/types";

export const demoUser: CurrentUser = {
  id: "demo-user-1", email: "s.kapoor@royalmelb.health", fullName: "S. Kapoor",
  role: "admin", department: "Administration", isActive: true, grantedPermissions: [],
};

export const demoDoctors: Doctor[] = [
  { id: "doc-1", fullName: "Dr Sanjay Kapoor", department: "General Practice" },
  { id: "doc-2", fullName: "Dr R. Patel", department: "Procedures" },
];

export const demoPatients: Patient[] = [
  { id: "patient-1", mrn: "MRN-8842301", name: "Williams Jamie", dob: "1979-03-04", gender: "female", status: "active", createdAt: new Date().toISOString() },
  { id: "patient-2", mrn: "MRN-1120044", name: "Morrison James", dob: "1985-11-20", gender: "male", status: "active", createdAt: new Date().toISOString() },
  { id: "patient-3", mrn: "MRN-7734211", name: "Nguyen Benjamin", dob: "1990-06-15", gender: "male", status: "active", createdAt: new Date().toISOString() },
  { id: "patient-4", mrn: "MRN-2210987", name: "Chen Sarah", dob: "1978-02-02", gender: "female", status: "active", createdAt: new Date().toISOString() },
];

function iso(daysFromNow: number, hour: number, minute = 0): string {
  const d = new Date();
  d.setDate(d.getDate() + daysFromNow);
  d.setHours(hour, minute, 0, 0);
  return d.toISOString();
}

function addMinutes(isoStr: string, minutes: number): string {
  return new Date(new Date(isoStr).getTime() + minutes * 60000).toISOString();
}

interface Seed { patient: string; mrn: string; type: AppointmentType; status: AppointmentStatus; doctorId: string; day: number; hour: number; minute?: number; duration: number; location: string; }

const SEEDS: Seed[] = [
  { patient: "Williams Jamie", mrn: "MRN-8842301", type: "new_patient", status: "confirmed", doctorId: "doc-1", day: 0, hour: 9, duration: 60, location: "Room 3 Level 2" },
  { patient: "Morrison James", mrn: "MRN-1120044", type: "follow_up", status: "confirmed", doctorId: "doc-1", day: 0, hour: 10, minute: 30, duration: 30, location: "Room 3 Level 2" },
  { patient: "Nguyen Benjamin", mrn: "MRN-7734211", type: "procedure", status: "pending", doctorId: "doc-2", day: 0, hour: 14, duration: 60, location: "Procedure Suite" },
  { patient: "Chen Linda", mrn: "MRN-9012233", type: "follow_up", status: "cancelled", doctorId: "doc-1", day: 0, hour: 14, minute: 30, duration: 30, location: "Room 3 Level 2" },
  { patient: "Chen Sarah", mrn: "MRN-2210987", type: "follow_up", status: "confirmed", doctorId: "doc-1", day: -1, hour: 8, minute: 30, duration: 30, location: "Room 1" },
  { patient: "Kapoor Rajan", mrn: "MRN-5567123", type: "new_patient", status: "confirmed", doctorId: "doc-1", day: -1, hour: 10, duration: 60, location: "Room 1" },
  { patient: "Johnson Steve", mrn: "MRN-4432198", type: "new_patient", status: "confirmed", doctorId: "doc-1", day: 2, hour: 9, duration: 30, location: "Room 3 Level 2" },
  { patient: "Davis Michael", mrn: "MRN-3321456", type: "new_patient", status: "confirmed", doctorId: "doc-1", day: 2, hour: 13, duration: 30, location: "Room 2" },
  { patient: "Smith Anna", mrn: "MRN-6654321", type: "new_patient", status: "confirmed", doctorId: "doc-1", day: 3, hour: 9, minute: 30, duration: 30, location: "Room 1" },
  { patient: "Jones Beth", mrn: "MRN-1198877", type: "new_patient", status: "confirmed", doctorId: "doc-1", day: 3, hour: 11, duration: 30, location: "Room 1" },
  { patient: "Park Sam", mrn: "MRN-8871234", type: "new_patient", status: "cancelled", doctorId: "doc-1", day: 5, hour: 11, duration: 30, location: "Room 2" },
];

export const demoAppointments: Appointment[] = SEEDS.map((s, i) => {
  const start = iso(s.day, s.hour, s.minute ?? 0);
  return {
    id: `appt-${i + 1}`, caseId: `case-${i + 1}`, doctorId: s.doctorId, timeSlot: start,
    endTime: addMinutes(start, s.duration), durationMinutes: s.duration, appointmentType: s.type,
    location: s.location, reason: "Fatigue and shortness of breath — ongoing for 6 weeks.",
    internalNotes: "Ensure consent forms completed before consultation.", status: s.status,
    referenceCode: `APT-DEMO-${String(i + 1).padStart(4, "0")}`, notifyPatient: true, notifyProvider: true,
    seriesId: null, createdAt: start, updatedAt: start,
    doctorName: demoDoctors.find(d => d.id === s.doctorId)?.fullName ?? null,
    patientName: s.patient, patientMrn: s.mrn,
  };
});

export function demoAppointmentDetail(id: string): AppointmentDetail {
  const a = demoAppointments.find(x => x.id === id) ?? demoAppointments[0];
  return {
    ...a,
    patient: { id: "patient-1", mrn: a.patientMrn, name: a.patientName ?? "Unknown", dob: "1979-03-04", gender: "female" },
    consent: { status: "captured", capturedAt: a.createdAt },
    history: [
      { action: "appointment.booked", label: "Appointment booked", actorLabel: "s.kapoor@royalmelb.health", timestamp: a.createdAt, details: {} },
      { action: "consent.captured", label: "Consent completed", actorLabel: "front desk", timestamp: a.createdAt, details: {} },
    ],
  };
}

function computeStats(items: Appointment[]) {
  const todayStart = new Date(); todayStart.setHours(0, 0, 0, 0);
  const todayEnd = new Date(todayStart); todayEnd.setDate(todayEnd.getDate() + 1);
  return {
    scheduled: items.filter(a => a.status === "pending" || a.status === "confirmed").length,
    pendingConfirmation: items.filter(a => a.status === "pending").length,
    confirmedToday: items.filter(a => a.status === "confirmed" && new Date(a.timeSlot) >= todayStart && new Date(a.timeSlot) < todayEnd).length,
    cancellations: items.filter(a => a.status === "cancelled").length,
  };
}

export function demoCalendarMonth(year: number, month: number): CalendarMonth {
  const inMonth = demoAppointments.filter(a => { const d = new Date(a.timeSlot); return d.getFullYear() === year && d.getMonth() + 1 === month; });
  const byDate = new Map<string, Appointment[]>();
  for (const a of inMonth) {
    const key = new Date(a.timeSlot).toISOString().slice(0, 10);
    if (!byDate.has(key)) byDate.set(key, []);
    byDate.get(key)!.push(a);
  }
  return {
    year, month, stats: computeStats(inMonth),
    days: [...byDate.entries()].sort(([a], [b]) => a.localeCompare(b)).map(([date, appointments]) => ({ date, appointments, total: appointments.length })),
  };
}

export function demoCalendarMarkers(year: number, month: number): CalendarMonthMarker[] {
  return demoCalendarMonth(year, month).days.map(d => ({ date: d.date, count: d.total }));
}

export function demoDayView(date: string): DayView {
  const items = demoAppointments.filter(a => a.timeSlot.slice(0, 10) === date);
  const providerCounts = new Map<string, number>();
  for (const a of items) if (a.status !== "cancelled") providerCounts.set(a.doctorId, (providerCounts.get(a.doctorId) ?? 0) + 1);
  return {
    date, stats: computeStats(items), appointments: items,
    totalBookedMinutes: items.filter(a => a.status !== "cancelled").reduce((sum, a) => sum + a.durationMinutes, 0),
    statusBreakdown: items.reduce((acc, a) => { acc[a.status] = (acc[a.status] ?? 0) + 1; return acc; }, {} as Record<string, number>),
    providers: [...providerCounts.entries()].map(([doctorId, appointmentCount]) => ({
      doctorId, doctorName: demoDoctors.find(d => d.id === doctorId)?.fullName ?? "Unknown", appointmentCount,
    })),
  };
}

export function demoAvailability(doctorId: string, date: string): Availability {
  const booked = demoAppointments.filter(a => a.doctorId === doctorId && a.timeSlot.slice(0, 10) === date && a.status !== "cancelled");
  const slots = [];
  for (let h = 9; h < 17; h++) {
    for (const m of [0, 30]) {
      const start = new Date(`${date}T${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}:00`);
      const end = new Date(start.getTime() + 30 * 60000);
      const isLunch = h === 12;
      const overlapsBooked = booked.some(b => new Date(b.timeSlot) < end && new Date(b.endTime) > start);
      slots.push({ start: start.toISOString(), end: end.toISOString(), available: !isLunch && !overlapsBooked });
    }
  }
  return { doctorId, date, slotMinutes: 30, slots };
}

// In-memory mutations below let the preview feel interactive (new/edited/
// cancelled appointments actually show up while you click around) without
// a backend — nothing here persists past a page refresh.
let nextDemoId = demoAppointments.length + 1;

export function demoCreateAppointment(input: {
  doctorId: string; timeSlot: string; durationMinutes: number; appointmentType: AppointmentType;
  location?: string; reason?: string; internalNotes?: string; patientLabel: string;
}): Appointment {
  const id = `appt-${nextDemoId++}`;
  const appt: Appointment = {
    id, caseId: `case-${id}`, doctorId: input.doctorId, timeSlot: input.timeSlot,
    endTime: addMinutes(input.timeSlot, input.durationMinutes), durationMinutes: input.durationMinutes,
    appointmentType: input.appointmentType, location: input.location ?? null, reason: input.reason ?? null,
    internalNotes: input.internalNotes ?? null, status: "confirmed", referenceCode: `APT-DEMO-${String(nextDemoId).padStart(4, "0")}`,
    notifyPatient: true, notifyProvider: true, seriesId: null, createdAt: new Date().toISOString(), updatedAt: new Date().toISOString(),
    doctorName: demoDoctors.find(d => d.id === input.doctorId)?.fullName ?? null, patientName: input.patientLabel, patientMrn: null,
  };
  demoAppointments.push(appt);
  return appt;
}

export function demoUpdateAppointment(id: string, patch: Partial<Appointment>): Appointment {
  const existing = demoAppointments.find(a => a.id === id);
  if (!existing) throw new Error("Appointment not found");
  Object.assign(existing, patch, { updatedAt: new Date().toISOString() });
  if (patch.timeSlot || patch.durationMinutes) {
    existing.endTime = addMinutes(existing.timeSlot, existing.durationMinutes);
  }
  return existing;
}

export function demoCancelAppointment(id: string): Appointment {
  return demoUpdateAppointment(id, { status: "cancelled" });
}

export function demoCompleteAppointment(id: string): Appointment {
  return demoUpdateAppointment(id, { status: "completed" });
}
