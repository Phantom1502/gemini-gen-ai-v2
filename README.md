# ICT Auto Trading Bot V2

Hệ thống giao dịch tự động theo lý thuyết **Inner Circle Trader (ICT)** với phân tích đa khung thời gian 3 giai đoạn.

---

## Kiến trúc Pipeline

```
MT5 Data (H1 raw)
     │
     ├─► Resample → Daily 20 nến
     │        └─► DailyBiasUtil.generate_daily_chart()
     │                  └─► [AI Stage 1] ICTAIAgent.analyze_daily()
     │                            └─► daily_bias: BULLISH / BEARISH / NEUTRAL
     │
     ├─► H1 Window (60 nến)
     │        └─► H1StructureUtil.generate_h1_chart()  ← nhận daily_bias
     │                  └─► [AI Stage 2] ICTAIAgent.analyze_h1()
     │                            └─► h1_trend, key_poi, h1_scenario
     │
     └─► M5 Window (120 nến)
              └─► M5EntryUtil.generate_m5_chart()  ← nhận h1_payload
                        └─► [AI Stage 3] ICTAIAgent.analyze_m5()
                                  └─► action: BUY / SELL / HOLD
                                           │
                                     MT5Util.open_position()
```

---

## Cấu trúc thư mục

```
ict_v2/
├── requirements.txt
├── src/
│   ├── config.py              ← Toàn bộ tham số cấu hình
│   ├── main.py                ← Entry point (live + dry-run)
│   ├── trader.py              ← Vòng lặp chính + pipeline gọi
│   ├── backtester.py          ← Backtest với CSV lịch sử
│   └── utils/
│       ├── mt5util.py         ← Kết nối MT5, lấy dữ liệu, đặt lệnh
│       ├── daily_bias_util.py ← Vẽ chart Daily + phân tích BSL/SSL
│       ├── h1_structure_util.py ← Vẽ chart H1 + FVG/OB/BOS
│       ├── m5_entry_util.py   ← Vẽ chart M5 + CHoCH/FVG entry
│       ├── ict_ai_agent.py    ← Gọi Gemini AI 3 giai đoạn
│       └── session_filter.py  ← Lọc phiên + Trailing SL
└── data/
    ├── charts/                ← Chart PNG được lưu tại đây
    ├── logs/                  ← CSV log giao dịch
    └── XAUUSD_H1.csv          ← (Tự chuẩn bị) Dữ liệu H1 cho backtest
```

---

## Cài đặt

```bash
pip install -r requirements.txt
```

> **Lưu ý:** `MetaTrader5` chỉ chạy trên Windows.

---

## Cấu hình

Mở `src/config.py` và điền:

```python
MT5_USERNAME  = 123456789
MT5_PASSWORD  = "password_của_bạn"
MT5_SERVER    = "Broker-Server"
MT5_SYMBOL    = "XAUUSD"

GEMINI_API_KEY = "AIza..."
GEMINI_MODEL   = "gemini-2.0-flash"   # hoặc "gemini-1.5-pro"

RISK_PERCENT  = 0.5    # 0.5% equity mỗi lệnh
RR_RATIO      = 2.5
```

---

## Chạy Bot

### Dry-run (kiểm tra không đặt lệnh)
```bash
cd src
python main.py --dry-run
```

### Live trading
```bash
cd src
python main.py
```

### Backtest
```bash
cd src
# Chỉ tạo chart (không tốn Gemini quota)
python backtester.py --no-ai --start 700 --end 2000 --step 4

# Full backtest với AI (tốn quota – dùng sau khi test chart OK)
python backtester.py --start 700 --end 1200 --step 8
```

---

## Các module ICT quan trọng

| Module | Chức năng |
|--------|-----------|
| `BSL/SSL` | Buy-Side / Sell-Side Liquidity (swing high/low) |
| `FVG` | Fair Value Gap – vùng imbalance 3 nến |
| `OB` | Order Block – nến cuối trước displacement |
| `BOS` | Break of Structure |
| `CHoCH` | Change of Character – đảo chiều cấu trúc |
| `DOL` | Draw on Liquidity – mục tiêu giá tiếp theo |
| `PDH/PDL` | Previous Day High/Low |

---

## Bộ lọc giao dịch

Bot chỉ vào lệnh khi:
- Đúng phiên giao dịch (London Open, NY Open – cấu hình trong `config.py`)
- Thứ 2 đến Thứ 6
- Không có lệnh đang mở

Trailing SL tự động kích hoạt khi lời >= 1R (cấu hình `TRAILING_TRIGGER_RR`).

---

## Log CSV

Mỗi ngày tạo 1 file `data/logs/trading_log_YYYYMMDD.csv` ghi đầy đủ:
- Kết quả 3 stage AI (Daily Bias, H1 Trend, M5 Action)
- Lý do entry/hold
- Ticket MT5, Lot, SL, Risk USD
- Kết quả thực tế (Profit, WIN/LOSE)
- Đường dẫn chart PNG
