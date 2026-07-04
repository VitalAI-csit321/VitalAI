import React, { useState } from "react";

export const C = {
  bg: "#161B27", sidebar: "#1A2035", surface: "#FFFFFF",
  surfaceDim: "#F5F6FA", border: "#E4E7EE",
  teal: "#2BA99B", tealDark: "#228C80", tealLight: "#EAF6F4",
  text: "#0F1624", textMid: "#4A5568", textMuted: "#9BA5B7",
  red: "#E53E3E", redLight: "#FFF5F5",
  amber: "#D97706", amberLight: "#FFFBEB",
  green: "#38A169", greenLight: "#F0FFF4",
} as const;

type BadgeColor = "teal" | "red" | "amber" | "green" | "gray";
const BADGE: Record<BadgeColor, { bg: string; color: string }> = {
  teal:  { bg: C.tealLight,  color: C.teal  },
  red:   { bg: C.redLight,   color: C.red   },
  amber: { bg: C.amberLight, color: C.amber },
  green: { bg: C.greenLight, color: C.green },
  gray:  { bg: "#F1F3F7",    color: C.textMid },
};

export function Badge({ color = "teal", children }: { color?: BadgeColor; children: React.ReactNode }) {
  const s = BADGE[color];
  return <span style={{ background: s.bg, color: s.color, fontSize: 11, fontWeight: 700, padding: "2px 8px", borderRadius: 4, textTransform: "uppercase", letterSpacing: "0.04em" }}>{children}</span>;
}

export function Btn({ children, variant = "primary", onClick, style = {}, size = "md", disabled = false, type = "button" }: {
  children: React.ReactNode; variant?: "primary" | "outline" | "danger" | "ghost";
  onClick?: () => void; style?: React.CSSProperties; size?: "sm" | "md";
  disabled?: boolean; type?: "button" | "submit";
}) {
  const [hov, setHov] = useState(false);
  const pad = size === "sm" ? "5px 12px" : "9px 20px";
  const base: React.CSSProperties = {
    primary: { background: disabled ? C.textMuted : hov ? C.tealDark : C.teal, color: "#fff", border: "none" },
    outline: { background: "#fff", color: C.textMid, border: `1px solid ${C.border}` },
    danger:  { background: hov ? "#C53030" : C.red, color: "#fff", border: "none" },
    ghost:   { background: "transparent", color: C.teal, border: "none" },
  }[variant];
  return (
    <button type={type} onClick={disabled ? undefined : onClick} disabled={disabled}
      onMouseEnter={() => setHov(true)} onMouseLeave={() => setHov(false)}
      style={{ ...base, borderRadius: 6, fontWeight: 600, fontSize: 13, padding: pad, cursor: disabled ? "not-allowed" : "pointer", transition: "background .15s", ...style }}>
      {children}
    </button>
  );
}

export function Input({ label, value, onChange, placeholder, type = "text", readOnly, required, error }: {
  label?: string; value?: string; onChange?: (v: string) => void;
  placeholder?: string; type?: string; readOnly?: boolean; required?: boolean; error?: string;
}) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
      {label && <label style={{ fontSize: 12, fontWeight: 500, color: C.textMid }}>{label}{required && <span style={{ color: C.red }}> *</span>}</label>}
      <input type={type} value={value} onChange={onChange ? e => onChange(e.target.value) : undefined}
        placeholder={placeholder} readOnly={readOnly} required={required}
        style={{ border: `1px solid ${error ? C.red : C.border}`, borderRadius: 6, padding: "8px 12px", fontSize: 13, color: C.text, outline: "none", background: readOnly ? C.surfaceDim : "#fff", width: "100%", boxSizing: "border-box" }} />
      {error && <span style={{ fontSize: 11, color: C.red }}>{error}</span>}
    </div>
  );
}

export function Textarea({ label, value, onChange, placeholder, rows = 3 }: {
  label?: string; value?: string; onChange?: (v: string) => void; placeholder?: string; rows?: number;
}) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
      {label && <label style={{ fontSize: 12, fontWeight: 500, color: C.textMid }}>{label}</label>}
      <textarea value={value} onChange={onChange ? e => onChange(e.target.value) : undefined}
        placeholder={placeholder} rows={rows}
        style={{ border: `1px solid ${C.border}`, borderRadius: 6, padding: "8px 12px", fontSize: 13, color: C.text, outline: "none", resize: "vertical", fontFamily: "inherit", width: "100%", boxSizing: "border-box" }} />
    </div>
  );
}

export function Select({ label, value, onChange, options, placeholder }: {
  label?: string; value: string; onChange: (v: string) => void;
  options: { label: string; value: string }[]; placeholder?: string;
}) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
      {label && <label style={{ fontSize: 12, fontWeight: 500, color: C.textMid }}>{label}</label>}
      <select value={value} onChange={e => onChange(e.target.value)}
        style={{ border: `1px solid ${C.border}`, borderRadius: 6, padding: "8px 12px", fontSize: 13, color: C.text, background: "#fff", outline: "none", width: "100%" }}>
        {placeholder && <option value="">{placeholder}</option>}
        {options.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
      </select>
    </div>
  );
}

export function Card({ children, style = {} }: { children: React.ReactNode; style?: React.CSSProperties }) {
  return <div style={{ background: C.surface, border: `1px solid ${C.border}`, borderRadius: 10, padding: 20, ...style }}>{children}</div>;
}

export function Alert({ type = "info", title, message }: { type?: "info" | "warning" | "error" | "success"; title?: string; message: string }) {
  const m = { info: { bg: C.tealLight, color: C.teal, icon: "ℹ" }, warning: { bg: C.amberLight, color: C.amber, icon: "⚠" }, error: { bg: C.redLight, color: C.red, icon: "✕" }, success: { bg: C.greenLight, color: C.green, icon: "✓" } }[type];
  return (
    <div style={{ background: m.bg, border: `1px solid ${m.color}30`, borderRadius: 8, padding: 12, display: "flex", gap: 10 }}>
      <span style={{ color: m.color, flexShrink: 0 }}>{m.icon}</span>
      <div>{title && <div style={{ fontSize: 13, fontWeight: 600, color: m.color, marginBottom: 2 }}>{title}</div>}<div style={{ fontSize: 12, color: m.color }}>{message}</div></div>
    </div>
  );
}

export function Spinner({ size = 20 }: { size?: number }) {
  return <div style={{ width: size, height: size, borderRadius: "50%", border: `2px solid ${C.border}`, borderTopColor: C.teal, animation: "spin 0.7s linear infinite" }} />;
}

export function Topbar({ children }: { children?: React.ReactNode }) {
  return (
    <div style={{ height: 52, background: "#fff", borderBottom: `1px solid ${C.border}`, display: "flex", alignItems: "center", justifyContent: "space-between", padding: "0 24px", position: "sticky", top: 0, zIndex: 40 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8, background: C.surfaceDim, border: `1px solid ${C.border}`, borderRadius: 7, padding: "6px 12px", width: 260 }}>
        <span style={{ color: C.textMuted, fontSize: 13 }}>🔍</span>
        <input placeholder="Search…" style={{ border: "none", background: "transparent", fontSize: 13, outline: "none", width: "100%" }} />
      </div>
      <div style={{ display: "flex", alignItems: "center", gap: 12 }}>{children}</div>
    </div>
  );
}

// inject spinner keyframe once
const s = document.createElement("style");
s.textContent = "@keyframes spin { to { transform: rotate(360deg); } }";
document.head.appendChild(s);
