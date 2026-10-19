"""Hermes XAU engine - doc MT5 realtime (MetaTrader5 API), phan tich, dieu khien SELL cua EA "DONGNV BOT GRID v5".

Dieu khien: dung co che san co cua v5 - lenh SELL STOP gia 2222 = EA DUNG SELL.
  Hermes dat lenh do (magic HERMES_MAGIC) de TAT, xoa lenh do de BAT.
  Lenh SELL STOP 2222 do anh Dong tu dat (magic khac) -> Hermes KHONG dong vao (tat tay).

Chay (bang mt5env python):
  python xau_engine.py guard    -> moi 1 phut: tinh quyet dinh, ap vao MT5. Chi in khi trang thai doi.
  python xau_engine.py report   -> du lieu cho bao cao phan tich 30 phut (LLM viet bao cao).
  python xau_engine.py show     -> xem nhanh, khong thay doi gi.
"""
import csv
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone

import MetaTrader5 as mt5
import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

# ======================= CAU HINH =======================
TERMINAL = r"C:\Program Files\MetaTrader 5\terminal64.exe"
SYMBOL = "XAUUSDc"
BOT_MAGIC = 123              # magic cua EA grid
SELL_STOP_PRICE = 2222.0     # = input entrySellStop cua EA
HERMES_MAGIC = 922222        # magic lenh SELL STOP do Hermes dat (de phan biet voi lenh tay)
HERMES_COMMENT = "HERMES SELL OFF"

NEWS_HIGH_MIN = 30           # tat SELL truoc/sau tin USD do (phut)
NEWS_MED_MIN = 15            # tin cam
SCORE_OFF = 6                # diem xu huong tang >= -> TAT SELL
SCORE_TIGHT = 4              # >= -> BAT nhung tran thap hon
MAX_SELL_ORDERS = 20         # so lenh SELL grid toi da
MAX_SELL_DD_PCT = 15.0       # lo tha noi SELL > % balance -> TAT
CAP_HYST = 2.0               # $ - can roi xuong duoi tran - 2$ moi bat lai (chong bat/tat lien tuc)
# ========================================================

VN_TZ = timezone(timedelta(hours=7))
STATE_FILE = os.path.join(HERE, "xau_state.json")
OVERRIDE_FILE = os.path.join(HERE, "sell_override.json")
JOURNAL = os.path.join(HERE, "xau_journal.csv")       # nhat ky quyet dinh (rut kinh nghiem)
SNAPSHOTS = os.path.join(HERE, "xau_snapshots.csv")   # anh chup thi truong moi 30'


# ---------------- ket noi / du lieu ----------------
def connect():
    if not mt5.initialize(path=TERMINAL):
        raise RuntimeError(f"Khong ket noi duoc MT5: {mt5.last_error()}")
    if not mt5.symbol_select(SYMBOL, True):
        raise RuntimeError(f"Khong co symbol {SYMBOL}")


def rates(tf, n):
    r = mt5.copy_rates_from_pos(SYMBOL, tf, 0, n)
    if r is None or len(r) < 50:
        raise RuntimeError(f"Thieu du lieu nen {tf}: {mt5.last_error()}")
    df = pd.DataFrame(r)
    df["time"] = pd.to_datetime(df["time"], unit="s")
    return df


def ema(s, n):
    return s.ewm(span=n, adjust=False).mean()


def rsi(s, n=14):
    d = s.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + up / dn.replace(0, np.nan))


def atr(df, n=14):
    pc = df["close"].shift()
    tr = pd.concat([df["high"] - df["low"], (df["high"] - pc).abs(), (df["low"] - pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False).mean()


def adx(df, n=14):
    up = df["high"].diff()
    dn = -df["low"].diff()
    pdm = np.where((up > dn) & (up > 0), up, 0.0)
    ndm = np.where((dn > up) & (dn > 0), dn, 0.0)
    a = atr(df, n)
    pdi = 100 * pd.Series(pdm, index=df.index).ewm(alpha=1 / n, adjust=False).mean() / a
    ndi = 100 * pd.Series(ndm, index=df.index).ewm(alpha=1 / n, adjust=False).mean() / a
    dx = 100 * (pdi - ndi).abs() / (pdi + ndi).replace(0, np.nan)
    return dx.ewm(alpha=1 / n, adjust=False).mean(), pdi, ndi


def tf_info(df):
    """Chi bao tren nen DA DONG (iloc[-2]) + gia hien tai."""
    c = df["close"]
    e20, e50, e200 = ema(c, 20), ema(c, 50), ema(c, 200)
    r = rsi(c)
    a = atr(df)
    ax, pdi, ndi = adx(df)
    mid = c.rolling(20).mean()
    sd = c.rolling(20).std()
    i = -2
    return {
        "close": c.iloc[i], "last": c.iloc[-1],
        "ema20": e20.iloc[i], "ema50": e50.iloc[i], "ema200": e200.iloc[i],
        "rsi": r.iloc[i], "rsi_now": r.iloc[-1], "atr": a.iloc[i],
        "adx": ax.iloc[i], "pdi": pdi.iloc[i], "ndi": ndi.iloc[i],
        "bb_up": (mid + 2 * sd).iloc[i], "bb_lo": (mid - 2 * sd).iloc[i],
        "hi20": df["high"].iloc[-21:-1].max(), "lo20": df["low"].iloc[-21:-1].min(),
        "o": df["open"].iloc[-1], "h": df["high"].iloc[-1], "l": df["low"].iloc[-1],
    }


def trend_word(t):
    if t["close"] > t["ema20"] > t["ema50"]:
        return "TĂNG"
    if t["close"] < t["ema20"] < t["ema50"]:
        return "GIẢM"
    return "ĐI NGANG"


def bot_positions():
    ps = mt5.positions_get(symbol=SYMBOL) or []
    sells = [p for p in ps if p.magic == BOT_MAGIC and p.type == mt5.POSITION_TYPE_SELL]
    buys = [p for p in ps if p.magic == BOT_MAGIC and p.type == mt5.POSITION_TYPE_BUY]
    def agg(lst):
        return {
            "n": len(lst), "lots": round(sum(p.volume for p in lst), 2),
            "pl": round(sum(p.profit + p.swap for p in lst), 2),
            "hi": max((p.price_open for p in lst), default=0.0),
            "lo": min((p.price_open for p in lst), default=0.0),
        }
    return agg(sells), agg(buys)


def stop_orders():
    """(lenh SELL STOP 2222 cua Hermes, co lenh tay khong)"""
    os_ = mt5.orders_get(symbol=SYMBOL) or []
    mine, manual = [], False
    for o in os_:
        if o.type == mt5.ORDER_TYPE_SELL_STOP and abs(o.price_open - SELL_STOP_PRICE) < 0.001:
            if o.magic == HERMES_MAGIC:
                mine.append(o)
            else:
                manual = True
    return mine, manual


def news_now(now):
    try:
        import ff_calendar as ff
        evs = ff.events(ff.fetch())
    except Exception:
        return None, [], "không tải được lịch tin"
    block, upcoming = None, []
    for e in evs:
        win = NEWS_HIGH_MIN if e["impact"] == "High" else NEWS_MED_MIN
        if e["t"] - timedelta(minutes=win) <= now <= e["t"] + timedelta(minutes=win) and block is None:
            block = e
        if now <= e["t"] <= now + timedelta(hours=8):
            upcoming.append(e)
    return block, upcoming, None


# ---------------- phan tich + quyet dinh ----------------
def analyze():
    now = datetime.now(VN_TZ)
    tick = mt5.symbol_info_tick(SYMBOL)
    acc = mt5.account_info()
    term = mt5.terminal_info()
    d1, h4, h1, m30, m15 = (tf_info(rates(tf, 300)) for tf in
                            (mt5.TIMEFRAME_D1, mt5.TIMEFRAME_H4, mt5.TIMEFRAME_H1,
                             mt5.TIMEFRAME_M30, mt5.TIMEFRAME_M15))
    dd = rates(mt5.TIMEFRAME_D1, 60)
    pdh, pdl = dd["high"].iloc[-2], dd["low"].iloc[-2]
    bid = tick.bid
    sell, buy = bot_positions()

    # --- diem xu huong TANG (nguy hiem cho grid SELL) ---
    score, why = 0, []
    def add(cond, pts, txt):
        nonlocal score
        if cond:
            score += pts
            why.append(f"+{pts} {txt}")
    add(d1["close"] > d1["ema50"], 1, "D1 trên EMA50")
    add(d1["ema20"] > d1["ema50"], 1, "D1 EMA20>EMA50")
    add(h4["close"] > h4["ema20"] > h4["ema50"], 2, "H4 xu hướng tăng (giá>EMA20>EMA50)")
    add(h4["adx"] > 25 and h4["pdi"] > h4["ndi"], 1, f"H4 ADX {h4['adx']:.0f} lực tăng mạnh")
    add(h1["close"] > h1["ema20"] > h1["ema50"], 1, "H1 xu hướng tăng")
    add(h1["rsi_now"] > 65, 1, f"H1 RSI {h1['rsi_now']:.0f} quá mua theo đà")
    add(bid > pdh, 2, f"giá vượt đỉnh hôm qua {pdh:.2f}")
    add(bid > h4["hi20"], 1, f"giá phá đỉnh 20 nến H4 {h4['hi20']:.2f}")
    add(m15["last"] - m15["o"] > 1.5 * m15["atr"], 2, "nến M15 tăng đột biến (>1.5 ATR)")
    # diem giam (thuan loi cho SELL)
    if h4["close"] < h4["ema20"] < h4["ema50"]:
        score -= 2
        why.append("-2 H4 xu hướng giảm")
    if h1["rsi_now"] < 35:
        score -= 1
        why.append(f"-1 H1 RSI {h1['rsi_now']:.0f} yếu")

    atr_d = d1["atr"]
    cap_normal = min(pdh + 0.5 * atr_d, d1["o"] + 1.0 * atr_d)
    cap_tight = min(pdh + 0.25 * atr_d, d1["o"] + 0.6 * atr_d)
    cap = cap_tight if score >= SCORE_TIGHT else cap_normal
    cap = round(cap, 2)

    block, upcoming, news_err = news_now(now)
    try:
        with open(OVERRIDE_FILE, encoding="utf-8") as f:
            ov = json.load(f)
    except Exception:
        ov = {}
    mode = str(ov.get("mode", "AUTO")).upper()
    if ov.get("max_price"):
        cap = float(ov["max_price"])

    dd_pct = -sell["pl"] / acc.balance * 100 if acc and acc.balance and sell["pl"] < 0 else 0.0

    # --- quyet dinh ---
    on, reason, code = True, "Điều kiện bình thường, cho phép SELL grid", "ON"
    if mode == "OFF":
        on, reason, code = False, "Anh Đông tắt tay qua Hermes", "MANUAL_OFF"
    elif mode == "ON":
        on, reason, code = True, "Anh Đông bật tay qua Hermes", "MANUAL_ON"
    elif block:
        on, reason, code = False, f"Tin mạnh {block['t']:%H:%M} {block['title']}", "NEWS"
    elif dd_pct >= MAX_SELL_DD_PCT:
        on, reason, code = False, f"Lỗ thả nổi SELL {dd_pct:.1f}% balance (ngưỡng {MAX_SELL_DD_PCT}%)", "DD"
    elif score >= SCORE_OFF:
        on, reason, code = False, f"Xu hướng tăng mạnh (điểm {score}/{SCORE_OFF})", "TREND"
    elif sell["n"] >= MAX_SELL_ORDERS:
        on, reason, code = False, f"Đã đủ {MAX_SELL_ORDERS} lệnh SELL", "MAXN"
    else:
        state = load_state()
        was_cap = state.get("code") == "CAP"
        limit = cap - CAP_HYST if was_cap else cap
        if bid > limit:
            on, reason, code = False, f"Giá {bid:.2f} trên trần SELL {cap:.2f}", "CAP"
        elif score >= SCORE_TIGHT:
            reason, code = f"Cho phép SELL nhưng thận trọng (điểm tăng {score}), hạ trần", "ON_TIGHT"

    return {
        "now": now, "bid": bid, "ask": tick.ask, "spread": round(tick.ask - tick.bid, 3),
        "acc": acc, "algo": bool(term.trade_allowed), "connected": bool(term.connected),
        "d1": d1, "h4": h4, "h1": h1, "m30": m30, "m15": m15, "pdh": pdh, "pdl": pdl,
        "sell": sell, "buy": buy, "score": score, "why": why, "cap": cap,
        "on": on, "reason": reason, "code": code, "mode": mode,
        "news_block": block, "upcoming": upcoming, "news_err": news_err, "dd_pct": dd_pct,
    }


# ---------------- thuc thi ----------------
def place_off():
    info = mt5.symbol_info(SYMBOL)
    base = {
        "action": mt5.TRADE_ACTION_PENDING, "symbol": SYMBOL, "volume": info.volume_min,
        "type": mt5.ORDER_TYPE_SELL_STOP, "price": SELL_STOP_PRICE, "magic": HERMES_MAGIC,
        "comment": HERMES_COMMENT, "type_time": mt5.ORDER_TIME_GTC,
    }
    last = None
    for fill in (mt5.ORDER_FILLING_RETURN, mt5.ORDER_FILLING_FOK, mt5.ORDER_FILLING_IOC):
        r = mt5.order_send({**base, "type_filling": fill})
        if r and r.retcode == mt5.TRADE_RETCODE_DONE:
            return True, ""
        last = f"{r.retcode} {r.comment}" if r else str(mt5.last_error())
    return False, last


def remove_off(orders):
    err = ""
    for o in orders:
        r = mt5.order_send({"action": mt5.TRADE_ACTION_REMOVE, "order": o.ticket})
        if not r or r.retcode != mt5.TRADE_RETCODE_DONE:
            err = f"{r.retcode} {r.comment}" if r else str(mt5.last_error())
    return err == "", err


def load_state():
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_state(st):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False)


def journal(a, applied):
    new = not os.path.exists(JOURNAL)
    with open(JOURNAL, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["time_vn", "ts", "on", "code", "bid", "cap", "score", "sell_n", "sell_pl", "applied", "reason"])
        w.writerow([a["now"].strftime("%Y-%m-%d %H:%M"), int(time.time()), int(a["on"]), a["code"], a["bid"],
                    a["cap"], a["score"], a["sell"]["n"], a["sell"]["pl"], applied, a["reason"]])


def short_msg(a, extra=""):
    head = "🟢 HERMES: BẬT SELL" if a["on"] else "🔴 HERMES: TẮT SELL"
    lines = [f"{head} – {SYMBOL}",
             f"Lý do: {a['reason']}",
             f"Giá: {a['bid']:.2f} | Trần SELL: {a['cap']:.2f}",
             f"SELL bot: {a['sell']['n']} lệnh, {a['sell']['lots']:.2f} lot, {a['sell']['pl']:+.2f} {a['acc'].currency}"]
    if extra:
        lines.append(extra)
    lines.append(f"⏱ {a['now']:%H:%M %d/%m}")
    return "\n".join(lines)


def cmd_guard():
    st = load_state()
    try:
        connect()
        a = analyze()
    except Exception as ex:
        if st.get("err") != str(ex)[:60]:
            st["err"] = str(ex)[:60]
            save_state(st)
            print(f"⚠️ HERMES SELL GUARD: lỗi đọc MT5 – {ex}\nKiểm tra MT5 còn mở và đăng nhập.")
        return
    st.pop("err", None)

    mine, manual = stop_orders()
    is_off_now = bool(mine) or manual
    applied, extra = "ok", ""

    if manual:
        applied = "manual_stop"
        a["on"], a["code"], a["reason"] = False, "MANUAL_STOP", "Có lệnh SELL STOP 2222 đặt tay – tôn trọng lệnh tay"
        if mine:
            remove_off(mine)          # khong can 2 lenh
    elif not a["algo"]:
        applied = "algo_off"
        extra = "⚠️ MT5 đang TẮT Algo Trading – Hermes chưa thể điều khiển, EA cũng không vào lệnh."
    elif a["on"] and mine:
        ok, err = remove_off(mine)
        applied = "removed" if ok else f"remove_fail {err}"
    elif not a["on"] and not mine:
        ok, err = place_off()
        applied = "placed" if ok else f"place_fail {err}"
    if applied.endswith("fail") or "fail" in applied:
        extra = f"❌ Không thực thi được trên MT5: {applied}"

    changed = (st.get("on") != a["on"]) or (st.get("code") != a["code"]) or ("fail" in applied) \
        or (applied == "algo_off" and st.get("applied") != "algo_off")
    if changed:
        journal(a, applied)
        print(short_msg(a, extra))
    st.update({"on": a["on"], "code": a["code"], "cap": a["cap"], "applied": applied,
               "ts": int(time.time())})
    save_state(st)


def outcome_stats():
    """Rut kinh nghiem: voi moi lan TAT do xu huong/tran trong 7 ngay, gia sau 4h di tiep bao nhieu."""
    if not os.path.exists(JOURNAL):
        return []
    rows = list(csv.DictReader(open(JOURNAL, encoding="utf-8")))
    out = []
    cutoff = time.time() - 7 * 86400
    for r in rows:
        ts = int(r["ts"])
        if ts < cutoff or ts > time.time() - 4 * 3600 or r["on"] != "0" or r["code"] not in ("TREND", "CAP", "NEWS"):
            continue
        rr = mt5.copy_rates_range(SYMBOL, mt5.TIMEFRAME_M15, datetime.fromtimestamp(ts, timezone.utc),
                                  datetime.fromtimestamp(ts + 4 * 3600, timezone.utc))
        if rr is None or len(rr) == 0:
            continue
        up = max(x["high"] for x in rr) - float(r["bid"])
        out.append((r["time_vn"], r["code"], float(r["bid"]), round(up, 2)))
    return out[-6:]


def snapshot(a):
    new = not os.path.exists(SNAPSHOTS)
    with open(SNAPSHOTS, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["time_vn", "bid", "score", "on", "code", "cap", "h4_rsi", "h1_rsi", "h4_adx",
                        "d1_atr", "sell_n", "sell_pl", "equity"])
        w.writerow([a["now"].strftime("%Y-%m-%d %H:%M"), a["bid"], a["score"], int(a["on"]), a["code"],
                    a["cap"], round(a["h4"]["rsi"], 1), round(a["h1"]["rsi"], 1), round(a["h4"]["adx"], 1),
                    round(a["d1"]["atr"], 2), a["sell"]["n"], a["sell"]["pl"], a["acc"].equity])


def cmd_report(write=True):
    connect()
    a = analyze()
    mine, manual = stop_orders()
    if write:
        snapshot(a)
    f = lambda x: f"{x:.2f}"
    acc = a["acc"]
    L = []
    L.append(f"THOI_GIAN_VN: {a['now']:%H:%M %d/%m/%Y}")
    L.append(f"SYMBOL: {SYMBOL} | Bid {f(a['bid'])} | Ask {f(a['ask'])} | Spread {a['spread']}")
    L.append(f"TAI_KHOAN: balance {acc.balance} equity {acc.equity} {acc.currency} | AlgoTrading: {'BAT' if a['algo'] else 'TAT'}")
    for k in ("d1", "h4", "h1", "m30", "m15"):
        t = a[k]
        L.append(f"{k.upper()}: xu_huong {trend_word(t)} | close {f(t['close'])} EMA20 {f(t['ema20'])} EMA50 {f(t['ema50'])} "
                 f"EMA200 {f(t['ema200'])} | RSI {t['rsi']:.1f} (hien tai {t['rsi_now']:.1f}) | ATR {f(t['atr'])} | "
                 f"ADX {t['adx']:.1f} +DI {t['pdi']:.1f} -DI {t['ndi']:.1f} | BB {f(t['bb_lo'])}-{f(t['bb_up'])} | "
                 f"dinh20 {f(t['hi20'])} day20 {f(t['lo20'])}")
    L.append(f"NGAY: mo cua {f(a['d1']['o'])} cao {f(a['d1']['h'])} thap {f(a['d1']['l'])} | dinh hom qua {f(a['pdh'])} day hom qua {f(a['pdl'])}")
    L.append(f"DIEM_TANG: {a['score']} (TAT khi >= {SCORE_OFF}, than trong khi >= {SCORE_TIGHT}) | " + "; ".join(a["why"]))
    L.append(f"QUYET_DINH_SELL: {'BAT' if a['on'] else 'TAT'} | ma {a['code']} | ly do: {a['reason']} | TRAN_SELL {f(a['cap'])} | che do {a['mode']}")
    L.append(f"TRANG_THAI_MT5: lenh SELL STOP 2222 Hermes={'CO' if mine else 'KHONG'} tay={'CO' if manual else 'KHONG'}")
    s, b = a["sell"], a["buy"]
    L.append(f"BOT_SELL: {s['n']} lenh, {s['lots']} lot, P/L {s['pl']} {acc.currency}, gia vao cao nhat {f(s['hi'])} thap nhat {f(s['lo'])} | toi da {MAX_SELL_ORDERS}")
    L.append(f"BOT_BUY: {b['n']} lenh, {b['lots']} lot, P/L {b['pl']} {acc.currency}")
    if a["news_err"]:
        L.append(f"TIN: LOI {a['news_err']}")
    elif a["upcoming"]:
        L.append("TIN_SAP_TOI (8h, gio VN): " + " ; ".join(
            f"{e['t']:%H:%M} {'DO' if e['impact']=='High' else 'CAM'} {e['title']} (DB {e['forecast']}, truoc {e['previous']})"
            for e in a["upcoming"]))
    else:
        L.append("TIN_SAP_TOI: khong co tin USD do/cam trong 8h")
    st = outcome_stats()
    if st:
        L.append("KINH_NGHIEM_7_NGAY (lan TAT SELL -> gia tang them toi da trong 4h sau): " + " ; ".join(
            f"{t} {c} tai {p:.2f} -> +{u}" for t, c, p, u in st))
    print("\n".join(L))


def cmd_account():
    """Bao cao tai khoan nhanh (khong LLM) cho lenh /taikhoan."""
    connect()
    now = datetime.now(VN_TZ)
    acc = mt5.account_info()
    term = mt5.terminal_info()
    tick = mt5.symbol_info_tick(SYMBOL)
    cur = acc.currency
    ps = mt5.positions_get() or []
    sell, buy = bot_positions()
    mine, manual = stop_orders()
    other = [p for p in ps if not (p.symbol == SYMBOL and p.magic == BOT_MAGIC)]

    # lai/lo da chot hom nay (tu 00:00 gio VN)
    day0 = now.replace(hour=0, minute=0, second=0, microsecond=0)
    deals = mt5.history_deals_get(day0.astimezone(timezone.utc), datetime.now(timezone.utc) + timedelta(days=1)) or []
    closed = [d for d in deals if d.entry in (mt5.DEAL_ENTRY_OUT, mt5.DEAL_ENTRY_INOUT, mt5.DEAL_ENTRY_OUT_BY)]
    day_pl = sum(d.profit + d.swap + d.commission for d in closed)

    float_pl = acc.equity - acc.balance
    ml = f"{acc.margin_level:.0f}%" if acc.margin else "-"
    if manual:
        sell_state = "🔴 TẮT (lệnh SELL STOP 2222 đặt tay)"
    elif mine:
        sell_state = "🔴 TẮT (Hermes)"
    else:
        sell_state = "🟢 BẬT"
    st = load_state()

    pnl_icon = "🟢" if float_pl > 0 else ("🔴" if float_pl < 0 else "⚪")
    pnl_word = "DƯƠNG" if float_pl > 0 else ("ÂM" if float_pl < 0 else "HOÀ")
    L = [f"#{acc.login} | {acc.server}",
         f"Balance: {acc.balance:,.2f} {cur}",
         f"Equity:  {acc.equity:,.2f} {cur} ({float_pl:+,.2f})",
         f"Lãi/lỗ đã chốt hôm nay: {day_pl:+,.2f} {cur}",
         f"PNL: {pnl_icon} {pnl_word} {float_pl:+,.2f} {cur}",
         "",
         f"📈 {SYMBOL}: {tick.ask:.2f}",
         f"🤖 Bot GRID:",
         f"  SELL: {sell['n']} lệnh | {sell['lots']:.2f} lot | {sell['pl']:+,.2f} {cur}",
         f"  BUY:  {buy['n']} lệnh | {buy['lots']:.2f} lot | {buy['pl']:+,.2f} {cur}",
         f"  Trạng thái SELL: {sell_state}"
         + (f" | trần {st['cap']:.2f}" if st.get("cap") else "")]
    if other:
        L.append(f"Lệnh khác: {len(other)} lệnh | {sum(p.volume for p in other):.2f} lot | "
                 f"{sum(p.profit + p.swap for p in other):+,.2f} {cur}")
    if not term.trade_allowed:
        L.append("⚠️ MT5 đang TẮT Algo Trading")
    if not term.connected:
        L.append("⚠️ MT5 mất kết nối server")
    print("\n".join(L))


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "show"
    try:
        if mode == "guard":
            cmd_guard()
        elif mode == "account":
            cmd_account()
        elif mode == "report":
            # cuoi tuan (gio VN: T7 05:00 -> T2 05:00) -> im lang
            now = datetime.now(VN_TZ)
            wd = now.weekday()
            if (wd == 5 and now.hour >= 5) or wd == 6 or (wd == 0 and now.hour < 5):
                print("MARKET_CLOSED")
                return
            cmd_report()
        else:
            cmd_report(write=False)
    finally:
        mt5.shutdown()


if __name__ == "__main__":
    main()
