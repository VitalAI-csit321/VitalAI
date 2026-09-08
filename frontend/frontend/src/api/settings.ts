import { apiGet, apiPatch } from "../lib/apiClient";
import type { AppSettingItem } from "./types";

interface RawSetting {
  key: string; value: unknown; default: unknown; type: AppSettingItem["type"];
  group: string; label: string; help: string;
  minimum: number | null; maximum: number | null; editable: boolean;
  updated_by: string | null; updated_at: string | null;
}

function toSetting(r: RawSetting): AppSettingItem {
  return {
    key: r.key, value: r.value, default: r.default, type: r.type,
    group: r.group, label: r.label, help: r.help,
    minimum: r.minimum, maximum: r.maximum, editable: r.editable,
    updatedBy: r.updated_by, updatedAt: r.updated_at,
  };
}

export async function listSettings(): Promise<AppSettingItem[]> {
  const res = await apiGet<{ items: RawSetting[] }>("/api/v1/settings");
  return res.items.map(toSetting);
}

export async function updateSettings(values: Record<string, unknown>): Promise<AppSettingItem[]> {
  const res = await apiPatch<{ items: RawSetting[] }>("/api/v1/settings", { values });
  return res.items.map(toSetting);
}
