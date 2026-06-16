# ICT Auto Trading Bot V2

Hệ thống giao dịch tự động theo lý thuyết **Inner Circle Trader (ICT)** với phân tích đa khung thời gian 3 giai đoạn, tích hợp AI Vision (Gemini) và tự động quản lý vốn.

---

## Tổng quan kiến trúc

```
MT5 Data (H1 raw, start_pos=0)
     │
     ├─► Resample → Daily (offset 20h GMT, khớp chart OANDA)
     │        └─► DailyBiasUtil.generate_daily_chart()
     │                  └─► [AI Stage 1] ICTAIAgent.analyze_daily()
     │                            └─► daily_bias: BULLISH / BEARISH / NEUTRAL
     │                            └─► 🔒 Cache 4h: chỉ refresh tại 0h/4h/8h/12h GMT
     │
     ├─► H1 Window (60 nến, kể cả nến đang chạy)
     │        └─► H1StructureUtil.generate_h1_chart()  ← nhận daily_bias
     │                  └─► [AI Stage 2] ICTAIAgent.analyze_h1()
     │                            └─► h1_trend, key_poi, h1_scenario
     │                            └─► 🔒 Cache 1h: chỉ refresh khi giờ UTC thay đổi
     │
     └─► M5 Window (120 nến, kể cả nến đang chạy)
              └─► M5EntryUtil.generate_m5_chart()  ← nhận h1_payload
                        └─► [AI Stage 3] ICTAIAgent.analyze_m5()
                                  └─► action: BUY / SELL / HOLD
                                           │
                                     MT5Util.open_position()
                                           │
                                     📄 generate_session_report() → PDF
```

---

## Tính năng chính

### Pipeline phân tích ICT 3 giai đoạn
- **Stage 1 — Daily Bias**: Xác định xu hướng ngày (BULLISH / BEARISH / NEUTRAL) dựa trên BSL/SSL, PDH/PDL, Equilibrium và vùng Premium/Discount. AI Vision đọc chart và metadata số để ra quyết định.
- **Stage 2 — H1 Structure**: Xác nhận xu hướng H1 thuận với Daily Bias, tìm POI (FVG / Order Block) làm vùng pullback, xây dựng kịch bản cụ thể cho M5.
- **Stage 3 — M5 Entry**: Phát hiện CHoCH M5 xác nhận hướng, tìm FVG M5 làm entry zone, quyết định BUY / SELL / HOLD theo Model 2022.

### Hệ thống cache thông minh
- **Daily Bias** chỉ được query AI tại các mốc **0h / 4h / 8h / 12h GMT**. Trong suốt 4 giờ giữa các mốc, bias được giữ nguyên từ cache → nhất quán trong phiên, tiết kiệm Gemini API quota.
- **H1 Result** chỉ refresh khi **giờ UTC thay đổi** (tức mỗi nến H1 mới). Mọi nến M5 trong cùng một giờ dùng chung kết quả H1 → giảm ~12x số lần gọi AI Stage 2.
- Khi Daily Bias được cập nhật mới → H1 cache bị **invalidate tự động** để đảm bảo H1 phân tích lại theo bias mới.

### Resample Daily khớp OANDA
- Chart Daily được resample từ H1 với `offset='20h' GMT` → mỗi ngày bắt đầu lúc **20:00 GMT Chủ nhật** và kết thúc **19:59 GMT** ngày hôm sau, khớp hoàn toàn với broker OANDA.
- Tất cả `copy_rates_from_pos` dùng `start_pos=0` để lấy cả nến đang chạy, giúp phân tích real-time chính xác hơn.

### Báo cáo PDF tự động
- Sau mỗi lần pipeline chạy (dù HOLD hay có lệnh), bot tạo **file PDF báo cáo** tại `data/reports/`.
- PDF gồm: thông tin phiên, kết quả AI 3 stage, dữ liệu số (PDH/PDL, EMA, FVG, BOS...), thông tin lệnh (nếu có), và **3 chart PNG** đính kèm (Daily / H1 / M5).
- Tên file theo quy ước: `XAUUSD_20260616_H08_1430.pdf` (symbol + ngày + trigger hour + giờ phút).
- Tự động tìm font Unicode (DejaVuSans / Arial) để hiển thị tiếng Việt đúng.

### Quản lý vốn & rủi ro
- Tính lot tự động theo % equity và SL thực tế (tính bằng điểm).
- Nếu lệnh trước lời lớn (> 2× default risk), risk lệnh tiếp theo = profit trước / 2 (compound có kiểm soát).
- Stop Loss đặt dưới low (BUY) hoặc trên high (SELL) của nến M5 vừa đóng, cộng thêm buffer spread.

### Trailing Stop Loss
- Tự động kích hoạt khi lợi nhuận ≥ `TRAILING_TRIGGER_RR × initial_risk`.
- Dịch SL từng bước `TRAILING_STEP_POINTS` khi giá tiến thuận chiều.
- Quản lý đồng thời nhiều lệnh qua `TrailingStopManager`.

### Bộ lọc phiên & bảo vệ cuối tuần
- Chỉ vào lệnh trong phiên London Open và NY Open (cấu hình trong `config.py`).
- Force-close tất cả lệnh vào **Thứ 6 lúc 22:30** (giờ local UTC+7) để tránh rủi ro qua cuối tuần.

---

## Cấu trúc thư mục

```
ict_v2/
├── config.py                  ← Toàn bộ tham số (credentials, risk, session, path)
├── requirements.txt
├── src/
│   ├── main.py                ← Entry point (live + dry-run)
│   ├── trader.py              ← Vòng lặp chính, pipeline cache, log, report
│   ├── backtester.py          ← Backtest với CSV H1 lịch sử
│   └── utils/
│       ├── mt5util.py         ← Kết nối MT5, resample OANDA, đặt lệnh
│       ├── daily_bias_util.py ← Chart Daily: BSL/SSL/PDH/PDL/EQ
│       ├── h1_structure_util.py ← Chart H1: FVG/OB/BOS/EMA50
│       ├── m5_entry_util.py   ← Chart M5: CHoCH/FVG/EMA21
│       ├── ict_ai_agent.py    ← Gemini AI 3 giai đoạn (schema Pydantic)
│       ├── report_generator.py← Xuất PDF báo cáo phiên giao dịch
│       ├── session_filter.py  ← Lọc phiên (London/NY) + Trailing SL
│       └── chartanalysisutil.py ← Bob Volman structural barrier (legacy)
└── data/
    ├── charts/                ← Chart PNG (Daily/H1/M5) theo phiên
    ├── logs/                  ← CSV log giao dịch theo ngày
    ├── reports/               ← PDF báo cáo phiên phân tích
    └── XAUUSD_H1.csv          ← (Tự chuẩn bị) Dữ liệu H1 cho backtest
```

---

## Cài đặt

```bash
pip install -r requirements.txt
```

> **Lưu ý:** `MetaTrader5` chỉ chạy trên **Windows**.

Để hỗ trợ tiếng Việt trong PDF, đặt file `arial.ttf` (từ `C:\Windows\Fonts\`) vào thư mục `src/utils/`. Nếu không có, bot tự dùng DejaVuSans từ matplotlib.

---

## Cấu hình

Mở `config.py` và điền thông tin thực tế:

```python
# MT5
MT5_USERNAME  = 123456789
MT5_PASSWORD  = "password_của_bạn"
MT5_SERVER    = "Broker-Server"
MT5_SYMBOL    = "XAUUSD"

# Gemini AI
GEMINI_API_KEY = "AIza..."
GEMINI_MODEL   = "gemini-2.0-flash"

# Quản lý vốn
RISK_PERCENT  = 0.5    # 0.5% equity mỗi lệnh
RR_RATIO      = 2.5

# Daily Bias chỉ refresh tại các giờ này (GMT)
DAILY_BIAS_REFRESH_HOURS_GMT = (0, 4, 8, 12)

# Thư mục output
CHART_FOLDER  = "data/charts"
LOG_FOLDER    = "data/logs"
REPORT_FOLDER = "data/reports"
```

---

## Chạy Bot

### Dry-run — kiểm tra pipeline không đặt lệnh thật
```bash
cd src
python main.py --dry-run
```
Chạy đúng 1 vòng Daily → H1 → M5, in kết quả AI ra màn hình, tạo chart PNG và PDF report để kiểm tra.

### Live trading
```bash
cd src
python main.py
```

### Backtest với CSV lịch sử
```bash
cd src
# Chỉ tạo chart, không tốn Gemini quota
python backtester.py --no-ai --start 700 --end 2000 --step 4

# Full backtest với AI (step 4 = mỗi 4 nến H1 = 4 giờ)
python backtester.py --start 700 --end 1200 --step 8
```

---

## Các khái niệm ICT được implement

| Khái niệm | Module | Mô tả |
|-----------|--------|-------|
| `BSL / SSL` | `daily_bias_util` | Buy-Side / Sell-Side Liquidity — swing high/low theo vòng đời (active → swept → broken) |
| `PDH / PDL` | `daily_bias_util` | Previous Day High/Low — mốc tham chiếu quan trọng từ nến ngày hôm qua |
| `Equilibrium` | `daily_bias_util` | Trung điểm biên độ ngày — phân chia vùng Premium (trên) và Discount (dưới) |
| `FVG` | `h1_structure_util`, `m5_entry_util` | Fair Value Gap — 3-candle imbalance, theo dõi trạng thái filled/unfilled |
| `OB` | `h1_structure_util` | Order Block — nến cuối trước displacement, theo dõi trạng thái mitigated |
| `BOS` | `h1_structure_util` | Break of Structure — giá đóng cửa phá qua swing high/low trước |
| `CHoCH` | `m5_entry_util` | Change of Character — BOS ngược chiều xác nhận đảo chiều cấu trúc M5 |
| `DOL` | `ict_ai_agent` | Draw on Liquidity — mục tiêu giá tiếp theo mà AI xác định từ liquidity map |
| `EMA 50` | `h1_structure_util` | Tham chiếu xu hướng H1 |
| `EMA 21` | `m5_entry_util` | Tham chiếu xu hướng M5, lọc overextended |

---

## Logic cache Daily Bias

```
Giờ UTC hiện tại    Trigger Hour    Hành động
─────────────────   ─────────────   ──────────────────────────────────────
00:00 – 03:59       H00             Query AI lần đầu trong ngày
04:00 – 07:59       H04             Query AI → có thể đổi bias nếu thị trường thay đổi
08:00 – 11:59       H08             Query AI → cập nhật trước phiên London
12:00 – 23:59       H12             Query AI → giữ đến hết ngày
                                    (13h–23h59 dùng lại cache H12)
```

Khi Daily Bias được cập nhật → H1 cache bị xóa → Stage 2 chạy lại ngay lập tức trong nến M5 kế tiếp.

---

## Cấu trúc file báo cáo PDF

Mỗi phiên M5 có lệnh hoặc HOLD đều tạo 1 file PDF:

```
data/reports/XAUUSD_20260616_H08_1435.pdf
                              ^^^  ^^^^
                              │    └── Giờ:phút GMT khi pipeline chạy
                              └─────── Trigger hour của Daily Bias
```

Nội dung PDF:
1. Thông tin phiên (symbol, thời gian, trigger hour)
2. Stage 1 — Daily Bias (bias, confidence, DOL, LTF scenario, dữ liệu số)
3. Stage 2 — H1 Structure (trend, POI, scenario, FVG/OB count, BOS)
4. Stage 3 — M5 Entry (action, entry zone, SL/TP, CHoCH, FVG entry)
5. Thông tin lệnh — ticket, lot, SL points, risk USD, kết quả (nếu có)
6. Chart PNG — Daily / H1 / M5 đính kèm trực tiếp

---

## Log CSV hàng ngày

File `data/logs/trading_log_YYYYMMDD.csv` ghi đầy đủ mỗi phiên:

| Cột | Mô tả |
|-----|-------|
| `Open/Close_Timestamp` | Thời gian mở/đóng lệnh |
| `Daily_Trigger_H` | Trigger hour của Daily Bias (0/4/8/12) |
| `Daily_Bias` | BULLISH / BEARISH / NEUTRAL |
| `Daily_DOL` | Draw on Liquidity (mục tiêu giá) |
| `H1_Trend` | UPTREND / DOWNTREND / RANGING |
| `H1_POI` | Vùng POI H1 AI xác định |
| `M5_Action` | BUY / SELL / HOLD |
| `M5_Geometry_Reason` | Lý do entry của AI |
| `SL_Points`, `Risk_USD`, `Lot` | Thông số lệnh |
| `MT5_Ticket` | Ticket MT5 |
| `Real_Profit_USD`, `Trade_Result` | Kết quả thực tế |
| `Daily/H1/M5_Chart` | Đường dẫn file PNG |

---

## Bộ lọc giao dịch — điều kiện để vào lệnh

Bot chỉ thực hiện lệnh khi **tất cả** điều kiện sau thỏa mãn:

1. Đúng ngày trong tuần (Thứ 2 → Thứ 6)
2. Đúng phiên giao dịch (London Open hoặc NY Open)
3. Không phải Thứ 6 sau 22:30 local
4. Không có lệnh đang mở (cùng symbol + magic number)
5. Pipeline 3 stage đều thành công và Stage 3 ra action BUY hoặc SELL