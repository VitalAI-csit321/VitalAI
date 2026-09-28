import type { AppointmentStatus, AppointmentType } from "../api/types";

export const TYPE_LABEL: Record<AppointmentType, string> = {
  new_patient: "New Patient",
  follow_up: "Follow Up",
  procedure: "Procedure",
  other: "Other",
};

export const TYPE_COLOR: Record<AppointmentType, { bg: string; text: string; dot: string; border: string }> = {
  new_patient: { bg: "bg-emerald-50", text: "text-emerald-800", dot: "bg-emerald-500", border: "border-emerald-500" },
  follow_up: { bg: "bg-blue-50", text: "text-blue-800", dot: "bg-blue-500", border: "border-blue-500" },
  procedure: { bg: "bg-amber-50", text: "text-amber-900", dot: "bg-amber-600", border: "border-amber-600" },
  other: { bg: "bg-slate-100", text: "text-slate-700", dot: "bg-slate-400", border: "border-slate-400" },
};

export const STATUS_LABEL: Record<AppointmentStatus, string> = {
  pending: "Pending",
  confirmed: "Confirmed",
  cancelled: "Cancelled",
  completed: "Completed",
};

export const STATUS_TONE: Record<AppointmentStatus, "green" | "amber" | "red" | "gray"> = {
  pending: "amber",
  confirmed: "green",
  cancelled: "gray",
  completed: "green",
};

// Clinic wall-clock time. The backend schedules in settings.clinic_timezone
// (Australia/Sydney by default) and GET /health reports it. These helpers used
// to assume the clinic ran on UTC: an "11:00" booking was stored as 10pm in
// Sydney, and the email agent's 8am bookings showed at 9 or 10pm the day before.
let clinicTimeZone = "Australia/Sydney";

export function setClinicTimeZone(zone: string): void {
  clinicTimeZone = zone;
}

function clinicParts(d: Date): { date: string; hour: number; minute: number } {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: clinicTimeZone, year: "numeric", month: "2-digit", day: "2-digit",
    hour: "2-digit", minute: "2-digit", hourCycle: "h23",
  }).formatToParts(d);
  const get = (type: string) => parts.find(p => p.type === type)!.value;
  return { date: `${get("year")}-${get("month")}-${get("day")}`, hour: Number(get("hour")), minute: Number(get("minute")) };
}

export function formatTime(iso: string): string {
  return new Date(iso).toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit", timeZone: clinicTimeZone });
}

/** Hours since clinic midnight, fractional, for placing an appointment on the day grid. */
export function clinicHour(d: Date): number {
  const p = clinicParts(d);
  return p.hour + p.minute / 60;
}

export function formatDateLong(iso: string): string {
  return new Date(iso).toLocaleDateString("en-US", { weekday: "long", day: "numeric", month: "long", year: "numeric" });
}

export function formatDateShort(iso: string): string {
  return new Date(iso).toLocaleDateString("en-US", { day: "numeric", month: "short", year: "numeric" });
}

export function toDateInputValue(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

export function toDateInputValueClinic(d: Date): string {
  return clinicParts(d).date;
}

export function toTimeInputValueClinic(d: Date): string {
  const p = clinicParts(d);
  return `${String(p.hour).padStart(2, "0")}:${String(p.minute).padStart(2, "0")}`;
}

/** The instant a clinic wall-clock date and time names, daylight saving included. */
export function parseClinicDateTime(date: string, time: string): Date {
  const [y, m, d] = date.split("-").map(Number);
  const [h, min] = time.split(":").map(Number);
  const wanted = Date.UTC(y, m - 1, d, h, min);
  let instant = wanted;
  // Twice: once to apply the zone's offset, once more in case that crossed a DST change.
  for (let i = 0; i < 2; i++) {
    const p = clinicParts(new Date(instant));
    const [py, pm, pd] = p.date.split("-").map(Number);
    instant += wanted - Date.UTC(py, pm - 1, pd, p.hour, p.minute);
  }
  return new Date(instant);
}

export function patientDisplayName(a: { patientName: string | null }): string {
  return a.patientName ?? "Unknown patient";
}

export function patientInitials(name: string): string {
  const parts = name.trim().split(/\s+/);
  return parts.length === 1 ? parts[0].slice(0, 2).toUpperCase() : (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
}

export const MONTH_NAMES = [
  "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December",
];
