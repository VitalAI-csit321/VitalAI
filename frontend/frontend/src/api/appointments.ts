import { apiGet, apiPatch, apiPost } from "../lib/apiClient";
import { isDemoMode } from "../lib/demoMode";
import {
  demoAppointmentDetail, demoAppointments, demoAvailability, demoCalendarMarkers, demoCalendarMonth,
  demoCancelAppointment, demoCompleteAppointment, demoCreateAppointment, demoDayView, demoPatients, demoUpdateAppointment,
} from "../data/demoData";
import type {
  Appointment,
  AppointmentDetail,
  AppointmentStatus,
  AppointmentType,
  Availability,
  CalendarMonth,
  CalendarMonthMarker,
  DayView,
  Gender,
} from "./types";

interface RawAppointment {
  id: string; case_id: string; doctor_id: string; time_slot: string; end_time: string;
  duration_minutes: number; appointment_type: AppointmentType; location: string | null;
  reason: string | null; internal_notes: string | null; status: AppointmentStatus;
  reference_code: string; notify_patient: boolean; notify_provider: boolean;
  series_id: string | null; created_at: string; updated_at: string;
  doctor_name: string | null; patient_name: string | null; patient_mrn: string | null;
}

interface RawDetail extends RawAppointment {
  patient: { id: string | null; mrn: string | null; name: string; dob: string | null; gender: string | null } | null;
  consent: { status: string; captured_at: string | null } | null;
  history: { action: string; label: string; actor_label: string | null; timestamp: string; details: Record<string, unknown> }[];
}

function toAppointment(r: RawAppointment): Appointment {
  return {
    id: r.id, caseId: r.case_id, doctorId: r.doctor_id, timeSlot: r.time_slot, endTime: r.end_time,
    durationMinutes: r.duration_minutes, appointmentType: r.appointment_type, location: r.location,
    reason: r.reason, internalNotes: r.internal_notes, status: r.status, referenceCode: r.reference_code,
    notifyPatient: r.notify_patient, notifyProvider: r.notify_provider, seriesId: r.series_id,
    createdAt: r.created_at, updatedAt: r.updated_at, doctorName: r.doctor_name,
    patientName: r.patient_name, patientMrn: r.patient_mrn,
  };
}

function toDetail(r: RawDetail): AppointmentDetail {
  return {
    ...toAppointment(r),
    patient: r.patient
      ? {
          id: r.patient.id, mrn: r.patient.mrn, name: r.patient.name, dob: r.patient.dob,
          gender: r.patient.gender as Gender | null,
        }
      : null,
    consent: r.consent ? { status: r.consent.status, capturedAt: r.consent.captured_at } : null,
    history: r.history.map(h => ({
      action: h.action, label: h.label, actorLabel: h.actor_label, timestamp: h.timestamp, details: h.details,
    })),
  };
}

export interface AppointmentListParams {
  doctorId?: string; dateFrom?: string; dateTo?: string; appointmentType?: AppointmentType;
  status?: AppointmentStatus; search?: string; limit?: number; offset?: number;
}

export async function listAppointments(
  params: AppointmentListParams = {},
): Promise<{ items: Appointment[]; total: number }> {
  if (isDemoMode()) {
    let items = demoAppointments;
    if (params.doctorId) items = items.filter(a => a.doctorId === params.doctorId);
    if (params.status) items = items.filter(a => a.status === params.status);
    if (params.appointmentType) items = items.filter(a => a.appointmentType === params.appointmentType);
    if (params.dateFrom) items = items.filter(a => a.timeSlot >= params.dateFrom!);
    if (params.dateTo) items = items.filter(a => a.timeSlot < params.dateTo!);
    if (params.search) {
      const q = params.search.toLowerCase();
      items = items.filter(a => (a.patientName ?? "").toLowerCase().includes(q) || (a.doctorName ?? "").toLowerCase().includes(q));
    }
    return { items: [...items].sort((a, b) => a.timeSlot.localeCompare(b.timeSlot)), total: items.length };
  }
  const page = await apiGet<{ items: RawAppointment[]; total: number }>("/api/v1/appointments", {
    doctor_id: params.doctorId, date_from: params.dateFrom, date_to: params.dateTo,
    appointment_type: params.appointmentType, status: params.status, search: params.search,
    limit: params.limit, offset: params.offset,
  });
  return { items: page.items.map(toAppointment), total: page.total };
}

export async function getCalendarMonth(year: number, month: number, doctorId?: string): Promise<CalendarMonth> {
  if (isDemoMode()) return demoCalendarMonth(year, month);
  const raw = await apiGet<{
    year: number; month: number;
    stats: { scheduled: number; pending_confirmation: number; confirmed_today: number; cancellations: number };
    days: { date: string; appointments: RawAppointment[]; total: number }[];
  }>("/api/v1/appointments/calendar", { year, month, doctor_id: doctorId });
  return {
    year: raw.year, month: raw.month,
    stats: {
      scheduled: raw.stats.scheduled, pendingConfirmation: raw.stats.pending_confirmation,
      confirmedToday: raw.stats.confirmed_today, cancellations: raw.stats.cancellations,
    },
    days: raw.days.map(d => ({ date: d.date, total: d.total, appointments: d.appointments.map(toAppointment) })),
  };
}

export async function getCalendarMarkers(year: number, month: number, doctorId?: string): Promise<CalendarMonthMarker[]> {
  if (isDemoMode()) return demoCalendarMarkers(year, month);
  const raw = await apiGet<{ date: string; count: number }[]>("/api/v1/appointments/calendar/markers", {
    year, month, doctor_id: doctorId,
  });
  return raw.map(m => ({ date: m.date, count: m.count }));
}

export async function getDayView(date: string, doctorId?: string): Promise<DayView> {
  if (isDemoMode()) return demoDayView(date);
  const raw = await apiGet<{
    date: string;
    stats: { scheduled: number; pending_confirmation: number; confirmed_today: number; cancellations: number };
    appointments: RawAppointment[]; total_booked_minutes: number; status_breakdown: Record<string, number>;
    providers: { doctor_id: string; doctor_name: string; appointment_count: number }[];
  }>("/api/v1/appointments/day", { date, doctor_id: doctorId });
  return {
    date: raw.date,
    stats: {
      scheduled: raw.stats.scheduled, pendingConfirmation: raw.stats.pending_confirmation,
      confirmedToday: raw.stats.confirmed_today, cancellations: raw.stats.cancellations,
    },
    appointments: raw.appointments.map(toAppointment),
    totalBookedMinutes: raw.total_booked_minutes,
    statusBreakdown: raw.status_breakdown,
    providers: raw.providers.map(p => ({ doctorId: p.doctor_id, doctorName: p.doctor_name, appointmentCount: p.appointment_count })),
  };
}

export async function getAvailability(doctorId: string, date: string, slotMinutes = 30): Promise<Availability> {
  if (isDemoMode()) return demoAvailability(doctorId, date);
  const raw = await apiGet<{
    doctor_id: string; date: string; slot_minutes: number;
    slots: { start: string; end: string; available: boolean }[];
  }>("/api/v1/appointments/availability", { doctor_id: doctorId, date, slot_minutes: slotMinutes });
  return { doctorId: raw.doctor_id, date: raw.date, slotMinutes: raw.slot_minutes, slots: raw.slots };
}

export async function getAppointment(id: string): Promise<AppointmentDetail> {
  if (isDemoMode()) return demoAppointmentDetail(id);
  return toDetail(await apiGet<RawDetail>(`/api/v1/appointments/${id}`));
}

export interface CreateAppointmentInput {
  doctorId: string; caseId: string; timeSlot: string; durationMinutes?: number;
  appointmentType?: AppointmentType; location?: string; reason?: string; internalNotes?: string;
  status?: AppointmentStatus; notifyPatient?: boolean; notifyProvider?: boolean;
  repeat?: { intervalDays: number; occurrences: number };
}

export async function createAppointment(input: CreateAppointmentInput): Promise<Appointment> {
  if (isDemoMode()) {
    const patient = demoPatients.find(p => p.id === input.caseId.replace("demo-case-", "")) ?? demoPatients[0];
    return demoCreateAppointment({
      doctorId: input.doctorId, timeSlot: input.timeSlot, durationMinutes: input.durationMinutes ?? 30,
      appointmentType: input.appointmentType ?? "other", location: input.location, reason: input.reason,
      internalNotes: input.internalNotes, patientLabel: patient.name,
    });
  }
  return toAppointment(
    await apiPost<RawAppointment>("/api/v1/appointments", {
      doctor_id: input.doctorId, case_id: input.caseId, time_slot: input.timeSlot,
      duration_minutes: input.durationMinutes, appointment_type: input.appointmentType,
      location: input.location, reason: input.reason, internal_notes: input.internalNotes,
      status: input.status, notify_patient: input.notifyPatient, notify_provider: input.notifyProvider,
      repeat: input.repeat
        ? { interval_days: input.repeat.intervalDays, occurrences: input.repeat.occurrences }
        : undefined,
    }),
  );
}

export interface UpdateAppointmentInput {
  doctorId?: string; timeSlot?: string; durationMinutes?: number; appointmentType?: AppointmentType;
  location?: string; reason?: string; internalNotes?: string; status?: AppointmentStatus;
  notifyPatient?: boolean; notifyProvider?: boolean; rescheduleReason?: string;
}

export async function updateAppointment(id: string, input: UpdateAppointmentInput): Promise<Appointment> {
  if (isDemoMode()) {
    return demoUpdateAppointment(id, {
      doctorId: input.doctorId, timeSlot: input.timeSlot, durationMinutes: input.durationMinutes,
      appointmentType: input.appointmentType, location: input.location, reason: input.reason,
      internalNotes: input.internalNotes, status: input.status,
    });
  }
  return toAppointment(
    await apiPatch<RawAppointment>(`/api/v1/appointments/${id}`, {
      doctor_id: input.doctorId, time_slot: input.timeSlot, duration_minutes: input.durationMinutes,
      appointment_type: input.appointmentType, location: input.location, reason: input.reason,
      internal_notes: input.internalNotes, status: input.status, notify_patient: input.notifyPatient,
      notify_provider: input.notifyProvider, reschedule_reason: input.rescheduleReason,
    }),
  );
}

export async function cancelAppointment(id: string, cancelReason?: string, notifyPatient = true): Promise<Appointment> {
  if (isDemoMode()) return demoCancelAppointment(id);
  return toAppointment(
    await apiPost<RawAppointment>(`/api/v1/appointments/${id}/cancel`, {
      cancel_reason: cancelReason, notify_patient: notifyPatient,
    }),
  );
}

export async function completeAppointment(id: string): Promise<Appointment> {
  if (isDemoMode()) return demoCompleteAppointment(id);
  return toAppointment(await apiPost<RawAppointment>(`/api/v1/appointments/${id}/complete`));
}
