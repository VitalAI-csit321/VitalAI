import { useState } from "react";
import { useNavigate, useLocation } from "react-router-dom";
import { useMutation } from "@tanstack/react-query";
import { login, getMe } from "../api/auth";
import { useAuthStore } from "../store/authStore";
import { Btn, Input, Alert, C } from "../components/ui";
import type { RegisterRequest } from "../types";
import { ROLES } from "../types";
import { register } from "../api/auth";

function AuthCard({ children }: { children: React.ReactNode }) {
  return (
    <div style={{ minHeight: "100vh", background: C.bg, display: "flex", alignItems: "center", justifyContent: "center" }}>
      <div style={{ background: "#fff", borderRadius: 12, padding: 36, width: 380, boxShadow: "0 20px 60px rgba(0,0,0,0.3)" }}>
        <div style={{ fontSize: 22, fontWeight: 800, color: C.text, textAlign: "center", marginBottom: 6 }}>VitalAI</div>
        {children}
      </div>
    </div>
  );
}

function ForgotPassword({ onBack }: { onBack: () => void }) {
  const [email, setEmail] = useState("");
  const [sent, setSent] = useState(false);
  return (
    <AuthCard>
      <button onClick={onBack} style={{ background: "none", border: "none", color: C.textMid, fontSize: 13, cursor: "pointer", marginBottom: 16, padding: 0 }}>← Back</button>
      <h2 style={{ fontSize: 17, fontWeight: 700, color: C.text, marginBottom: 8 }}>Reset your password</h2>
      <p style={{ fontSize: 13, color: C.textMid, marginBottom: 20 }}>Enter your email and we'll send a reset link.</p>
      {sent
        ? <Alert type="success" message={`Reset link sent to ${email}`} />
        : <>
            <div style={{ marginBottom: 16 }}><Input label="Email address" value={email} onChange={setEmail} type="email" placeholder="you@hospital.health" /></div>
            <Btn style={{ width: "100%" }} onClick={() => setSent(true)} disabled={!email}>Send reset link</Btn>
          </>
      }
      <div style={{ textAlign: "center", marginTop: 16 }}>
        <button onClick={onBack} style={{ color: C.teal, fontSize: 13, cursor: "pointer", background: "none", border: "none" }}>Back to sign in</button>
      </div>
    </AuthCard>
  );
}

function RegisterForm({ onBack }: { onBack: () => void }) {
  const navigate = useNavigate();
  const { setAuth } = useAuthStore();
  const [form, setForm] = useState<RegisterRequest>({ email: "", password: "", full_name: "" });
  const [confirm, setConfirm] = useState("");
  const [pwErr, setPwErr] = useState("");
  const set = (f: keyof RegisterRequest) => (v: string) => setForm(p => ({ ...p, [f]: v }));

  const mutation = useMutation({
    mutationFn: async () => {
      await register(form);
      const tokenRes = await login({ email: form.email, password: form.password });
      useAuthStore.getState().setAuth(tokenRes.access_token, {
        id: "", email: form.email, full_name: form.full_name,
        role: ROLES.FRONT_DESK, is_active: true, created_at: ""
      });
      const user = await getMe();
      return { token: tokenRes.access_token, user };
    },
    onSuccess: ({ token, user }) => {
      setAuth(token, user);
      navigate("/dashboard", { replace: true });
    },
  });

  function submit() {
    if (form.password !== confirm) { setPwErr("Passwords do not match"); return; }
    if (form.password.length < 8) { setPwErr("Minimum 8 characters"); return; }
    setPwErr("");
    mutation.mutate();
  }

  return (
    <AuthCard>
      <button onClick={onBack} style={{ background: "none", border: "none", color: C.textMid, fontSize: 13, cursor: "pointer", marginBottom: 16, padding: 0 }}>← Back to sign in</button>
      <h2 style={{ fontSize: 17, fontWeight: 700, color: C.text, textAlign: "center", marginBottom: 20 }}>Create account</h2>
      {mutation.isError && <div style={{ marginBottom: 14 }}><Alert type="error" message="Registration failed. Email may already be in use." /></div>}
      <div style={{ display: "flex", flexDirection: "column", gap: 14, marginBottom: 20 }}>
        <Input label="Full name" value={form.full_name} onChange={set("full_name")} placeholder="Jane Smith" required />
        <Input label="Email address" value={form.email} onChange={set("email")} type="email" placeholder="you@hospital.health" required />
        <Input label="Password" value={form.password} onChange={set("password")} type="password" required />
        <Input label="Confirm password" value={confirm} onChange={setConfirm} type="password" required error={pwErr} />
      </div>
      <p style={{ fontSize: 11, color: C.textMuted, marginBottom: 14 }}>Your account starts with Front Desk access. An admin can elevate your role.</p>
      <Btn style={{ width: "100%" }} onClick={submit} disabled={mutation.isPending || !form.full_name || !form.email || !form.password || !confirm}>
        {mutation.isPending ? "Creating…" : "Create account"}
      </Btn>
    </AuthCard>
  );
}

export function LoginPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const { setAuth } = useAuthStore();
  const from = (location.state as { from?: { pathname: string } })?.from?.pathname ?? "/dashboard";

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [view, setView] = useState<"login" | "register" | "forgot">("login");

  const mutation = useMutation({
    mutationFn: async () => {
      // Step 1: get token
      const tokenRes = await login({ email, password });
      const token = tokenRes.access_token;

      // Step 2: store token immediately so getMe() request is authenticated
      useAuthStore.getState().setAuth(token, {
        id: "", email, full_name: "",
        role: ROLES.FRONT_DESK, is_active: true, created_at: ""
      });

      // Step 3: fetch real user object
      const user = await getMe();
      return { token, user };
    },
    onSuccess: ({ token, user }) => {
      setAuth(token, user);
      navigate(from, { replace: true });
    },
    onError: () => {
      // Clear the temporary auth if getMe fails
      useAuthStore.getState().clearAuth();
    },
  });

  if (view === "forgot") return <ForgotPassword onBack={() => setView("login")} />;
  if (view === "register") return <RegisterForm onBack={() => setView("login")} />;

  return (
    <AuthCard>
      <h2 style={{ fontSize: 17, fontWeight: 600, color: C.text, textAlign: "center", marginBottom: 24 }}>Welcome back</h2>
      {mutation.isError && (
        <div style={{ marginBottom: 16 }}>
          <Alert type="error" message="Invalid email or password." />
        </div>
      )}
      <div style={{ display: "flex", flexDirection: "column", gap: 14, marginBottom: 16 }}>
        <Input label="Email address" value={email} onChange={setEmail} type="email" required />
        <Input label="Password" value={password} onChange={setPassword} type="password" required />
      </div>
      <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 16 }}>
        <label style={{ display: "flex", gap: 6, fontSize: 13, color: C.textMid, cursor: "pointer" }}>
          <input type="checkbox" style={{ accentColor: C.teal }} /> Remember me
        </label>
        <button onClick={() => setView("forgot")} style={{ color: C.teal, fontSize: 13, cursor: "pointer", background: "none", border: "none" }}>
          Forgot password?
        </button>
      </div>
      <Btn
        style={{ width: "100%" }}
        onClick={() => mutation.mutate()}
        disabled={mutation.isPending || !email || !password}
      >
        {mutation.isPending ? "Signing in…" : "Sign in"}
      </Btn>
      <div style={{ display: "flex", alignItems: "center", gap: 10, margin: "16px 0" }}>
        <div style={{ flex: 1, height: 1, background: C.border }} />
        <span style={{ fontSize: 12, color: C.textMuted }}>OR</span>
        <div style={{ flex: 1, height: 1, background: C.border }} />
      </div>
      <button disabled style={{ width: "100%", padding: "9px 0", border: `1px solid ${C.border}`, borderRadius: 6, background: C.surfaceDim, color: C.textMuted, fontSize: 13, cursor: "not-allowed" }}>
        Sign in with SSO
      </button>
      <p style={{ textAlign: "center", marginTop: 12, fontSize: 11, color: C.textMuted }}>MVP Build • Limited SSO Support</p>
      <div style={{ textAlign: "center", marginTop: 20, fontSize: 13, color: C.textMid }}>
        Don't have an account?{" "}
        <button onClick={() => setView("register")} style={{ color: C.teal, fontWeight: 600, cursor: "pointer", background: "none", border: "none", fontSize: 13 }}>
          Create one
        </button>
      </div>
    </AuthCard>
  );
}
