-- 011_registry_enhancements.sql
-- Enhancements for centralized College Registry

-- 1. Department additions
ALTER TABLE department ADD COLUMN IF NOT EXISTS description TEXT;
ALTER TABLE department ADD COLUMN IF NOT EXISTS active BOOLEAN NOT NULL DEFAULT TRUE;

-- 2. Allow NULL email in department_account (no public email registration required)
ALTER TABLE department_account ALTER COLUMN email DROP NOT NULL;
ALTER TABLE department_account ALTER COLUMN email SET DEFAULT NULL;

-- 3. Faculty additions
ALTER TABLE faculty ADD COLUMN IF NOT EXISTS phone TEXT;
ALTER TABLE faculty ADD COLUMN IF NOT EXISTS specialization TEXT;

-- 4. Multi-department assignment for faculty
CREATE TABLE IF NOT EXISTS faculty_department_assignment (
  faculty_id INT NOT NULL REFERENCES faculty(id) ON DELETE CASCADE,
  department_id INT NOT NULL REFERENCES department(id) ON DELETE CASCADE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (faculty_id, department_id)
);

-- 5. Class enhancements
ALTER TABLE class ADD COLUMN IF NOT EXISTS program_name TEXT;
ALTER TABLE class ADD COLUMN IF NOT EXISTS course_name TEXT;
