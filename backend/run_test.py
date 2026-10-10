"""Double-click friendly: runs the engine test from anywhere. Usage: python run_test.py"""
import os, runpy
os.chdir(os.path.join(os.path.dirname(os.path.abspath(__file__)), "tests"))
runpy.run_path("test_engine.py", run_name="__main__")
