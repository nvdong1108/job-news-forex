"""ForexFactory calendar -> tin VANG (gio Viet Nam).

Nguon DUY NHAT: feed chinh thuc cua ForexFactory
  https://nfs.faireconomy.media/ff_calendar_thisweek.xml (gio GMT, co link tung tin)
Gio trong XML la GMT (UTC) -> +7 ra gio VN (VN khong co DST).
Cuoi tin co note: Nguon tin tuc: ForexFactory (chu thuong, khong link)

Cach chay:
  python ff_calendar.py today    -> danh sach tin hom nay (dung cho bao sang 7h)
  python ff_calendar.py remind   -> nhac tin sap ra trong REMIND_MINUTES phut toi;
                                    khong co tin -> KHONG in gi (cron se im lang)
"""
import json
import os
import sys
import urllib.request
from datetime import datetime, timedelta, timezone

import xml.etree.ElementTree as ET

URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.xml"
VN_TZ = timezone(timedelta(hours=7))          # Viet Nam khong co DST
IMPACTS = ("High", "Medium")                  # Do + Cam
COUNTRIES = ("USD",)                          # tien te anh huong vang
REMIND_MINUTES = 45                           # cua so nhac (cron chay moi 30 phut)
STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ff_reminded.json")
ICON = {"High": "\U0001F7E5", "Medium": "\U0001F7E7"}   # vuong do / vuong cam

sys.stdout.reconfigure(encoding="utf-8")


CACHE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ff_cache.json")
CACHE_MAX_AGE = 20 * 60   # feed gioi han so lan goi (429) -> dung cache 20 phut


def _parse_xml(raw):
    """XML cua ForexFactory: date MM-DD-YYYY, time la gio GMT (vd 12:30pm), co <url> tung tin."""
    root = ET.fromstring(raw)
    data = []
    for ev in root.findall("event"):
        g = lambda tag: ((ev.find(tag).text or "").strip() if ev.find(tag) is not None else "")
        data.append({k: g(k) for k in ("title", "country", "date", "time", "impact",
                                         "forecast", "previous", "url")})
    if not data:
        raise ValueError("feed rong")
    return data


def fetch():
    """Lay feed; dung cache neu con moi, hoac khi mang loi/429 (cache < 12h)."""
    import time
    age = time.time() - os.path.getmtime(CACHE_FILE) if os.path.exists(CACHE_FILE) else 1e9
    if age < CACHE_MAX_AGE:
        with open(CACHE_FILE, encoding="utf-8") as f:
            return json.load(f)
    try:
        req = urllib.request.Request(URL, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=25) as r:
            data = _parse_xml(r.read())
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        return data
    except Exception:
        if age < 12 * 3600:
            with open(CACHE_FILE, encoding="utf-8") as f:
                return json.load(f)
        raise


def _to_vn(date_s, time_s):
    # gio trong XML la GMT -> +7 = gio VN. "All Day"/"Tentative" -> bo qua
    t = time_s.lower().replace(" ", "")
    d = datetime.strptime(f"{date_s} {t}", "%m-%d-%Y %I:%M%p")
    return d.replace(tzinfo=timezone.utc).astimezone(VN_TZ)


def events(data):
    out = []
    for e in data:
        if e.get("impact") not in IMPACTS or e.get("country") not in COUNTRIES:
            continue
        try:
            t = _to_vn(e["date"], e["time"])
        except Exception:
            continue
        out.append({"t": t, "title": e.get("title", ""), "impact": e["impact"],
                    "country": e["country"], "forecast": e.get("forecast") or "-",
                    "previous": e.get("previous") or "-",
                    "url": e.get("url") or "https://www.forexfactory.com/calendar"})
    out.sort(key=lambda x: x["t"])
    return out


def line(ev):
    return (f"{ev['t']:%H:%M} {ICON[ev['impact']]} {ev['country']} {ev['title']}"
            f" | Dự báo: {ev['forecast']} | Trước: {ev['previous']}")


def cmd_today(evs):
    now = datetime.now(VN_TZ)
    today = [e for e in evs if e["t"].date() == now.date()]
    print(f"NGUON: ForexFactory | Ngay (gio VN): {now:%d/%m/%Y} | So tin: {len(today)}")
    for e in today:
        print(line(e))


def cmd_remind(evs):
    now = datetime.now(VN_TZ)
    end = now + timedelta(minutes=REMIND_MINUTES)
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            sent = set(json.load(f))
    except Exception:
        sent = set()
    hits = []
    for e in evs:
        key = f"{e['t'].isoformat()}|{e['country']}|{e['title']}"
        if now <= e["t"] <= end and key not in sent:
            hits.append(e)
            sent.add(key)
    if not hits:
        return
    mins = int((hits[0]["t"] - now).total_seconds() // 60)
    out = [f"\u23f0 SẮP CÓ TIN VÀNG (khoảng {mins} phút nữa) - ForexFactory"]
    for e in hits:
        out.append(line(e))
    out.append("\U0001F916 AI dự đoán: vàng có thể biến động mạnh 2 chiều, cân nhắc đứng ngoài trước tin.")
    out.append("\u26a0\ufe0f Không phải khuyến nghị đầu tư.")
    out.append("Nguồn tin tức: ForexFactory")
    print("\n".join(out))
    # chi giu 200 key gan nhat
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(sorted(sent)[-200:], f)


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "remind"
    try:
        evs = events(fetch())
    except Exception as ex:
        if mode == "today":
            print(f"LOI: khong tai duoc lich ForexFactory ({ex})")
        return  # remind: im lang khi loi mang
    cmd_today(evs) if mode == "today" else cmd_remind(evs)


if __name__ == "__main__":
    main()
