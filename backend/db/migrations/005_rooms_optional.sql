-- Rooms are optional for now: a timetable session may have no room. Room data is kept for later.
ALTER TABLE timetable_entry ALTER COLUMN room_id DROP NOT NULL;
