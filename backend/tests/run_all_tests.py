"""Test runner for TESSellate.
Runs each test suite against a clean seeded database.
"""
import os
import subprocess
import sys

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SEED_SCRIPT = os.path.join(BACKEND_DIR, "db", "seed.py")

TESTS = [
    "test_selection_types.py",
    "test_cross_dept.py",
    "test_timetable_editor.py",
    "test_no_otp.py",
    "test_api.py",
    "test_conflicts.py",
    "test_faculty.py",
    "test_rules.py",
    "test_registry.py",
    "test_signup.py",
]

def run():
    env = os.environ.copy()
    env["SEED_PASSWORD"] = "TestPass-1234"
    env["PYTHONPATH"] = BACKEND_DIR

    all_passed = True
    for test in TESTS:
        print(f"\n{'='*20} RUNNING: {test} {'='*20}")
        # 1. Reseed DB
        reseed = subprocess.run([sys.executable, SEED_SCRIPT], cwd=BACKEND_DIR, env=env, capture_output=True, text=True)
        if reseed.returncode != 0:
            print(f"FAILED TO SEED FOR {test}: {reseed.stderr}")
            all_passed = False
            continue

        # 2. Run Test
        test_path = os.path.join(BACKEND_DIR, "tests", test)
        res = subprocess.run([sys.executable, test_path], cwd=BACKEND_DIR, env=env)
        if res.returncode != 0:
            print(f"FAILED: {test}")
            all_passed = False
        else:
            print(f"SUCCESS: {test}")

    if all_passed:
        print("\n\n>>> ALL TEST SUITES COMPLETED AND PASSED 100%! <<<")
    else:
        print("\n\n>>> SOME TESTS FAILED. <<<")
        sys.exit(1)

if __name__ == "__main__":
    run()
