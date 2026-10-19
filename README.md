# job-news-forex – Bot báo tin vàng & điều khiển SELL grid (Hermes cron)

Bộ script chạy trong **Hermes cron** để:

- Báo lịch tin kinh tế USD ảnh hưởng vàng (ForexFactory) mỗi sáng 7h lên Telegram.
- Nhắc trước khi tin High/Medium sắp ra.
- Theo dõi MT5 (XAUUSDc, Exness cent) và tự **bật/tắt chiều SELL** của EA `DONGNV BOT GRID v5`.
- Tạo dữ liệu cho báo cáo phân tích vàng theo giờ (đang tắt).

## Cấu trúc

```
job-news-forex/
├── scripts/
│   ├── ff_calendar.py     # Lõi lịch ForexFactory: today / remind
│   ├── ff_today.py        # Cron entry: báo sáng 7h      -> ff_calendar today
│   ├── ff_remind.py       # Cron entry: nhắc trước tin   -> ff_calendar remind
│   ├── xau_engine.py      # Lõi MT5: phân tích + điều khiển SELL (guard/report/show/account)
│   ├── xau_run.py         # Wrapper: chạy xau_engine.py bằng venv mt5env
│   ├── xau_guard.py       # Cron entry: SELL guard 5 phút -> xau_run guard
│   ├── xau_report.py      # Cron entry: báo cáo 1 giờ     -> xau_run report (có công tắc .off)
│   └── gold_30m.py        # Bản cũ (watchdog tin 60 phút), không job nào dùng
├── cron/
│   └── jobs.example.json  # Cấu hình 4 cron job (prompt, lịch, nơi gửi) – ID nhóm đã che
├── requirements.txt
├── .gitignore
└── README.md
```

## Các cron job

| ID | Tên | Lịch | Script | Gọi AI | Gửi tới |
|---|---|---|---|---|---|
| `8cb371bc66b5` | Vàng – báo sáng 7h (ForexFactory) | `0 7 * * *` | `ff_today.py` | Có (viết bản tin từ output script) | origin + Alert XAU + Kairos |
| `61ba07235851` | Vàng – nhắc trước tin | mỗi 30 phút | `ff_remind.py` | Không (gửi thẳng output) | origin + Alert XAU + Kairos |
| `9a5ef58d5810` | XAU SELL guard | mỗi 5 phút | `xau_guard.py` | Không | Alert XAU (test) |
| `e90064b90867` | XAU báo cáo phân tích 1 giờ | `1 * * * *` (đang **tắt**) | `xau_report.py` | Có | Alert XAU (test) |

Nguyên tắc chung của Hermes cron:

- Job có `no_agent: true` → script in gì thì gửi đúng nội dung đó, **in rỗng = không gửi** (im lặng).
- Job gọi AI → output script được đưa vào prompt làm dữ liệu, AI viết tin rồi gửi.
- Script in `{"wakeAgent": false}` → bỏ qua lượt chạy (không gọi AI, không gửi).

Prompt đầy đủ của từng job nằm trong `cron/jobs.example.json`.

## 1. Lịch tin ForexFactory – `ff_calendar.py`

- Nguồn duy nhất: `https://nfs.faireconomy.media/ff_calendar_thisweek.xml` (giờ GMT, cộng 7 = giờ VN).
- Lọc: tiền tệ `USD`, impact `High` (🟥) và `Medium` (🟧).
- Cache 20 phút trong `ff_cache.json` (feed hay trả 429).
- Cuối tin ghi `Nguồn tin tức: ForexFactory` (chữ thường, **không link**).

```bash
python scripts/ff_calendar.py today    # danh sách tin hôm nay (báo sáng 7h)
python scripts/ff_calendar.py remind   # tin sắp ra trong REMIND_MINUTES (45') tới; không có -> không in gì
```

Tin đã nhắc được lưu trong `ff_reminded.json` (giữ 200 key gần nhất) để không nhắc trùng.

Cấu hình đầu file: `IMPACTS`, `COUNTRIES`, `REMIND_MINUTES`.

## 2. MT5 engine – `xau_engine.py`

Đọc MT5 realtime qua thư viện `MetaTrader5` (terminal phải đang mở và đăng nhập).

```bash
mt5env\Scripts\python.exe scripts/xau_engine.py guard    # quyết định + ÁP VÀO MT5, chỉ in khi trạng thái đổi
mt5env\Scripts\python.exe scripts/xau_engine.py report   # dữ liệu cho báo cáo phân tích (cuối tuần in MARKET_CLOSED)
mt5env\Scripts\python.exe scripts/xau_engine.py show     # xem nhanh, không thay đổi gì
mt5env\Scripts\python.exe scripts/xau_engine.py account  # thông tin tài khoản
```

### Cơ chế bật/tắt SELL

Dùng cơ chế có sẵn của EA grid v5: có lệnh **SELL STOP giá 2222** thì EA **dừng mở SELL**.

- Hermes **tắt SELL** = đặt lệnh SELL STOP 2222 với magic `922222`, comment `HERMES SELL OFF`.
- Hermes **bật SELL** = xoá lệnh đó.
- Lệnh SELL STOP 2222 do anh Đông **tự đặt tay** (magic khác) → Hermes tôn trọng, không động vào.

> ⚠️ Chế độ `guard` **có đặt/xoá lệnh chờ thật** trên MT5. Không mở/đóng lệnh thị trường.

### Thứ tự quyết định (tắt SELL khi)

1. `sell_override.json` có `"mode": "OFF"` (tắt tay) / `"ON"` (bật tay). Có thể đặt `max_price` để ép trần.
2. Có tin USD mạnh: High ±30 phút, Medium ±15 phút.
3. Lỗ thả nổi SELL ≥ `MAX_SELL_DD_PCT` (15%) balance.
4. Điểm xu hướng tăng ≥ `SCORE_OFF` (6) – tính từ EMA/RSI/ADX/ATR trên D1/H4/H1/M30/M15.
5. Số lệnh SELL ≥ `MAX_SELL_ORDERS` (20).
6. Giá trên **trần SELL** (theo đỉnh hôm qua + ATR ngày; trễ `CAP_HYST` 2$ để không bật/tắt liên tục).

Điểm ≥ `SCORE_TIGHT` (4) → vẫn cho SELL nhưng hạ trần.

Nếu MT5 tắt Algo Trading → chỉ cảnh báo, không điều khiển được.

### File dữ liệu (không commit)

| File | Nội dung |
|---|---|
| `xau_state.json` | Trạng thái lần chạy trước (on/code/cap) |
| `sell_override.json` | Bật/tắt tay (tuỳ chọn) |
| `xau_journal.csv` | Nhật ký mỗi lần đổi quyết định |
| `xau_snapshots.csv` | Ảnh chụp thị trường mỗi lần report |
| `xau_report.off` | Có file này → job báo cáo giờ không chạy. Xoá để bật lại |

### Cấu hình (đầu `xau_engine.py`)

| Biến | Mặc định | Ý nghĩa |
|---|---|---|
| `TERMINAL` | `C:\Program Files\MetaTrader 5\terminal64.exe` | Đường dẫn MT5 |
| `SYMBOL` | `XAUUSDc` | Symbol |
| `BOT_MAGIC` | `123` | Magic EA grid |
| `SELL_STOP_PRICE` | `2222.0` | Giá lệnh chặn SELL (= input của EA) |
| `HERMES_MAGIC` | `922222` | Magic lệnh chặn do Hermes đặt |
| `NEWS_HIGH_MIN` / `NEWS_MED_MIN` | `30` / `15` | Phút tắt SELL quanh tin |
| `SCORE_OFF` / `SCORE_TIGHT` | `6` / `4` | Ngưỡng điểm xu hướng |
| `MAX_SELL_ORDERS` | `20` | Số lệnh SELL tối đa |
| `MAX_SELL_DD_PCT` | `15.0` | % lỗ thả nổi SELL |
| `CAP_HYST` | `2.0` | Trễ trần ($) |

## Cài đặt

Yêu cầu: Windows, MetaTrader 5 đang chạy + đăng nhập, Python 3.10+, Hermes Agent (gateway đang chạy để cron hoạt động).

```bash
# venv cho MT5 engine – xau_run.py tìm nó ở ../mt5env (cạnh thư mục scripts)
python -m venv mt5env
mt5env\Scripts\pip install -r requirements.txt

# test
python scripts/ff_calendar.py today
mt5env\Scripts\python.exe scripts/xau_engine.py show
```

### Triển khai vào Hermes

Hermes cron chạy script trong thư mục `scripts` của Hermes:
`C:\Users\DongNV\AppData\Local\hermes\scripts\` (venv ở `C:\Users\DongNV\AppData\Local\hermes\mt5env`).

Repo này là **bản sao để quản lý code**. Sửa xong thì chép các file `.py` trong `scripts/` sang thư mục trên (không chép file dữ liệu). Cấu hình job thật nằm ở `C:\Users\DongNV\AppData\Local\hermes\cron\jobs.json` – quản lý bằng `hermes cron` thay vì sửa tay.

Thay placeholder trong `cron/jobs.example.json` khi tạo lại job:

| Placeholder | Nhóm |
|---|---|
| `<KAIROS_LIVE_CHAT_ID>` | Kairos 1.0 – nhóm THẬT |
| `<ALERT_XAU_TEST_CHAT_ID>` | Alert XAU – nhóm test |

## Lưu ý an toàn

- Không commit `.env`, key, `cron/jobs.json` thật, ID nhóm Telegram (đã có trong `.gitignore`).
- Đổi gì về nội dung/định dạng tin → test ở nhóm **Alert XAU** trước khi bật cho Kairos.
- Tin nhắn không chèn link/URL.
