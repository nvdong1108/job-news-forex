import runpy, sys, os
sys.argv = [sys.argv[0], "guard"]
runpy.run_path(os.path.join(os.path.dirname(os.path.abspath(__file__)), "xau_run.py"), run_name="__main__")
