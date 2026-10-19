"""Gold 30m watchdog: prints alert only if High/Medium USD news within next 60 min, else prints nothing."""
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.xml"
VN_TZ = timezone(timedelta(hours=7))


def et_offset(date_naive):
    # US DST: 2nd Sunday of March -> 1st Sunday of November = UTC-4, else UTC-5
    y = date_naive.year
    def nth_sunday(year, month, n):
        from datetime import date as dcls
        count, day = 0, 1
        while True:
            dt = dcls(year, month, day)
            if dt.weekday() == 6:
                count += 1
                if count == n:
                    return dt
            day += 1
    import datetime as _dt
    dst_start = nth_sunday(y, 3, 2)
    # first Sunday of November
    nov1 = _dt.date(y, 11, 1)
    days_to_sun = (6 - nov1.weekday()) % 7
    dst_end = _dt.date(y, 11, 1 + days_to_sun)
    dd = date_naive.date()
    return -4 if dst_start <= dd < dst_end else -5

ICON = {"High": "\U0001F7E5", "Medium": "\U0001F7E7"}


def parse_et(dt_date: str, dt_time: str):
    # date: MM-DD-YYYY, time: e.g. "12:30pm", "8:00am", "All Day"
    try:
        if not dt_time or "all day" in dt_time.lower():
            return None
        t = dt_time.strip().lower().replace(" ", "")
        d = datetime.strptime(f"{dt_date.strip()} {t}", "%m-%d-%Y %I:%M%p")
        off = et_offset(d)
        return d.replace(tzinfo=timezone(timedelta(hours=off)))
    except Exception:
        return None


def main():
    try:
        req = urllib.request.Request(URL, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=25) as r:
            raw = r.read()
    except Exception:
        return
    try:
        root = ET.fromstring(raw)
    except Exception:
        return

    now_vn = datetime.now(VN_TZ)
    window_end = now_vn + timedelta(minutes=60)
    hits = []

    for ev in root.findall("event"):
        def txt(tag):
            n = ev.find(tag)
            return (n.text or "").strip() if n is not None and n.text else ""
        impact = txt("impact")
        if impact not in ("High", "Medium"):
            continue
        country = txt("country")
        if country != "USD":
            continue
        et_dt = parse_et(txt("date"), txt("time"))
        if et_dt is None:
            continue
        vn_dt = et_dt.astimezone(VN_TZ)
        if now_vn <= vn_dt <= window_end:
            mins = int((vn_dt - now_vn).total_seconds() // 60)
            hits.append((vn_dt, mins, txt("title"), impact, txt("forecast"), txt("previous")))

    if not hits:
        return
    hits.sort()
    mins_max = max(m for _, m, *_ in hits)
    lines = [f"\u23f0 S\u1eaeP C\u00d3 TIN V\u00c0NG ({mins_max} ph\u00fat n\u1eefa)"]
    for vn_dt, mins, title, impact, fc, prev in hits:
        lines.append(f"{vn_dt.strftime('%H:%M')} {ICON.get(impact, '')} {title} | D\u1ef1 b\u00e1o: {fc or '-'} | Tr\u01b0\u1edbc: {prev or '-'}")
        lines.append("\U0001F916 AI d\u1ef1 \u0111o\u00e1n: v\u00e0ng c\u00f3 th\u1ec3 bi\u1ebfn \u0111\u1ed9ng m\u1ea1nh, c\u00e2n nh\u1eafc \u0111\u1ee9ng ngo\u00e0i tr\u01b0\u1edbc tin.")
    lines.append("\u26a0\ufe0f V\u00e0ng c\u00f3 th\u1ec3 gi\u1eadt m\u1ea1nh. Kh\u00f4ng ph\u1ea3i khuy\u1ebfn ngh\u1ecb \u0111\u1ea7u t\u01b0.")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
