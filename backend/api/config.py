"""Feature switches. Rooms are switched OFF for now: timetables are made without rooms or labs.
To bring rooms back later, set the environment variable USE_ROOMS=1 (nothing is deleted)."""
import os

USE_ROOMS = os.environ.get("USE_ROOMS") == "1"

# Two-step sign-in (a code emailed after the password). ON by default and in production.
# TEMPORARY testing switch: set the environment variable REQUIRE_OTP=0 to sign in with the password alone and to create
# department accounts without an emailed confirmation code. Set it back to 1 (or remove it) to turn the codes on again.
REQUIRE_OTP = os.environ.get("REQUIRE_OTP", "1") != "0"
