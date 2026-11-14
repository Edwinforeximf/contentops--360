-- Reference PostgreSQL schema; FastAPI SQLAlchemy creates Phase 1 tables on startup.
-- Use migration tooling before making schema changes in production.
CREATE TABLE IF NOT EXISTS users (id SERIAL PRIMARY KEY, email VARCHAR(255) UNIQUE NOT NULL, name VARCHAR(120) NOT NULL, password_hash TEXT NOT NULL, role VARCHAR(32) NOT NULL DEFAULT 'content', active BOOLEAN DEFAULT TRUE);
CREATE TABLE IF NOT EXISTS projects (id SERIAL PRIMARY KEY, title VARCHAR(200) NOT NULL, description TEXT DEFAULT '', created_by INTEGER REFERENCES users(id), created_at TIMESTAMPTZ DEFAULT NOW());
CREATE TABLE IF NOT EXISTS tasks (id SERIAL PRIMARY KEY, project_id INTEGER NOT NULL REFERENCES projects(id), title VARCHAR(200) NOT NULL, stage VARCHAR(32) DEFAULT 'content', status VARCHAR(32) DEFAULT 'todo', assignee_id INTEGER REFERENCES users(id), planned_start TIMESTAMPTZ, planned_end TIMESTAMPTZ, actual_start TIMESTAMPTZ, actual_end TIMESTAMPTZ, asset_url TEXT DEFAULT '', notes TEXT DEFAULT '', created_at TIMESTAMPTZ DEFAULT NOW());
CREATE TABLE IF NOT EXISTS time_entries (id SERIAL PRIMARY KEY, task_id INTEGER NOT NULL REFERENCES tasks(id), user_id INTEGER NOT NULL REFERENCES users(id), started_at TIMESTAMPTZ NOT NULL, stopped_at TIMESTAMPTZ);
CREATE TABLE IF NOT EXISTS reviews (id SERIAL PRIMARY KEY, task_id INTEGER NOT NULL REFERENCES tasks(id), reviewer_id INTEGER NOT NULL REFERENCES users(id), decision VARCHAR(20) NOT NULL, comment TEXT DEFAULT '', created_at TIMESTAMPTZ DEFAULT NOW());
CREATE TABLE IF NOT EXISTS task_events (id SERIAL PRIMARY KEY, task_id INTEGER NOT NULL REFERENCES tasks(id), actor_id INTEGER NOT NULL REFERENCES users(id), action VARCHAR(80), detail TEXT DEFAULT '', created_at TIMESTAMPTZ DEFAULT NOW());
CREATE INDEX IF NOT EXISTS idx_tasks_project ON tasks(project_id);
CREATE INDEX IF NOT EXISTS idx_tasks_assignee ON tasks(assignee_id);
CREATE INDEX IF NOT EXISTS idx_time_entries_task ON time_entries(task_id);
