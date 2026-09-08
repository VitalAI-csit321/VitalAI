import { useEffect, useState } from "react";
import { listSettings, updateSettings } from "../../api/settings";
import type { AppSettingItem } from "../../api/types";
import { describeApiError } from "../../lib/apiClient";
import { Spinner } from "../../components/ui";

// The ten-category taxonomy, mirroring backend/app/models/task.py::TaskCategory.
const TASK_CATEGORIES: { value: string; label: string }[] = [
  { value: "appointment_request", label: "Appointment request" },
  { value: "new_patient_onboarding", label: "New patient onboarding" },
  { value: "prescription_renewal", label: "Prescription renewal" },
  { value: "results_enquiry", label: "Results enquiry" },
  { value: "referral_request", label: "Referral request" },
  { value: "medical_records_request", label: "Medical records request" },
  { value: "billing_insurance_enquiry", label: "Billing / insurance enquiry" },
  { value: "complaint_escalation", label: "Complaint escalation" },
  { value: "general_administrative", label: "General administrative" },
  { value: "urgent_emergency", label: "Urgent / emergency" },
];

const ROLES: { value: string; label: string }[] = [
  { value: "front_desk", label: "Front desk" },
  { value: "operator", label: "Operator" },
  { value: "admin", label: "Admin" },
  { value: "doctor", label: "Doctor" },
];

// Bounded numeric settings rendered as sliders rather than plain number inputs.
const RANGE_KEYS = new Set([
  "task_routing_auto_threshold",
  "task_routing_floor",
  "llm_temperature",
]);

function sameValue(a: unknown, b: unknown): boolean {
  return JSON.stringify(a) === JSON.stringify(b);
}

export function SettingsSection({ group }: { group: string }) {
  const [items, setItems] = useState<AppSettingItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [dirty, setDirty] = useState<Record<string, unknown>>({});
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    let active = true;
    listSettings()
      .then(res => { if (active) setItems(res); })
      .catch(() => { if (active) setLoadError("Could not load settings."); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, []);

  function effectiveValue(item: AppSettingItem): unknown {
    return item.key in dirty ? dirty[item.key] : item.value;
  }

  function setPending(key: string, value: unknown, originalValue: unknown) {
    setSaved(false);
    setDirty(prev => {
      const next = { ...prev };
      if (sameValue(value, originalValue)) delete next[key];
      else next[key] = value;
      return next;
    });
  }

  function resetToDefault(item: AppSettingItem) {
    setPending(item.key, item.default, item.value);
  }

  async function onSave() {
    if (Object.keys(dirty).length === 0) return;
    setSaving(true);
    setSaveError(null);
    try {
      const res = await updateSettings(dirty);
      setItems(res);
      setDirty({});
      setSaved(true);
    } catch (err) {
      setSaveError(describeApiError(err, "Could not save settings."));
    } finally {
      setSaving(false);
    }
  }

  if (loading) return <Spinner label="Loading settings" />;
  if (loadError) return <p className="text-sm text-red-700">{loadError}</p>;

  const groupItems = items.filter(i => i.group === group);
  if (groupItems.length === 0) {
    return <p className="text-sm text-slate-500 py-8 text-center">Nothing to configure here yet.</p>;
  }

  return (
    <div>
      <h2 className="text-base font-semibold text-slate-900 mb-5">{group}</h2>
      <div className="space-y-4">
        {groupItems.map(item => (
          <div key={item.key} className="rounded-xl border border-slate-200 p-4">
            {item.key === "task_routing_category_roles" ? (
              <CategoryRoleEditor item={item} value={effectiveValue(item) as Record<string, string>}
                onChange={v => setPending(item.key, v, item.value)} />
            ) : item.key === "email_no_autosend_categories" ? (
              <CategoryListEditor item={item} value={effectiveValue(item) as string[]}
                onChange={v => setPending(item.key, v, item.value)} />
            ) : (
              <ScalarField item={item} value={effectiveValue(item)}
                onChange={v => setPending(item.key, v, item.value)} />
            )}
            {item.editable && !sameValue(effectiveValue(item), item.default) && (
              <button onClick={() => resetToDefault(item)}
                className="mt-2 text-xs font-medium text-brand hover:underline">
                Reset to default
              </button>
            )}
          </div>
        ))}
      </div>

      <div className="mt-5 flex items-center gap-3">
        <button onClick={onSave} disabled={saving || Object.keys(dirty).length === 0}
          className="rounded-lg bg-brand px-5 py-2 text-sm font-semibold text-white hover:bg-brand-hover disabled:opacity-40 disabled:cursor-not-allowed">
          {saving ? "Saving..." : "Save changes"}
        </button>
        {saved && <span className="text-sm text-emerald-600">Saved.</span>}
        {saveError && <span className="text-sm text-red-700">{saveError}</span>}
      </div>
    </div>
  );
}

function FieldChrome({ item, children }: { item: AppSettingItem; children: React.ReactNode }) {
  return (
    <div>
      <div className="flex items-baseline justify-between">
        <label className="text-sm font-semibold text-slate-900">{item.label}</label>
        {!item.editable && <span className="text-xs font-medium text-slate-400">Read-only</span>}
      </div>
      <div className="mt-1.5">{children}</div>
      {item.help && <p className="mt-1.5 text-xs text-slate-500">{item.help}</p>}
    </div>
  );
}

function ScalarField({
  item, value, onChange,
}: { item: AppSettingItem; value: unknown; onChange: (v: unknown) => void }) {
  const disabled = !item.editable;

  if (item.type === "bool") {
    return (
      <FieldChrome item={item}>
        <label className="inline-flex items-center gap-2 text-sm text-slate-700">
          <input type="checkbox" checked={Boolean(value)} disabled={disabled}
            onChange={e => onChange(e.target.checked)}
            className="h-4 w-4 rounded border-slate-300 text-brand focus:ring-brand" />
          {value ? "Enabled" : "Disabled"}
        </label>
      </FieldChrome>
    );
  }

  if (item.type === "int" || item.type === "float") {
    const step = item.type === "float" ? 0.01 : 1;
    if (RANGE_KEYS.has(item.key)) {
      return (
        <FieldChrome item={item}>
          <div className="flex items-center gap-3">
            <input type="range" min={item.minimum ?? 0} max={item.maximum ?? 1} step={step}
              value={Number(value)} disabled={disabled}
              onChange={e => onChange(parseFloat(e.target.value))}
              className="flex-1 accent-brand" />
            <span className="w-14 text-right text-sm font-medium text-slate-700">
              {Number(value).toFixed(2)}
            </span>
          </div>
        </FieldChrome>
      );
    }
    return (
      <FieldChrome item={item}>
        <input type="number" min={item.minimum ?? undefined} max={item.maximum ?? undefined} step={step}
          value={Number(value)} disabled={disabled}
          onChange={e => onChange(item.type === "int" ? parseInt(e.target.value, 10) : parseFloat(e.target.value))}
          className="w-40 rounded-lg border border-slate-200 px-3.5 py-2 text-sm outline-none focus:border-brand disabled:bg-slate-50 disabled:text-slate-400" />
      </FieldChrome>
    );
  }

  // str
  return (
    <FieldChrome item={item}>
      <input type="text" value={String(value ?? "")} disabled={disabled}
        onChange={e => onChange(e.target.value)}
        className="w-full rounded-lg border border-slate-200 px-3.5 py-2 text-sm outline-none focus:border-brand disabled:bg-slate-50 disabled:text-slate-400" />
    </FieldChrome>
  );
}

function CategoryRoleEditor({
  item, value, onChange,
}: { item: AppSettingItem; value: Record<string, string>; onChange: (v: Record<string, string>) => void }) {
  function setRole(category: string, role: string) {
    const next = { ...value };
    if (role === "") delete next[category];
    else next[category] = role;
    onChange(next);
  }

  return (
    <FieldChrome item={item}>
      <div className="divide-y divide-slate-100 rounded-lg border border-slate-200">
        {TASK_CATEGORIES.map(cat => (
          <div key={cat.value} className="flex items-center justify-between px-3.5 py-2">
            <span className="text-sm text-slate-700">{cat.label}</span>
            <select value={value[cat.value] ?? ""} onChange={e => setRole(cat.value, e.target.value)}
              className="rounded-lg border border-slate-200 px-2.5 py-1.5 text-sm outline-none focus:border-brand">
              <option value="">Default</option>
              {ROLES.map(r => <option key={r.value} value={r.value}>{r.label}</option>)}
            </select>
          </div>
        ))}
      </div>
    </FieldChrome>
  );
}

function CategoryListEditor({
  item, value, onChange,
}: { item: AppSettingItem; value: string[]; onChange: (v: string[]) => void }) {
  function toggle(category: string, checked: boolean) {
    const next = checked ? [...value, category] : value.filter(v => v !== category);
    onChange(next);
  }

  return (
    <FieldChrome item={item}>
      <div className="grid grid-cols-2 gap-2 rounded-lg border border-slate-200 p-3.5">
        {TASK_CATEGORIES.map(cat => (
          <label key={cat.value} className="inline-flex items-center gap-2 text-sm text-slate-700">
            <input type="checkbox" checked={value.includes(cat.value)}
              onChange={e => toggle(cat.value, e.target.checked)}
              className="h-4 w-4 rounded border-slate-300 text-brand focus:ring-brand" />
            {cat.label}
          </label>
        ))}
      </div>
    </FieldChrome>
  );
}
