// The one date style for the whole app (Australian), in the clinic's time zone:
// "30 Sept 2026", "7:28 am". The backend schedules in settings.clinic_timezone
// and GET /health reports it; main.tsx passes it in at startup.
let clinicZone = "Australia/Sydney";
export const setClinicTimeZone = (zone: string) => { clinicZone = zone; };
export const clinicTimeZone = () => clinicZone;

const DAY_ONLY = /^\d{4}-\d{2}-\d{2}$/;

export function formatDate(value: string | Date): string {
  // A birth or expiry date is a calendar day, not an instant: never shift it.
  const timeZone = typeof value === "string" && DAY_ONLY.test(value) ? "UTC" : clinicZone;
  return new Date(value).toLocaleDateString("en-AU", { day: "numeric", month: "short", year: "numeric", timeZone });
}
export const formatTime = (value: string | Date) =>
  new Date(value).toLocaleTimeString("en-AU", { hour: "numeric", minute: "2-digit", timeZone: clinicZone });
export const formatDateTime = (value: string | Date) => `${formatDate(value)}, ${formatTime(value)}`;
export const formatDateLong = (value: string | Date) =>
  new Date(value).toLocaleDateString("en-AU", { weekday: "long", day: "numeric", month: "long", year: "numeric", timeZone: clinicZone });

// A system code as words: "email.dispatch_recorded" -> "Email dispatch recorded".
export function humanize(code: string): string {
  const s = code.replace(/[._]+/g, " ").trim().toLowerCase();
  return s.charAt(0).toUpperCase() + s.slice(1);
}

const CONTACT_STATUS: Record<string, string> = {
  intake_received: "Received",
  intake_incomplete: "Incomplete",
  consent_pending: "Awaiting consent",
  consent_captured: "Consent given",
  context_ready: "Ready",
  context_insufficient: "Needs more information",
  triage_routine: "Routine",
  triage_time_sensitive: "Time-sensitive",
  triage_immediate: "Urgent",
};
export const contactStatusLabel = (status: string) => CONTACT_STATUS[status] ?? humanize(status);
