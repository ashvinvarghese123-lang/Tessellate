-- Migration 006: Cross-Department MDC, Minor & Student Enrollment Integration

-- 1. Institutional Category
CREATE TABLE IF NOT EXISTS institutional_category (
  id SERIAL PRIMARY KEY,
  name TEXT UNIQUE NOT NULL CHECK (name IN ('Aided', 'Self-Financing'))
);
INSERT INTO institutional_category (name) VALUES ('Aided'), ('Self-Financing')
ON CONFLICT (name) DO NOTHING;

-- 2. Department Category Link
ALTER TABLE department ADD COLUMN IF NOT EXISTS category_id INT REFERENCES institutional_category(id);

UPDATE department SET category_id = (SELECT id FROM institutional_category WHERE name = 'Aided')
WHERE category_id IS NULL AND code IN ('DEPT-CS', 'DEPT-MATHS', 'DEPT-COMMERCE');

UPDATE department SET category_id = (SELECT id FROM institutional_category WHERE name = 'Self-Financing')
WHERE category_id IS NULL AND code IN ('DEPT-BCA', 'DEPT-CHEM', 'DEPT-PHYSICS');

UPDATE department SET category_id = (SELECT id FROM institutional_category WHERE name = 'Aided')
WHERE category_id IS NULL;

-- 3. Student Table
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

-- 4. Course Table (General subject / course definition)
CREATE TABLE IF NOT EXISTS course (
  id SERIAL PRIMARY KEY,
  course_code TEXT UNIQUE NOT NULL,
  course_name TEXT NOT NULL,
  course_type TEXT NOT NULL CHECK (course_type IN ('Regular', 'MDC', 'Minor')),
  department_id INT NOT NULL REFERENCES department(id) ON DELETE CASCADE,
  description TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_course_dept ON course(department_id);

-- 5. Course Offering Table (Actual academic instance)
CREATE TABLE IF NOT EXISTS course_offering (
  id SERIAL PRIMARY KEY,
  offering_code TEXT UNIQUE NOT NULL,
  course_id INT NOT NULL REFERENCES course(id) ON DELETE CASCADE,
  offering_department_id INT NOT NULL REFERENCES department(id) ON DELETE CASCADE,
  academic_year_id INT REFERENCES academic_year(id),
  semester SMALLINT NOT NULL DEFAULT 1,
  scheduling_scope TEXT NOT NULL CHECK (scheduling_scope IN ('college_wide', 'department_specific')),
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

-- 6. Course Section Table
CREATE TABLE IF NOT EXISTS course_section (
  id SERIAL PRIMARY KEY,
  course_offering_id INT NOT NULL REFERENCES course_offering(id) ON DELETE CASCADE,
  section_name TEXT NOT NULL,
  capacity SMALLINT NOT NULL DEFAULT 60 CHECK (capacity >= 1),
  faculty_id INT REFERENCES faculty(id) ON DELETE SET NULL,
  room_id INT REFERENCES room(id) ON DELETE SET NULL,
  UNIQUE (course_offering_id, section_name)
);

-- 7. Course Enrollment Table
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

-- 8. Common Time Slot Table (College-Wide Fixed Slots)
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

-- 9. Timetable Entry adaptations
ALTER TABLE timetable_entry ADD COLUMN IF NOT EXISTS course_offering_id INT REFERENCES course_offering(id) ON DELETE CASCADE;
ALTER TABLE timetable_entry ADD COLUMN IF NOT EXISTS section_id INT REFERENCES course_section(id) ON DELETE SET NULL;
ALTER TABLE timetable_entry ALTER COLUMN allocation_id DROP NOT NULL;
ALTER TABLE timetable_entry ALTER COLUMN class_id DROP NOT NULL;
ALTER TABLE timetable_entry ALTER COLUMN timetable_id DROP NOT NULL;
ALTER TABLE timetable_entry ALTER COLUMN faculty_id DROP NOT NULL;

ALTER TABLE timetable_entry DROP CONSTRAINT IF EXISTS te_no_teacher_overlap;
ALTER TABLE timetable_entry ADD CONSTRAINT te_no_teacher_overlap EXCLUDE USING gist (faculty_id WITH =, day WITH =, span WITH &&) WHERE (faculty_id IS NOT NULL);

ALTER TABLE timetable_entry DROP CONSTRAINT IF EXISTS te_no_class_overlap;
ALTER TABLE timetable_entry ADD CONSTRAINT te_no_class_overlap EXCLUDE USING gist (class_id WITH =, day WITH =, span WITH &&) WHERE (class_id IS NOT NULL);

ALTER TABLE timetable_entry DROP CONSTRAINT IF EXISTS te_no_section_overlap;
ALTER TABLE timetable_entry ADD CONSTRAINT te_no_section_overlap EXCLUDE USING gist (section_id WITH =, day WITH =, span WITH &&) WHERE (section_id IS NOT NULL);
