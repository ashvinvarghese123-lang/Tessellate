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
