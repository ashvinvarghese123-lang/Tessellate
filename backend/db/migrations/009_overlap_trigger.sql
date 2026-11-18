-- Migration 009: Implement timetable_entry overlap exclusion trigger
-- Replaces btree_gist extension exclusion constraints with a native PL/pgSQL trigger.
-- Enforces identical exclusion rules (teacher, room, class, section non-overlap) without external DLL dependencies.

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
