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

All 25 sponsor-approved designs are implemented across two shells:

**Main app**: Login, Forgot password, Dashboard, Patients list, Patient
onboarding, Patient detail, Case detail, Consent queue, Consent capture,
Consent success, Records & information retrieval, Inbox, Compose, Review
queue, Add case, Escalations, Audit log, Audit event detail, Users, and
Settings.

**Platform Operations**: a separate shell with its own login gate
(`/platform-ops/login`), System Health, and Model & Risk Configuration.
It shares the same auth session as the main app but renders its own sidebar
and layout (`PlatformOpsLayout` in `src/pages/PlatformOps.tsx`).

Audit and Users are gated to the `admin` role via `<ProtectedRoute roles={["admin"]}>`
and are hidden from the sidebar for other roles.

## Database-agnostic design (the adapter seam)

Components import domain types from `src/api/types.ts` only: never raw API
shapes. Each `src/api/*.ts` file is an adapter that maps today's backend to those
types, so changing the backend means changing adapter bodies, not components.

## Wired to real endpoints

- Auth: login (`/auth/login`, OAuth2 form flow), current user (`/auth/me`),
  user management (`/auth/users`, elevate/department/active/grants)
- Dashboard: count tiles and Pending Reviews list, aggregated from `/intake`,
  `/audit`, and `/human-review`
- Patients (`/patients`) and Cases/Intake (`/intake`)
- Consent (`/consent/*`)
- Records: clinical documents (`/clinical-documents`) and RAG query (`/rag/query`)
- Inbox actions: approve draft, escalate, archive (`/approvals`, `/tasks/*`)
- Review queue (`/human-review/*`): claim, complete, reject, escalate, create
- Tasks / Escalations board (`/tasks/*`) with comments
- Audit (`/audit/*`), including chain verification and CSV export

## Structure

```
src/
  lib/apiClient.ts   single HTTP transport (JWT, form-login, page envelope)
  lib/auth.tsx        session context
  api/types.ts        domain model: the stable contract
  api/*.ts             adapters: backend shapes -> domain types
                        (auth, cases, consent, records, misc, tasks,
                         reviewTasks, audit)
  components/          Sidebar, Layout, ProtectedRoute, shared UI (ui.tsx)
  pages/               one file per screen, plus PlatformOps.tsx which
                        exports the whole Platform Operations shell
                        (login, layout, System Health, Model Config)
```
