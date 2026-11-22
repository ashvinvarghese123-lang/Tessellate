-- Migration 014: Workspace Simplification, Course Categories on Subjects, and MDC/Minor Common Slot Template Assignments

ALTER TABLE subject ADD COLUMN IF NOT EXISTS course_category TEXT NOT NULL DEFAULT 'Regular' CHECK (course_category IN ('Regular', 'MDC', 'Minor'));
ALTER TABLE subject ADD COLUMN IF NOT EXISTS duration_min INT NOT NULL DEFAULT 60;
ALTER TABLE teacher_allocation ADD COLUMN IF NOT EXISTS duration_min INT NOT NULL DEFAULT 60;

CREATE TABLE IF NOT EXISTS common_slot_assignment (
  id SERIAL PRIMARY KEY,
  department_id INT NOT NULL REFERENCES department(id) ON DELETE CASCADE,
  common_slot_id INT NOT NULL REFERENCES common_time_slot(id) ON DELETE CASCADE,
  subject_id INT REFERENCES subject(id) ON DELETE CASCADE,
  course_offering_id INT REFERENCES course_offering(id) ON DELETE CASCADE,
  faculty_id INT REFERENCES faculty(id) ON DELETE SET NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (department_id, common_slot_id, subject_id)
);

CREATE INDEX IF NOT EXISTS idx_cslot_assign_dept ON common_slot_assignment(department_id);
CREATE INDEX IF NOT EXISTS idx_cslot_assign_slot ON common_slot_assignment(common_slot_id);
CREATE INDEX IF NOT EXISTS idx_cslot_assign_fac ON common_slot_assignment(faculty_id);
