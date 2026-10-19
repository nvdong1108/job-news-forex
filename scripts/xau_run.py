"""Cron wrapper: chay xau_engine.py bang venv co MetaTrader5 (mt5env)."""
import os
import subprocess
import sys

sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
PY = os.path.join(os.path.dirname(HERE), "mt5env", "Scripts", "python.exe")
mode = sys.argv[1] if len(sys.argv) > 1 else "guard"
r = subprocess.run([PY, os.path.join(HERE, "xau_engine.py"), mode], capture_output=True,
                   text=True, encoding="utf-8", errors="replace", timeout=150,
                   env={**os.environ, "PYTHONIOENCODING": "utf-8"})
out = (r.stdout or "").strip()
if r.returncode != 0:
    print(f"⚠️ Hermes XAU engine lỗi ({mode}):\n{(r.stderr or '')[-800:]}")
elif mode == "report" and out == "MARKET_CLOSED":
    print('{"wakeAgent": false}')
else:
    print(out)
