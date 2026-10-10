# VitalAI Frontend

React + Vite + React Router + Tailwind SPA for the VitalAI system.

## Running

```bash
cp .env.example .env      # VITE_API_BASE_URL=http://localhost:8000
npm install
npm run dev               # http://localhost:5173
```

`npm run build` type-checks (TypeScript strict) and emits a production bundle to
`dist/`. The backend must allow the frontend origin via its `CORS_ORIGINS` env
(preconfigured for `http://localhost:5173`).

## Screens

All routes are defined in `src/App.tsx`. The app is built for desktop screens.

**Without signing in**: Login, Forgot password, Reset password, and the patient
registration form a patient opens from an emailed link (`/register/<token>`).

**Signed in**: Dashboard, Patients (list, onboarding, detail, edit), Case, Contact,
Consent (queue, new, capture, view, success), Records & information retrieval,
Inbox, Review queue, Add case, Escalations, Calendar and appointments (new,
detail, edit), and Settings. Settings includes the clinic mailbox sign-in, a
manual import, and an Operations section with the health of the database, object
storage, LLM provider and mailbox.

**Restricted**: Users is admin only (`<ProtectedRoute roles={["admin"]}>`). Audit
log and Audit event detail need the `read_audit` permission
(`<ProtectedRoute permission="read_audit">`). Escalations is not available to
doctors. `components/Sidebar.tsx` hides whatever the signed-in user cannot open.

## Database-agnostic design (the adapter seam)

Components import domain types from `src/api/types.ts` only: never raw API
shapes. Each `src/api/*.ts` file is an adapter that maps today's backend to those
types, so changing the backend means changing adapter bodies, not components.

## Wired to real endpoints

- Auth: login (`/auth/login`, OAuth2 form flow), current user (`/auth/me`),
  password change and reset, user management (`/auth/users`,
  elevate/department/active/grants; inviting a user calls `/auth/register` with
  the admin's token)
- Dashboard: count tiles and Pending Reviews list, aggregated from `/intake`,
  `/audit`, and `/human-review`
- Patients (`/patients`), Cases (`/cases`) and Intake (`/intake`)
- Patient registration form (`/public/registration/{token}`), no sign-in
- Consent (`/consent/*`)
- Records: clinical documents (`/clinical-documents`) and RAG query (`/rag/query`)
- Inbox: approve or reject a draft, write a reply, escalate, archive
  (`/inbox/*`, `/approvals`, `/tasks/*`)
- Review queue (`/human-review/*`): claim, complete, reject, escalate, reroute,
  reassign, link patient, create
- Tasks / Escalations board (`/tasks/*`) with comments
- Calendar (`/appointments/*`, `/doctors`)
- Voicemail audio playback (`/calls/{id}/audio`)
- Audit (`/audit/*`), including chain verification and CSV export
- Settings (`/settings`), the clinic mailbox (`/integrations/outlook/*`) and
  system health (`/health/detailed`)

## Structure

```
src/
  lib/apiClient.ts   single HTTP transport (JWT, form-login, page envelope)
  lib/auth.tsx        session context
  lib/roles.ts        role labels and permission checks
  api/types.ts        domain model: the stable contract
  api/*.ts             adapters: backend shapes -> domain types
                        (auth, cases, episodes, consent, records, tasks,
                         reviewTasks, appointments, doctors, calls,
                         registration, settings, integrations, platformOps,
                         audit, misc)
  components/          Sidebar, Layout, ProtectedRoute, shared UI (ui.tsx)
  pages/               one file per screen
  pages/settings/      the sections of the Settings page
```
