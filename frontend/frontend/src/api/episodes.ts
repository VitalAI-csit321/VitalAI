// Cases: episodes of care (backend /api/v1/cases). In the UI a "case" is one
// clinical problem; the per-message rows under /intake are "contacts".
import { apiGet, apiPatch, apiPost } from "../lib/apiClient";

export type EpisodeStatus = "open" | "closed";

export interface Episode {
  id: string; patientId: string; patientName: string | null; title: string;
  status: EpisodeStatus; doctorId: string | null; doctorName: string | null;
  openedAt: string; closedAt: string | null; outcomeNote: string | null; lastActivityAt: string;
}

export interface TimelineEntry {
  kind: "contact" | "appointment" | "consent" | "review";
  id: string; at: string; label: string; status: string | null;
  contactId: string | null; inboxTaskId: string | null;
}

export interface EpisodeDetail extends Episode { timeline: TimelineEntry[] }

interface RawEpisode {
  id: string; patient_id: string; patient_name: string | null; title: string; status: EpisodeStatus;
  doctor_id: string | null; doctor_name: string | null; opened_at: string; closed_at: string | null;
  outcome_note: string | null; last_activity_at: string;
}

interface RawTimelineEntry {
  kind: TimelineEntry["kind"]; id: string; at: string; label: string; status: string | null;
  contact_id: string | null; inbox_task_id: string | null;
}

function toEpisode(r: RawEpisode): Episode {
  return {
    id: r.id, patientId: r.patient_id, patientName: r.patient_name, title: r.title, status: r.status,
    doctorId: r.doctor_id, doctorName: r.doctor_name, openedAt: r.opened_at, closedAt: r.closed_at,
    outcomeNote: r.outcome_note, lastActivityAt: r.last_activity_at,
  };
}

export async function listEpisodes(params: { patientId?: string; status?: EpisodeStatus } = {}): Promise<Episode[]> {
  const q: Record<string, unknown> = { limit: 200 };
  if (params.patientId) q.patient_id = params.patientId;
  if (params.status) q.status = params.status;
  const page = await apiGet<{ items: RawEpisode[]; total: number }>("/api/v1/cases", q);
  return page.items.map(toEpisode);
}

export async function getEpisode(id: string): Promise<EpisodeDetail> {
  const r = await apiGet<RawEpisode & { timeline: RawTimelineEntry[] }>(`/api/v1/cases/${id}`);
  return {
    ...toEpisode(r),
    timeline: r.timeline.map(t => ({
      kind: t.kind, id: t.id, at: t.at, label: t.label, status: t.status,
      contactId: t.contact_id, inboxTaskId: t.inbox_task_id,
    })),
  };
}

export async function createEpisode(input: { patientId: string; title: string; doctorId?: string | null }): Promise<Episode> {
  return toEpisode(await apiPost<RawEpisode>("/api/v1/cases", {
    patient_id: input.patientId, title: input.title, doctor_id: input.doctorId || null,
  }));
}

export async function updateEpisode(id: string, input: { title?: string; doctorId?: string }): Promise<Episode> {
  return toEpisode(await apiPatch<RawEpisode>(`/api/v1/cases/${id}`, { title: input.title, doctor_id: input.doctorId }));
}

export async function closeEpisode(id: string, note: string): Promise<Episode> {
  return toEpisode(await apiPost<RawEpisode>(`/api/v1/cases/${id}/close`, { note }));
}

export async function reopenEpisode(id: string): Promise<Episode> {
  return toEpisode(await apiPost<RawEpisode>(`/api/v1/cases/${id}/reopen`, {}));
}

// The contact a staff booking or consent files under: the case's latest
// contact, or a new "staff" one. Returns the contact id.
export async function staffContactFor(episodeId: string, reason: string): Promise<string> {
  return (await apiPost<{ id: string }>(`/api/v1/cases/${episodeId}/contact`, { reason })).id;
}

// Move a contact, appointment or consent to another case of the same patient
// (targetEpisodeId), or to a new one (newTitle). patientId confirms who an
// unconfirmed contact (a voicemail) is from.
export async function moveToEpisode(input: {
  kind: "contact" | "appointment" | "consent"; itemId: string;
  targetEpisodeId?: string | null; newTitle?: string; patientId?: string;
}): Promise<Episode> {
  return toEpisode(await apiPost<RawEpisode>("/api/v1/cases/move", {
    kind: input.kind, item_id: input.itemId, target_episode_id: input.targetEpisodeId ?? null,
    new_title: input.newTitle, patient_id: input.patientId,
  }));
}

// A picker value: an open case's id, or NEW_CASE to open one with a title.
export const NEW_CASE = "__new__";

// Resolves a picker choice to a case id, opening the new case when asked.
export async function resolveCaseChoice(patientId: string, choice: string, newTitle: string): Promise<string | null> {
  if (!choice) return null;
  if (choice !== NEW_CASE) return choice;
  return (await createEpisode({ patientId, title: newTitle.trim() || "New case" })).id;
}
