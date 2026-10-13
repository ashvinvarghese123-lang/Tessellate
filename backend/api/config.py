"""Feature switches. Rooms are switched OFF for now: timetables are made without rooms or labs.
To bring rooms back later, set the environment variable USE_ROOMS=1 (nothing is deleted)."""
import os

USE_ROOMS = os.environ.get("USE_ROOMS") == "1"
