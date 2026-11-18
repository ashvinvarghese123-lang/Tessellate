-- Tessellate schema (PostgreSQL 14+)
-- Principle: departments own timetables; faculty, rooms and time slots are GLOBAL.
CREATE EXTENSION IF NOT EXISTS btree_gist;

CREATE TABLE college (
  id SERIAL PRIMARY KEY, name TEXT NOT NULL, website_url TEXT,
  days SMALLINT NOT NULL DEFAULT 5, periods SMALLINT NOT NULL DEFAULT 6);

CREATE TABLE department (
  id SERIAL PRIMARY KEY,
  code TEXT UNIQUE NOT NULL,                 -- 'DEPT-CS'
  name TEXT NOT NULL);

CREATE TABLE academic_year (id SERIAL PRIMARY KEY, label TEXT UNIQUE NOT NULL);   -- '2026-27'

-- Working periods only. Breaks and lunch are simply not rows here, so they can never be assigned.
CREATE TABLE time_slot (
  id SERIAL PRIMARY KEY,
  day SMALLINT NOT NULL CHECK (day BETWEEN 0 AND 6),
  period SMALLINT NOT NULL,
  starts TIME NOT NULL, ends TIME NOT NULL,
  UNIQUE (day, period));

-- One department = one secure account = one workspace. There are NO roles and NO priority column.
CREATE TABLE department_account (
  id SERIAL PRIMARY KEY,
  department_id INT UNIQUE NOT NULL REFERENCES department(id),
  username TEXT UNIQUE NOT NULL,
  email TEXT NOT NULL,                        -- registered official address; the only place codes are sent
  password_hash TEXT NOT NULL,                -- scrypt, never plain text
  failed_logins SMALLINT NOT NULL DEFAULT 0,
  locked_until TIMESTAMPTZ,
  password_changed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  active BOOLEAN NOT NULL DEFAULT TRUE);

CREATE TABLE auth_session (
  token_hash TEXT PRIMARY KEY,                -- SHA-256 of the cookie value
  account_id INT NOT NULL REFERENCES department_account(id) ON DELETE CASCADE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  last_seen TIMESTAMPTZ NOT NULL DEFAULT now(),
  expires_at TIMESTAMPTZ NOT NULL,
  revoked BOOLEAN NOT NULL DEFAULT FALSE);

CREATE TABLE password_reset (
  token_hash TEXT PRIMARY KEY,
  account_id INT NOT NULL REFERENCES department_account(id) ON DELETE CASCADE,
  expires_at TIMESTAMPTZ NOT NULL, used BOOLEAN NOT NULL DEFAULT FALSE);

CREATE TABLE login_audit (
  id BIGSERIAL PRIMARY KEY, at TIMESTAMPTZ NOT NULL DEFAULT now(),
  account_id INT REFERENCES department_account(id), department_id INT REFERENCES department(id),
  event TEXT NOT NULL);                       -- login_ok, bad_password, bad_code, logout, password_changed ...

-- ONE row per person. FAC-001 is the same teacher in every department.
CREATE TABLE faculty (
  id SERIAL PRIMARY KEY,
  faculty_code TEXT UNIQUE NOT NULL,         -- 'FAC-001'
  name TEXT NOT NULL,
  home_department_id INT REFERENCES department(id),
  designation TEXT, email TEXT, profile_url TEXT,
  max_weekly_sessions SMALLINT NOT NULL DEFAULT 18,
  active BOOLEAN NOT NULL DEFAULT TRUE);

CREATE TABLE faculty_availability (          -- periods a teacher can NOT teach (or prefers not to)
  faculty_id INT REFERENCES faculty(id) ON DELETE CASCADE,
  time_slot_id INT REFERENCES time_slot(id),
  kind TEXT NOT NULL DEFAULT 'unavailable' CHECK (kind IN ('unavailable','avoid')),
  PRIMARY KEY (faculty_id, time_slot_id));

CREATE TABLE room (
  id SERIAL PRIMARY KEY, name TEXT UNIQUE NOT NULL, capacity SMALLINT,
  room_type TEXT NOT NULL CHECK (room_type IN ('Classroom','Computer lab','Laboratory')),
  home_department_id INT REFERENCES department(id));

CREATE TABLE room_availability (
  room_id INT REFERENCES room(id) ON DELETE CASCADE,
  time_slot_id INT REFERENCES time_slot(id), PRIMARY KEY (room_id, time_slot_id));

-- Department-owned data -----------------------------------------------------
CREATE TABLE class (
  id SERIAL PRIMARY KEY,
  department_id INT NOT NULL REFERENCES department(id),
  academic_year_id INT NOT NULL REFERENCES academic_year(id),
  semester SMALLINT NOT NULL, section TEXT NOT NULL, name TEXT NOT NULL,
  students SMALLINT, home_room_id INT REFERENCES room(id),
  UNIQUE (department_id, academic_year_id, semester, section));

CREATE TABLE subject (
  id SERIAL PRIMARY KEY, code TEXT, name TEXT NOT NULL,
  department_id INT NOT NULL REFERENCES department(id),
  kind TEXT NOT NULL DEFAULT 'Lecture' CHECK (kind IN ('Lecture','Lab')),
  required_room_type TEXT NOT NULL DEFAULT 'Classroom');

-- "Teacher X teaches subject Y to class Z, N sessions a week". Teachers may sit in any department.
CREATE TABLE teacher_allocation (
  id SERIAL PRIMARY KEY,
  class_id INT NOT NULL REFERENCES class(id) ON DELETE CASCADE,
  subject_id INT NOT NULL REFERENCES subject(id),
  faculty_id INT NOT NULL REFERENCES faculty(id),
  sessions_per_week SMALLINT NOT NULL CHECK (sessions_per_week BETWEEN 1 AND 30),
  UNIQUE (class_id, subject_id));

CREATE TABLE timetable (                       -- one per class per run of publishing
  id SERIAL PRIMARY KEY,
  class_id INT NOT NULL UNIQUE REFERENCES class(id),
  department_id INT NOT NULL REFERENCES department(id),
  status TEXT NOT NULL DEFAULT 'draft'
    CHECK (status IN ('draft','under_review','approved','published','frozen')),
  quality SMALLINT, updated_at TIMESTAMPTZ NOT NULL DEFAULT now());

CREATE TABLE timetable_entry (
  id BIGSERIAL PRIMARY KEY,
  timetable_id INT NOT NULL REFERENCES timetable(id) ON DELETE CASCADE,
  allocation_id INT NOT NULL REFERENCES teacher_allocation(id) ON DELETE CASCADE,
  class_id INT NOT NULL REFERENCES class(id),
  faculty_id INT NOT NULL REFERENCES faculty(id),
  room_id INT NOT NULL REFERENCES room(id),
  time_slot_id INT NOT NULL REFERENCES time_slot(id),
  locked BOOLEAN NOT NULL DEFAULT FALSE,
  -- The database itself refuses double-booking, whatever the app does (hard constraints):
  UNIQUE (faculty_id, time_slot_id),
  UNIQUE (room_id,    time_slot_id),
  UNIQUE (class_id,   time_slot_id));
CREATE INDEX ON timetable_entry (timetable_id);

-- Short-lived reservations so two coordinators cannot grab the same teacher at once.
CREATE TABLE resource_lock (
  faculty_id INT REFERENCES faculty(id), room_id INT REFERENCES room(id),
  time_slot_id INT NOT NULL REFERENCES time_slot(id),
  held_by INT NOT NULL REFERENCES department_account(id),
  expires_at TIMESTAMPTZ NOT NULL,
  CHECK ((faculty_id IS NULL) <> (room_id IS NULL)));
CREATE UNIQUE INDEX ON resource_lock (faculty_id, time_slot_id) WHERE faculty_id IS NOT NULL;
CREATE UNIQUE INDEX ON resource_lock (room_id,    time_slot_id) WHERE room_id    IS NOT NULL;

CREATE TABLE generation_run (
  id SERIAL PRIMARY KEY, department_id INT REFERENCES department(id), scope TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('ok','impossible','error')),
  quality SMALLINT, problems JSONB, started_by INT REFERENCES department_account(id),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now());

CREATE TABLE faculty_sync (                    -- every website sync is reviewed before saving
  id SERIAL PRIMARY KEY, source_url TEXT NOT NULL, fetched_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  payload JSONB NOT NULL, changes JSONB NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','approved','rejected')),
  approved_by INT REFERENCES department_account(id));   -- any department may review a sync

CREATE TABLE change_request (
  id SERIAL PRIMARY KEY, timetable_id INT NOT NULL REFERENCES timetable(id),
  requested_by INT NOT NULL REFERENCES department_account(id), reason TEXT,
  entry_id BIGINT, new_day SMALLINT, new_period SMALLINT,
  status TEXT NOT NULL DEFAULT 'applied' CHECK (status IN ('applied','blocked')),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now());

CREATE TABLE notification (
  id SERIAL PRIMARY KEY, department_id INT NOT NULL REFERENCES department(id),
  message TEXT NOT NULL, read BOOLEAN NOT NULL DEFAULT FALSE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now());

CREATE TABLE audit_log (
  id BIGSERIAL PRIMARY KEY, at TIMESTAMPTZ NOT NULL DEFAULT now(),
  department_id INT REFERENCES department(id),
  action TEXT NOT NULL, entry_id BIGINT, old_value JSONB, new_value JSONB, reason TEXT);

-- Departments see "busy" for other departments' sessions without seeing their timetable:
CREATE VIEW faculty_busy AS
SELECT e.faculty_id, ts.day, ts.period, ts.starts, ts.ends,
       d.name AS department, c.name AS class_name, s.name AS subject
FROM timetable_entry e
JOIN time_slot ts ON ts.id = e.time_slot_id
JOIN class c ON c.id = e.class_id
JOIN department d ON d.id = c.department_id
JOIN teacher_allocation a ON a.id = e.allocation_id
JOIN subject s ON s.id = a.subject_id;
-- Self-service department sign-up
CREATE UNIQUE INDEX IF NOT EXISTS department_account_email_key ON department_account (lower(email));
-- College Registry: a separate, data-only account type (no timetable powers, no department priority)
CREATE TABLE IF NOT EXISTS registry_account (
  id SERIAL PRIMARY KEY, username TEXT UNIQUE NOT NULL, email TEXT NOT NULL, password_hash TEXT NOT NULL,
  failed_logins SMALLINT NOT NULL DEFAULT 0, locked_until TIMESTAMPTZ,
  password_changed_at TIMESTAMPTZ NOT NULL DEFAULT now(), active BOOLEAN NOT NULL DEFAULT TRUE);
CREATE TABLE IF NOT EXISTS registry_session (
  token_hash TEXT PRIMARY KEY, account_id INT NOT NULL REFERENCES registry_account(id) ON DELETE CASCADE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(), last_seen TIMESTAMPTZ NOT NULL DEFAULT now(),
  expires_at TIMESTAMPTZ NOT NULL, revoked BOOLEAN NOT NULL DEFAULT FALSE);
CREATE TABLE IF NOT EXISTS registry_reset (
  token_hash TEXT PRIMARY KEY, account_id INT NOT NULL REFERENCES registry_account(id) ON DELETE CASCADE,
  expires_at TIMESTAMPTZ NOT NULL, used BOOLEAN NOT NULL DEFAULT FALSE);
-- Departments choose their own period times and timetable rules.
-- Sessions now carry their own day and time range, and the DATABASE refuses any overlap of a teacher,
-- room or class, even when two departments use different period times.
CREATE EXTENSION IF NOT EXISTS btree_gist;

CREATE TABLE IF NOT EXISTS department_settings (
  department_id INT PRIMARY KEY REFERENCES department(id) ON DELETE CASCADE,
  config JSONB NOT NULL,                       -- days, periods (start/end), rules, periods kept free
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now());

ALTER TABLE timetable_entry ADD COLUMN IF NOT EXISTS day SMALLINT;
ALTER TABLE timetable_entry ADD COLUMN IF NOT EXISTS period SMALLINT;       -- position inside the department's own period list
ALTER TABLE timetable_entry ADD COLUMN IF NOT EXISTS start_min SMALLINT;    -- minutes after midnight
ALTER TABLE timetable_entry ADD COLUMN IF NOT EXISTS end_min SMALLINT;

UPDATE timetable_entry e SET day = ts.day, period = ts.period,
  start_min = (EXTRACT(HOUR FROM ts.starts) * 60 + EXTRACT(MINUTE FROM ts.starts))::smallint,
  end_min = (EXTRACT(HOUR FROM ts.ends) * 60 + EXTRACT(MINUTE FROM ts.ends))::smallint
FROM time_slot ts WHERE ts.id = e.time_slot_id AND e.day IS NULL;

ALTER TABLE timetable_entry ALTER COLUMN day SET NOT NULL;
ALTER TABLE timetable_entry ALTER COLUMN period SET NOT NULL;
ALTER TABLE timetable_entry ALTER COLUMN start_min SET NOT NULL;
ALTER TABLE timetable_entry ALTER COLUMN end_min SET NOT NULL;
ALTER TABLE timetable_entry ALTER COLUMN time_slot_id DROP NOT NULL;        -- legacy column, no longer used for new sessions
ALTER TABLE timetable_entry ADD CONSTRAINT te_valid_time CHECK (end_min > start_min);

ALTER TABLE timetable_entry DROP CONSTRAINT IF EXISTS timetable_entry_faculty_id_time_slot_id_key;
ALTER TABLE timetable_entry DROP CONSTRAINT IF EXISTS timetable_entry_room_id_time_slot_id_key;
ALTER TABLE timetable_entry DROP CONSTRAINT IF EXISTS timetable_entry_class_id_time_slot_id_key;

ALTER TABLE timetable_entry ADD COLUMN IF NOT EXISTS span int4range GENERATED ALWAYS AS (int4range(start_min::int, end_min::int)) STORED;
ALTER TABLE timetable_entry ADD CONSTRAINT te_no_teacher_overlap EXCLUDE USING gist (faculty_id WITH =, day WITH =, span WITH &&);
ALTER TABLE timetable_entry ADD CONSTRAINT te_no_room_overlap    EXCLUDE USING gist (room_id    WITH =, day WITH =, span WITH &&);
ALTER TABLE timetable_entry ADD CONSTRAINT te_no_class_overlap   EXCLUDE USING gist (class_id   WITH =, day WITH =, span WITH &&);

DROP VIEW IF EXISTS faculty_busy;
CREATE VIEW faculty_busy AS
SELECT e.faculty_id, e.day, e.period, e.start_min, e.end_min, d.name AS department, c.name AS class_name, s.name AS subject
FROM timetable_entry e JOIN class c ON c.id = e.class_id JOIN department d ON d.id = c.department_id
JOIN teacher_allocation a ON a.id = e.allocation_id JOIN subject s ON s.id = a.subject_id;
-- Rooms are optional for now: a timetable session may have no room. Room data is kept for later.
ALTER TABLE timetable_entry ALTER COLUMN room_id DROP NOT NULL;

-- 006: Cross-Department MDC, Minor & Student Enrollment Integration
CREATE TABLE IF NOT EXISTS institutional_category (
  id SERIAL PRIMARY KEY,
  name TEXT UNIQUE NOT NULL CHECK (name IN ('Aided', 'Self-Financing'))
);
INSERT INTO institutional_category (name) VALUES ('Aided'), ('Self-Financing')
ON CONFLICT (name) DO NOTHING;

ALTER TABLE department ADD COLUMN IF NOT EXISTS category_id INT REFERENCES institutional_category(id);

CREATE TABLE IF NOT EXISTS student (
  id SERIAL PRIMARY KEY,
  register_number TEXT UNIQUE NOT NULL,
  name TEXT NOT NULL,
  home_department_id INT NOT NULL REFERENCES department(id) ON DELETE RESTRICT,
  academic_year_id INT REFERENCES academic_year(id),
  semester SMALLINT NOT NULL DEFAULT 1,
  class_id INT REFERENCES class(id) ON DELETE SET NULL,
  status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'inactive', 'graduated')),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_student_home_dept ON student(home_department_id);
CREATE INDEX IF NOT EXISTS idx_student_class ON student(class_id);

CREATE TABLE IF NOT EXISTS course (
  id SERIAL PRIMARY KEY,
  course_code TEXT UNIQUE NOT NULL,
  course_name TEXT NOT NULL,
  course_type TEXT NOT NULL CHECK (course_type IN ('Regular', 'MDC', 'Minor', 'REGULAR', 'MINOR')),
  selection_type TEXT CHECK (selection_type IN ('STUDENT_SELECTED', 'DEPARTMENT_SELECTED')),
  department_id INT NOT NULL REFERENCES department(id) ON DELETE CASCADE,
  description TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_course_dept ON course(department_id);

CREATE TABLE IF NOT EXISTS course_offering (
  id SERIAL PRIMARY KEY,
  offering_code TEXT UNIQUE NOT NULL,
  course_id INT NOT NULL REFERENCES course(id) ON DELETE CASCADE,
  offering_department_id INT NOT NULL REFERENCES department(id) ON DELETE CASCADE,
  academic_year_id INT REFERENCES academic_year(id),
  semester SMALLINT NOT NULL DEFAULT 1,
  scheduling_scope TEXT NOT NULL CHECK (scheduling_scope IN ('college_wide', 'department_specific')),
  selection_type TEXT CHECK (selection_type IN ('STUDENT_SELECTED', 'DEPARTMENT_SELECTED')),
  required_sessions SMALLINT NOT NULL DEFAULT 3 CHECK (required_sessions BETWEEN 1 AND 20),
  session_duration SMALLINT NOT NULL DEFAULT 60,
  max_enrollment SMALLINT NOT NULL DEFAULT 60 CHECK (max_enrollment >= 1),
  faculty_id INT REFERENCES faculty(id) ON DELETE SET NULL,
  room_id INT REFERENCES room(id) ON DELETE SET NULL,
  required_room_type TEXT NOT NULL DEFAULT 'Classroom',
  status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'completed', 'draft')),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_course_offering_dept ON course_offering(offering_department_id);

CREATE TABLE IF NOT EXISTS course_section (
  id SERIAL PRIMARY KEY,
  course_offering_id INT NOT NULL REFERENCES course_offering(id) ON DELETE CASCADE,
  section_name TEXT NOT NULL,
  capacity SMALLINT NOT NULL DEFAULT 60 CHECK (capacity >= 1),
  faculty_id INT REFERENCES faculty(id) ON DELETE SET NULL,
  room_id INT REFERENCES room(id) ON DELETE SET NULL,
  UNIQUE (course_offering_id, section_name)
);

CREATE TABLE IF NOT EXISTS course_enrollment (
  id SERIAL PRIMARY KEY,
  student_id INT NOT NULL REFERENCES student(id) ON DELETE CASCADE,
  course_offering_id INT NOT NULL REFERENCES course_offering(id) ON DELETE CASCADE,
  section_id INT REFERENCES course_section(id) ON DELETE SET NULL,
  enrollment_status TEXT NOT NULL DEFAULT 'enrolled' CHECK (enrollment_status IN ('enrolled', 'dropped')),
  enrollment_date TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (student_id, course_offering_id)
);
CREATE INDEX IF NOT EXISTS idx_enrollment_offering ON course_enrollment(course_offering_id);
CREATE INDEX IF NOT EXISTS idx_enrollment_student ON course_enrollment(student_id);

CREATE TABLE IF NOT EXISTS common_time_slot (
  id SERIAL PRIMARY KEY,
  academic_year_id INT REFERENCES academic_year(id),
  semester SMALLINT NOT NULL DEFAULT 1,
  day SMALLINT NOT NULL CHECK (day BETWEEN 0 AND 6),
  start_min SMALLINT NOT NULL,
  end_min SMALLINT NOT NULL,
  applicable_course_type TEXT NOT NULL CHECK (applicable_course_type IN ('MDC', 'Minor', 'Both')),
  name TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'inactive')),
  CHECK (end_min > start_min)
);

CREATE OR REPLACE VIEW common_scheduling_period AS
SELECT
  id,
  academic_year_id AS academic_year,
  semester,
  applicable_course_type AS applicable_course_types,
  day,
  start_min,
  end_min,
  (status = 'active') AS active
FROM common_time_slot;

ALTER TABLE timetable_entry ADD COLUMN IF NOT EXISTS course_offering_id INT REFERENCES course_offering(id) ON DELETE CASCADE;
ALTER TABLE timetable_entry ADD COLUMN IF NOT EXISTS section_id INT REFERENCES course_section(id) ON DELETE SET NULL;
ALTER TABLE timetable_entry ALTER COLUMN allocation_id DROP NOT NULL;
ALTER TABLE timetable_entry ALTER COLUMN class_id DROP NOT NULL;
ALTER TABLE timetable_entry ALTER COLUMN timetable_id DROP NOT NULL;
ALTER TABLE timetable_entry ALTER COLUMN faculty_id DROP NOT NULL;

ALTER TABLE timetable_entry DROP CONSTRAINT IF EXISTS te_no_teacher_overlap;
ALTER TABLE timetable_entry DROP CONSTRAINT IF EXISTS te_no_class_overlap;
ALTER TABLE timetable_entry DROP CONSTRAINT IF EXISTS te_no_section_overlap;

-- High-Performance Database Indexes for Timetable Grid, Conflicts & Allocations
CREATE INDEX IF NOT EXISTS idx_te_class ON timetable_entry(class_id);
CREATE INDEX IF NOT EXISTS idx_te_offering ON timetable_entry(course_offering_id);
CREATE INDEX IF NOT EXISTS idx_te_faculty ON timetable_entry(faculty_id);
CREATE INDEX IF NOT EXISTS idx_te_room ON timetable_entry(room_id);
CREATE INDEX IF NOT EXISTS idx_te_day_period ON timetable_entry(day, period);
CREATE INDEX IF NOT EXISTS idx_te_day_span ON timetable_entry(day, start_min, end_min);
CREATE INDEX IF NOT EXISTS idx_audit_dept ON audit_log(department_id, id DESC);
CREATE INDEX IF NOT EXISTS idx_class_dept ON class(department_id);
CREATE INDEX IF NOT EXISTS idx_alloc_class ON teacher_allocation(class_id);
CREATE INDEX IF NOT EXISTS idx_alloc_faculty ON teacher_allocation(faculty_id);

-- Timetable Entry Overlap Trigger
CREATE OR REPLACE FUNCTION check_timetable_entry_overlaps() RETURNS TRIGGER AS $$
BEGIN
    IF NEW.faculty_id IS NOT NULL AND EXISTS (
        SELECT 1 FROM timetable_entry
        WHERE id <> coalesce(NEW.id, -1)
          AND faculty_id = NEW.faculty_id
          AND day = NEW.day
          AND start_min < NEW.end_min
          AND end_min > NEW.start_min
    ) THEN
        RAISE EXCEPTION 'Teacher overlap conflict' USING ERRCODE = '23P01';
    END IF;

    IF NEW.room_id IS NOT NULL AND EXISTS (
        SELECT 1 FROM timetable_entry
        WHERE id <> coalesce(NEW.id, -1)
          AND room_id = NEW.room_id
          AND day = NEW.day
          AND start_min < NEW.end_min
          AND end_min > NEW.start_min
    ) THEN
        RAISE EXCEPTION 'Room overlap conflict' USING ERRCODE = '23P01';
    END IF;

    IF NEW.class_id IS NOT NULL AND EXISTS (
        SELECT 1 FROM timetable_entry
        WHERE id <> coalesce(NEW.id, -1)
          AND class_id = NEW.class_id
          AND day = NEW.day
          AND start_min < NEW.end_min
          AND end_min > NEW.start_min
    ) THEN
        RAISE EXCEPTION 'Class overlap conflict' USING ERRCODE = '23P01';
    END IF;

    IF NEW.section_id IS NOT NULL AND EXISTS (
        SELECT 1 FROM timetable_entry
        WHERE id <> coalesce(NEW.id, -1)
          AND section_id = NEW.section_id
          AND day = NEW.day
          AND start_min < NEW.end_min
          AND end_min > NEW.start_min
    ) THEN
        RAISE EXCEPTION 'Section overlap conflict' USING ERRCODE = '23P01';
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_timetable_entry_overlaps ON timetable_entry;
CREATE TRIGGER trg_timetable_entry_overlaps
BEFORE INSERT OR UPDATE ON timetable_entry
FOR EACH ROW EXECUTE FUNCTION check_timetable_entry_overlaps();

