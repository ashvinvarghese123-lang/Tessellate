-- Migration 010: High-Performance Database Indexes for Timetable Grid, Conflicts & Allocations
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
