import { apiGet } from "../lib/apiClient";
import { isDemoMode } from "../lib/demoMode";
import { demoDoctors } from "../data/demoData";
import type { Doctor } from "./types";

interface RawDoctor { id: string; full_name: string; department: string | null; }

function toDoctor(r: RawDoctor): Doctor {
  return { id: r.id, fullName: r.full_name, department: r.department };
}

export async function listDoctors(search?: string): Promise<Doctor[]> {
  if (isDemoMode()) {
    if (!search) return demoDoctors;
    const q = search.toLowerCase();
    return demoDoctors.filter(d => d.fullName.toLowerCase().includes(q));
  }
  const raw = await apiGet<RawDoctor[]>("/api/v1/doctors", search ? { search } : undefined);
  return raw.map(toDoctor);
}
