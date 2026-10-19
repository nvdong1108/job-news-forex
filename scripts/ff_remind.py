import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ff_calendar
sys.argv = ["ff_calendar.py", "remind"]
ff_calendar.main()
