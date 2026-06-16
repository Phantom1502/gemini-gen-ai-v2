"""
config.py
=========
Tập trung toàn bộ tham số cấu hình V2.
Chỉnh sửa file này để điều chỉnh bot mà không cần đụng vào code logic.
"""

# ══════════════════════════════════════════════════════════════════
# MT5 CREDENTIALS
# ══════════════════════════════════════════════════════════════════
MT5_USERNAME    = 183787990       # Số tài khoản MT5
MT5_PASSWORD    = "Devuong1502@"
MT5_SERVER      = "Exness-MT5Real25"
MT5_SYMBOL      = "XAUUSDc"

# ══════════════════════════════════════════════════════════════════
# AI / GEMINI
# ══════════════════════════════════════════════════════════════════
GEMINI_API_KEY  = "AQ.Ab8RN6I35RE242D5J3L49jHzq_8cC7Feoff2-bHCvOaEuF1C7A"
GEMINI_MODEL    = "gemini-3.1-flash-lite"   # hoặc "gemini-1.5-pro" để chính xác hơn

# ══════════════════════════════════════════════════════════════════
# QUẢN LÝ VỐN
# ══════════════════════════════════════════════════════════════════
RISK_PERCENT    = 0.1      # % equity mỗi lệnh
RR_RATIO        = 2.5      # Risk:Reward mặc định
SPREADS         = 260      # Điểm buffer thêm vào SL (tránh bị quét bởi spread)
MAGIC_NUMBER    = 20261606 # ID định danh lệnh của bot

# ══════════════════════════════════════════════════════════════════
# TRAILING STOP LOSS
# ══════════════════════════════════════════════════════════════════
TRAILING_ENABLED       = True
TRAILING_TRIGGER_RR    = 1.0   # Kích hoạt trailing khi lời >= 1R
TRAILING_STEP_POINTS   = 150   # Dịch SL mỗi 150 points khi giá đi thuận

# ══════════════════════════════════════════════════════════════════
# BỘ LỌC PHIÊN GIAO DỊCH (UTC+7 - Giờ Việt Nam)
# ══════════════════════════════════════════════════════════════════
# Chỉ vào lệnh trong các khung giờ active để tránh low liquidity
ALLOWED_SESSIONS = [
    {"name": "Asian Open",    "start": "01:00", "end": "05:00"},
    {"name": "London Open",   "start": "07:00", "end": "10:00"},
    {"name": "NY Open",       "start": "12:00", "end": "15:00"},
]

# Ngày trong tuần được phép giao dịch (0=Thứ 2, 4=Thứ 6)
ALLOWED_WEEKDAYS = [0, 1, 2, 3, 4]  # Thứ 2 → Thứ 6

# Cắt lệnh cuối tuần: đóng lệnh vào Thứ 6 lúc 22:30 nếu vẫn đang mở
FORCE_CLOSE_FRIDAY_TIME = "22:30"

# ══════════════════════════════════════════════════════════════════
# DỮ LIỆU / PHÂN TÍCH
# ══════════════════════════════════════════════════════════════════
H1_FETCH_COUNT  = 700   # Số nến H1 để resample Daily (~29 ngày)
H1_CHART_WINDOW = 40    # Số nến H1 hiển thị trên chart
M5_CHART_WINDOW = 40   # Số nến M5 hiển thị trên chart

DAILY_CANDLES   = 20    # Số nến Daily để phân tích (luôn 20)

# ══════════════════════════════════════════════════════════════════
# BACKTEST (chỉ dùng khi chạy backtester.py)
# ══════════════════════════════════════════════════════════════════
BACKTEST_CSV_PATH  = "data/XAUUSD_H1.csv"   # File CSV H1 lịch sử
BACKTEST_START_IDX = 700                     # Index bắt đầu (đủ để resample Daily)
BACKTEST_END_IDX   = None                    # None = đến hết file
BACKTEST_STEP      = 1                       # Bước nhảy nến H1 (1 = mỗi nến)

# ══════════════════════════════════════════════════════════════════
# LOGGING
# ══════════════════════════════════════════════════════════════════
LOG_FOLDER      = "data/logs"
CHART_FOLDER    = "data/charts"
SAVE_ALL_CHARTS = True   # False = chỉ lưu chart khi có lệnh (tiết kiệm disk)
