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

export function formatTime(iso: string): string {
  return new Date(iso).toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" });
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
