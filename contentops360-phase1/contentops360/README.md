# ContentOps 360 — Phase 1 MVP

Multi-user content production task management with flexible schedules, daily operations, manual work timers, review approval, publishing, and basic production KPIs.

## Structure
- `backend/` FastAPI + SQLAlchemy + PostgreSQL (SQLite fallback for local development)
- `frontend/` Next.js + TypeScript responsive dashboard
- `database/schema.sql` PostgreSQL schema reference

## Railway deployment (3 services in one project)
1. Push this folder to a **private** GitHub repository.
2. Create a Railway project and add **PostgreSQL**.
3. Add backend service from GitHub repo, set **Root Directory** to `/backend`, choose Dockerfile deployment. Set:
   - `DATABASE_URL=${{Postgres.DATABASE_URL}}` (use Railway's variable reference UI; actual PostgreSQL service name may differ)
   - `JWT_SECRET` random 64+ characters (`openssl rand -hex 32`)
   - `CORS_ORIGINS=https://YOUR-FRONTEND.up.railway.app`
   Generate a public domain for the backend. Test `/health` and `/docs`.
4. Add frontend service from same repo, set **Root Directory** to `/frontend`, Dockerfile deployment. Add **build variable** `NEXT_PUBLIC_API_URL=https://YOUR-BACKEND.up.railway.app`. Railway must pass this as Docker build arg. The frontend Dockerfile defines `ARG NEXT_PUBLIC_API_URL`. If your Railway build system does not forward the variable as a build argument, configure it in service build settings or use a Docker build arg manually.
5. Generate public domain for frontend. Update backend `CORS_ORIGINS` to the exact frontend HTTPS origin; redeploy backend.
6. Open frontend → **Instalasi pertama? Buat admin**. Only the first setup can create an admin.
7. Admin adds users. Content/manager/admin create projects and tasks, assign PIC, and set planned times in WIB.

**Security:** Keep Railway variables secret; never commit `.env`. Enable private GitHub repo and database backups. The starter uses JWT in localStorage for simplicity; production hardening should migrate to secure HttpOnly cookies, rate limiting, CSRF safeguards, database migrations, and invite-only user provisioning. Public first-admin setup should be protected by a deployment-time bootstrap secret or private provisioning endpoint before production launch.

## Local development
Backend:
```
cd backend
python -m venv .venv
# activate venv
pip install -r requirements.txt
# copy .env.example to .env and set JWT_SECRET (DATABASE_URL may be sqlite:///./local.db)
uvicorn app.main:app --reload --port 8000
```
Frontend:
```
cd frontend
npm install
# copy .env.example to .env.local
npm run dev
```

## Phase 1 limitations / next steps
- The timeline is a dated table, not yet a drag-and-drop Gantt chart.
- Assets are links (e.g. Google Drive); no OAuth/upload integration yet.
- Task review is per task; production-to-publication dependency enforcement is not yet implemented.
- Time tracking is manual; `Pause` ends a work interval, `Resume` starts a new one. `Stop` submits for review.
- No separate button to submit a task without creating a time entry; the UI provides a start-and-stop fallback.
- `tracked_seconds` counts running intervals as of each API response; refresh to update.
- No editing of deadlines in the UI yet (PATCH API supports it).
- Organic/paid metrics, campaign data and granular per-role KPI are Phase 2/3, not yet implemented.
- Basic role-based access is provided, but project-level tenant isolation and granular permissions are not implemented.
- Production use requires Alembic migrations, automated tests, request validation, audit logging enhancements, and deployment hardening.
