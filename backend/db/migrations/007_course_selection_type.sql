-- Migration 007: Course Selection-Based Scheduling Update (Student-Selected vs Department-Selected)

-- 1. Add selection_type to course table
ALTER TABLE course ADD COLUMN IF NOT EXISTS selection_type TEXT CHECK (selection_type IN ('STUDENT_SELECTED', 'DEPARTMENT_SELECTED'));

-- Ensure course_type check allows Regular, MDC, Minor in standard or upper case
ALTER TABLE course DROP CONSTRAINT IF EXISTS course_course_type_check;
ALTER TABLE course ADD CONSTRAINT course_course_type_check CHECK (course_type IN ('Regular', 'MDC', 'Minor', 'REGULAR', 'MINOR'));

-- Set selection_type for existing courses
UPDATE course SET selection_type = NULL WHERE course_type IN ('Regular', 'REGULAR');
UPDATE course SET selection_type = 'STUDENT_SELECTED'
WHERE course_type IN ('MDC', 'Minor', 'MINOR')
  AND id IN (SELECT course_id FROM course_offering WHERE scheduling_scope = 'college_wide');
UPDATE course SET selection_type = 'DEPARTMENT_SELECTED'
WHERE course_type IN ('MDC', 'Minor', 'MINOR')
  AND (selection_type IS NULL OR id IN (SELECT course_id FROM course_offering WHERE scheduling_scope = 'department_specific'));

-- 2. Add selection_type to course_offering table
ALTER TABLE course_offering ADD COLUMN IF NOT EXISTS selection_type TEXT CHECK (selection_type IN ('STUDENT_SELECTED', 'DEPARTMENT_SELECTED'));

UPDATE course_offering SET selection_type = 'STUDENT_SELECTED' WHERE scheduling_scope = 'college_wide';
UPDATE course_offering SET selection_type = 'DEPARTMENT_SELECTED' WHERE scheduling_scope = 'department_specific';
UPDATE course_offering SET selection_type = 'STUDENT_SELECTED' WHERE selection_type IS NULL;

-- 3. Common Scheduling Period View (Schema compatibility for Section 10 entity)
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
