import runpy, sys, os, json

HERE = os.path.dirname(os.path.abspath(__file__))
# CO TAT: neu ton tai file xau_report.off -> khong chay phan tich, khong goi AI, khong gui tin.
# Bat lai: xoa file xau_report.off
OFF_FLAG = os.path.join(HERE, "xau_report.off")

if os.path.exists(OFF_FLAG):
    print(json.dumps({"wakeAgent": False}))
    sys.exit(0)

sys.argv = [sys.argv[0], "report"]
runpy.run_path(os.path.join(HERE, "xau_run.py"), run_name="__main__")
