import { useId } from "react";
import type { ProfileFields } from "../api/cases";

export interface ProfileFieldDef {
  key: keyof ProfileFields;
  apiKey: string;
  label: string;
  type?: "text" | "textarea" | "select" | "date";
  options?: string[];
  naOption?: boolean;
}

export interface ProfileFieldGroup {
  title: string;
  fields: ProfileFieldDef[];
}

export const PROFILE_FIELD_GROUPS: ProfileFieldGroup[] = [
  {
    title: "Details",
    fields: [
      { key: "address", apiKey: "address", label: "Address" },
      {
        key: "indigenousStatus", apiKey: "indigenous_status", label: "Indigenous status", type: "select",
        options: ["Aboriginal", "Torres Strait Islander", "Both", "Neither", "Not stated"],
      },
      { key: "preferredLanguage", apiKey: "preferred_language", label: "Preferred language" },
    ],
  },
  {
    title: "Contact",
    fields: [
      { key: "phone", apiKey: "phone", label: "Phone" },
      { key: "email", apiKey: "email", label: "Email" },
      { key: "emergencyContactName", apiKey: "emergency_contact_name", label: "Emergency contact name" },
      { key: "emergencyContactPhone", apiKey: "emergency_contact_phone", label: "Emergency contact phone" },
      {
        key: "preferredCommunication", apiKey: "preferred_communication", label: "Preferred communication",
        type: "select", options: ["Phone", "Email", "SMS", "Portal"],
      },
      {
        key: "bestTimeToContact", apiKey: "best_time_to_contact", label: "Best time to contact",
        type: "select", options: ["Morning", "Afternoon", "Evening"],
      },
    ],
  },
  {
    title: "History",
    fields: [
      { key: "knownConditions", apiKey: "known_conditions", label: "Known conditions", type: "textarea" },
      { key: "currentMedications", apiKey: "current_medications", label: "Current medications", type: "textarea" },
      { key: "allergies", apiKey: "allergies", label: "Allergies", type: "textarea" },
    ],
  },
  {
    title: "Insurance",
    fields: [
      { key: "insuranceProvider", apiKey: "insurance_provider", label: "Insurance provider" },
      { key: "policyNumber", apiKey: "policy_number", label: "Policy number" },
      { key: "groupNumber", apiKey: "group_number", label: "Group number", naOption: true },
      { key: "expiryDate", apiKey: "insurance_expiry", label: "Expiry date", type: "date" },
      { key: "medicareNumber", apiKey: "medicare_number", label: "Medicare number", naOption: true },
      {
        key: "concessionCard", apiKey: "concession_card", label: "Concession card", type: "select",
        options: ["None", "Health Care Card", "Pensioner Concession", "Commonwealth Seniors"],
      },
    ],
  },
];

export const PROFILE_FIELD_LABELS_BY_API_KEY: Record<string, string> = Object.fromEntries(
  PROFILE_FIELD_GROUPS.flatMap(g => g.fields.map(f => [f.apiKey, f.label])),
);

const inputClass = "w-full rounded-lg border border-slate-300 px-3.5 py-2.5 text-sm outline-none focus:border-brand focus:ring-1 focus:ring-brand";

export function ProfileFieldInput({
  def, value, onChange,
}: { def: ProfileFieldDef; value: string; onChange: (value: string) => void }) {
  const id = useId();
  return (
    <div>
      <label htmlFor={id} className="block text-sm font-medium text-slate-700 mb-1.5">{def.label}</label>
      <div className="flex gap-2">
        {def.type === "textarea" ? (
          <textarea id={id} className={`${inputClass} h-28 resize-none`} value={value} onChange={e => onChange(e.target.value)} />
        ) : def.type === "select" ? (
          <select id={id} className={inputClass} value={value} onChange={e => onChange(e.target.value)}>
            <option value="">Select...</option>
            {def.options?.map(o => <option key={o}>{o}</option>)}
          </select>
        ) : (
          <input
            id={id}
            className={inputClass}
            placeholder={def.type === "date" ? "DD/MM/YYYY" : undefined}
            value={value}
            onChange={e => onChange(e.target.value)}
          />
        )}
        {def.naOption && (
          <button
            type="button"
            onClick={() => onChange("N/A")}
            aria-label={`Mark ${def.label.toLowerCase()} as not applicable`}
            className="shrink-0 rounded-lg border border-slate-300 px-3 text-xs font-medium text-slate-600 hover:bg-slate-50"
          >
            N/A
          </button>
        )}
      </div>
    </div>
  );
}
