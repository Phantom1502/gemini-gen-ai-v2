"""
config.py  (V2.1)
=================
Tập trung toàn bộ tham số cấu hình.
Chỉnh sửa file này để điều chỉnh bot mà không cần đụng vào code logic.
"""

import core_config

# ══════════════════════════════════════════════════════════════════
# MT5 CREDENTIALS
# ══════════════════════════════════════════════════════════════════
MT5_USERNAME    = core_config.MT5_USERNAME
MT5_PASSWORD    = core_config.MT5_PASSWORD
MT5_SERVER      = core_config.MT5_SERVER
MT5_SYMBOL      = core_config.MT5_SYMBOL

# ══════════════════════════════════════════════════════════════════
# AI / GEMINI
# ══════════════════════════════════════════════════════════════════
GEMINI_API_KEY  = core_config.GEMINI_API_KEY    
GEMINI_MODEL    = core_config.GEMINI_MODEL        # "gemini-2.0-flash" hoặc "gemini-1.5-pro"

# ══════════════════════════════════════════════════════════════════
# QUẢN LÝ VỐN
# ══════════════════════════════════════════════════════════════════
RISK_PERCENT    = 0.2
RR_RATIO        = 2.5
SPREADS         = 260
MAGIC_NUMBER    = 20261606

# ══════════════════════════════════════════════════════════════
# QUẢN LÝ LỆNH (TradeManager — partial close + BE + optional trailing)
# ══════════════════════════════════════════════════════════════
# Partial close 50% khi giá đạt half_target (midpoint entry→TP)
# Sau đó SL tự động dời về Breakeven + BE_BUFFER_POINTS

BE_BUFFER_POINTS       = 50    # points buffer sau entry để tránh bị quét ngay
TRAILING_ENABLED       = False # Tắt mặc định — partial close đã đủ
TRAILING_STEP_POINTS   = 150

# ══════════════════════════════════════════════════════════════════
# BỘ LỌC PHIÊN GIAO DỊCH (UTC+7 — Giờ Việt Nam local)
# ══════════════════════════════════════════════════════════════════
ALLOWED_SESSIONS = [
    {"name": "London Open",       "start": "14:00", "end": "18:00"},
    {"name": "NY Open",           "start": "19:30", "end": "23:30"},
    {"name": "London-NY Overlap", "start": "19:00", "end": "22:00"},
]
ALLOWED_WEEKDAYS        = [0, 1, 2, 3, 4]   # Thứ 2 → Thứ 6
FORCE_CLOSE_FRIDAY_TIME = "22:30"            # Giờ local (UTC+7)

# ══════════════════════════════════════════════════════════════════
# DỮ LIỆU / PHÂN TÍCH
# ══════════════════════════════════════════════════════════════════
H1_FETCH_COUNT  = 700    # ~29 ngày H1 để resample Daily đủ 22 nến
H1_CHART_WINDOW = 60
M5_CHART_WINDOW = 120
DAILY_CANDLES   = 20

# Daily Bias chỉ được query lại tại các giờ này (GMT 0):
# 0h, 4h, 8h, 12h — tức 4 lần/ngày, mỗi session giữ nguyên bias
DAILY_BIAS_REFRESH_HOURS_GMT = (0, 4, 8, 12)

# ══════════════════════════════════════════════════════════════════
# BACKTEST
# ══════════════════════════════════════════════════════════════════
BACKTEST_CSV_PATH  = "data/XAUUSD_H1.csv"
BACKTEST_START_IDX = 700
BACKTEST_END_IDX   = None
BACKTEST_STEP      = 1

# ══════════════════════════════════════════════════════════════════
# LOGGING & OUTPUT
# ══════════════════════════════════════════════════════════════════
LOG_FOLDER      = "data/logs"
CHART_FOLDER    = "data/charts"
REPORT_FOLDER   = "data/reports"   # ← MỚI: thư mục chứa PDF báo cáo
SAVE_ALL_CHARTS = True
