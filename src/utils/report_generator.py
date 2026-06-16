"""
report_generator.py  (V2.1 - Hoàn chỉnh)
==========================================
Tạo báo cáo PDF giao dịch ICT V2 theo từng phiên phân tích.

Tích hợp vào pipeline sau mỗi lần bot phân tích (dù HOLD hay có lệnh).
Mỗi báo cáo gồm:
  1. Thông tin phiên: thời gian, symbol, bias trigger (0h/4h/8h/12h)
  2. Kết quả 3-stage AI (Daily Bias, H1 Context, M5 Entry)
  3. Thông tin lệnh (nếu có BUY/SELL)
  4. Chart PNG 3 khung thời gian (Daily, H1, M5)

Font: DejaVuSans (có sẵn trên mọi hệ điều hành, hỗ trợ Unicode đầy đủ)
Nếu muốn dùng font khác (Arial), đặt file arial.ttf cạnh script.
"""

import os
import datetime
from fpdf import FPDF
from typing import Dict, List, Optional


# ═══════════════════════════════════════════════════════════════
# FONT SETUP
# ═══════════════════════════════════════════════════════════════

def _find_unicode_font() -> Optional[str]:
    """
    Tìm file TTF hỗ trợ Unicode/tiếng Việt theo thứ tự ưu tiên:
    1. arial.ttf cạnh script (người dùng tự đặt)
    2. DejaVuSans từ matplotlib (luôn có khi cài matplotlib)
    3. None → dùng Helvetica (không hỗ trợ tiếng Việt, hiển thị dấu hỏi)
    """
    # 1. arial.ttf cạnh file report_generator.py
    local = os.path.join(os.path.dirname(__file__), "arial.ttf")
    if os.path.exists(local):
        return local

    # 2. DejaVuSans từ matplotlib
    try:
        import matplotlib
        mpl_data = matplotlib.get_data_path()
        candidate = os.path.join(mpl_data, "fonts", "ttf", "DejaVuSans.ttf")
        if os.path.exists(candidate):
            return candidate
    except Exception:
        pass

    # 3. Tìm trong các đường dẫn hệ thống phổ biến
    system_paths = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",          # Linux
        "/System/Library/Fonts/Supplemental/Arial.ttf",             # macOS
        "C:\\Windows\\Fonts\\arial.ttf",                            # Windows
    ]
    for p in system_paths:
        if os.path.exists(p):
            return p

    return None


# ═══════════════════════════════════════════════════════════════
# PDF CLASS
# ═══════════════════════════════════════════════════════════════

class ICTReportPDF(FPDF):
    """
    PDF báo cáo giao dịch ICT V2.
    Kế thừa FPDF, override header/footer.
    """

    def __init__(self, session_time: str, symbol: str):
        super().__init__()
        self.session_time = session_time
        self.symbol       = symbol
        self._font_name   = "UniFont"

        # Đăng ký font Unicode
        font_path = _find_unicode_font()
        if font_path:
            self.add_font(self._font_name, "",  font_path, uni=True)
            self.add_font(self._font_name, "B", font_path, uni=True)
            self.add_font(self._font_name, "I", font_path, uni=True)
            print(f"✅ [PDF] Dùng font: {os.path.basename(font_path)}")
        else:
            # Fallback: Helvetica không hỗ trợ tiếng Việt
            self._font_name = "Helvetica"
            print("⚠️  [PDF] Không tìm thấy font Unicode. Tiếng Việt có thể hiển thị sai.")

    def header(self):
        self.set_font(self._font_name, "B", 15)
        self.set_text_color(38, 166, 154)   # màu teal ICT
        self.cell(0, 10, "BÁO CÁO PHÂN TÍCH ICT V2 — ĐA KHUNG THỜI GIAN", ln=True, align="C")

        self.set_font(self._font_name, "I", 9)
        self.set_text_color(132, 142, 156)
        self.cell(0, 6,
                  f"Symbol: {self.symbol}  |  Phiên: {self.session_time}  |  "
                  f"Pipeline: Daily → H1 → M5",
                  ln=True, align="C")

        self.set_draw_color(42, 46, 57)
        self.set_line_width(0.5)
        self.line(10, self.get_y() + 1, 200, self.get_y() + 1)
        self.ln(5)

    def footer(self):
        self.set_y(-13)
        self.set_font(self._font_name, "I", 7)
        self.set_text_color(132, 142, 156)
        self.cell(0, 10,
                  f"ICT Auto Trading Bot V2  |  Trang {self.page_no()}/{{nb}}  |  "
                  f"Tạo lúc {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                  align="C")

    # ── Tiện ích vẽ ──────────────────────────────

    def section_title(self, title: str):
        self.set_font(self._font_name, "B", 11)
        self.set_fill_color(19, 23, 34)
        self.set_text_color(251, 192, 45)   # vàng ICT
        self.cell(0, 8, f"  {title}", ln=True, fill=True)
        self.ln(2)

    def kv_row(self, key: str, value: str, indent: int = 5):
        """In một dòng key: value"""
        self.set_x(10 + indent)
        self.set_font(self._font_name, "B", 9)
        self.set_text_color(200, 200, 200)
        key_w = 55
        self.cell(key_w, 6, f"{key}:", ln=False)
        self.set_font(self._font_name, "", 9)
        self.set_text_color(255, 255, 255)
        # multi_cell để xuống dòng nếu value dài
        self.multi_cell(0, 6, str(value) if value else "—")

    def colored_badge(self, label: str, value: str):
        """Badge màu động cho Bias / Action / Confidence."""
        colors = {
            "BULLISH": (38, 166, 154), "BUY": (38, 166, 154),
            "BEARISH": (239, 83, 80),  "SELL": (239, 83, 80),
            "NEUTRAL": (168, 168, 168),"HOLD": (168, 168, 168),
            "HIGH":    (38, 166, 154), "MEDIUM": (251, 192, 45),
            "LOW":     (239, 83, 80),
        }
        r, g, b = colors.get(value.upper(), (200, 200, 200))
        self.set_font(self._font_name, "B", 9)
        self.set_text_color(132, 142, 156)
        self.set_x(15)
        self.cell(40, 7, f"{label}:", ln=False)
        self.set_text_color(r, g, b)
        self.cell(0, 7, value, ln=True)

    def divider(self):
        self.set_draw_color(42, 46, 57)
        self.line(10, self.get_y(), 200, self.get_y())
        self.ln(3)

    def insert_chart(self, img_path: str, caption: str):
        """Chèn ảnh chart vào trang mới nếu cần."""
        if not img_path or not os.path.exists(img_path):
            self.set_font(self._font_name, "I", 8)
            self.set_text_color(239, 83, 80)
            self.cell(0, 8, f"  ⚠ Không tìm thấy: {img_path}", ln=True)
            return

        # Kiểm tra còn đủ chỗ không (ảnh cao ~80mm)
        if self.get_y() > 210:
            self.add_page()

        self.set_font(self._font_name, "I", 8)
        self.set_text_color(132, 142, 156)
        self.set_x(10)
        self.cell(0, 6, f"  📊 {caption}", ln=True)
        self.image(img_path, x=10, w=188)
        self.ln(4)


# ═══════════════════════════════════════════════════════════════
# HÀM CHÍNH
# ═══════════════════════════════════════════════════════════════

def generate_session_report(
    output_path: str,
    symbol: str,
    session_time: str,           # VD: "2026-06-16 08:00 GMT"
    bias_trigger_hour: int,      # 0, 4, 8, 12
    daily_result:  Optional[Dict],
    h1_result:     Optional[Dict],
    m5_result:     Optional[Dict],
    daily_payload: Optional[Dict],
    h1_payload:    Optional[Dict],
    m5_payload:    Optional[Dict],
    daily_img:     str = "",
    h1_img:        str = "",
    m5_img:        str = "",
    trade_info:    Optional[Dict] = None,   # thông tin lệnh nếu có
) -> str:
    """
    Tạo file PDF báo cáo cho một phiên phân tích.

    Parameters
    ----------
    output_path       : đường dẫn file PDF đầu ra
    symbol            : ký hiệu tài sản (VD: XAUUSD)
    session_time      : chuỗi thời gian phiên (hiển thị trên header)
    bias_trigger_hour : giờ trigger Daily Bias (0 / 4 / 8 / 12)
    daily/h1/m5_result: dict kết quả AI từng stage (có thể None)
    daily/h1/m5_payload: dict dữ liệu số từng stage
    daily/h1/m5_img   : đường dẫn ảnh chart
    trade_info        : dict thông tin lệnh {action, ticket, lot, sl_pts, risk_usd, tp}

    Returns
    -------
    output_path (str)
    """
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

    pdf = ICTReportPDF(session_time=session_time, symbol=symbol)
    pdf.alias_nb_pages()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.set_fill_color(19, 23, 34)
    pdf.add_page()

    fn = pdf._font_name   # font đã đăng ký

    # ══════════════════════════════════════════════
    # SECTION 1: THÔNG TIN PHIÊN
    # ══════════════════════════════════════════════
    pdf.section_title("1. THÔNG TIN PHIÊN PHÂN TÍCH")

    pdf.kv_row("Symbol",        symbol)
    pdf.kv_row("Thời gian",     session_time)
    pdf.kv_row("Bias trigger",  f"{bias_trigger_hour:02d}:00 GMT (cập nhật mỗi 4 giờ)")
    pdf.kv_row("Pipeline",      "Daily Bias → H1 Structure → M5 Entry (ICT Model 2022)")
    pdf.ln(3)
    pdf.divider()

    # ══════════════════════════════════════════════
    # SECTION 2: DAILY BIAS (Stage 1)
    # ══════════════════════════════════════════════
    pdf.section_title("2. STAGE 1 — DAILY BIAS")

    if daily_result:
        pdf.colored_badge("Daily Bias",  daily_result.get("daily_bias", "—"))
        pdf.colored_badge("Confidence",  daily_result.get("confidence_score", "—"))
        pdf.kv_row("Market State",       daily_result.get("current_market_state", "—"))
        pdf.kv_row("Draw on Liquidity",  daily_result.get("draw_on_liquidity", "—"))

        ltf = daily_result.get("ltf_execution_context") or {}
        pdf.kv_row("LTF Scenario",       ltf.get("primary_scenario", "—"))
        pdf.kv_row("Invalidation",       ltf.get("invalidation_level", "—"))
    else:
        pdf.set_font(fn, "I", 9)
        pdf.set_text_color(239, 83, 80)
        pdf.cell(0, 7, "  ✗ Stage 1 không có kết quả.", ln=True)

    if daily_payload:
        anchors = daily_payload.get("yesterday_anchors", {})
        mctx    = daily_payload.get("market_context", {})
        metrics = daily_payload.get("mathematical_metrics", {})
        pdf.ln(2)
        pdf.set_font(fn, "B", 8); pdf.set_text_color(132, 142, 156)
        pdf.cell(0, 5, "  — Dữ liệu số Daily —", ln=True)
        pdf.kv_row("PDH / PDL",
                   f"{anchors.get('PDH', '—')} / {anchors.get('PDL', '—')}")
        pdf.kv_row("Yesterday Close",   str(anchors.get("yesterday_close", "—")))
        pdf.kv_row("Equilibrium",       str(metrics.get("equilibrium", "—")))
        pdf.kv_row("Price Zone",        mctx.get("price_zone_vs_equilibrium", "—"))
        liq = daily_payload.get("liquidity_map", {})
        active = liq.get("active_liquidity", [])
        if active:
            pdf.kv_row("Active Liquidity",
                       "  |  ".join(f"{l['type']} {l['price']}" for l in active[:4]))

    pdf.ln(3)
    pdf.divider()

    # ══════════════════════════════════════════════
    # SECTION 3: H1 STRUCTURE (Stage 2)
    # ══════════════════════════════════════════════
    pdf.section_title("3. STAGE 2 — H1 STRUCTURE")

    if h1_result:
        pdf.colored_badge("H1 Trend",    h1_result.get("h1_trend", "—"))
        pdf.colored_badge("Confidence",  h1_result.get("confidence_score", "—"))
        pdf.kv_row("Key POI",            h1_result.get("key_poi", "—"))
        pdf.kv_row("H1 Scenario",        h1_result.get("h1_scenario", "—"))
    else:
        pdf.set_font(fn, "I", 9); pdf.set_text_color(239, 83, 80)
        pdf.cell(0, 7, "  ✗ Stage 2 không có kết quả.", ln=True)

    if h1_payload:
        pdf.ln(2)
        pdf.set_font(fn, "B", 8); pdf.set_text_color(132, 142, 156)
        pdf.cell(0, 5, "  — Dữ liệu số H1 —", ln=True)
        pdf.kv_row("Giá hiện tại",    str(h1_payload.get("current_price", "—")))
        pdf.kv_row("EMA 50",          str(h1_payload.get("ema_50", "—")))
        pdf.kv_row("Price vs EMA50",  h1_payload.get("price_vs_ema50", "—"))
        pdf.kv_row("FVG active",      str(h1_payload.get("active_fvg_count", "—")))
        pdf.kv_row("OB active",       str(h1_payload.get("active_ob_count", "—")))
        bos = h1_payload.get("last_bos")
        if bos:
            pdf.kv_row("Last BOS",
                       f"{bos.get('type','?')} tại {bos.get('price','?')} "
                       f"(nến #{bos.get('candle_idx','?')})")

    pdf.ln(3)
    pdf.divider()

    # ══════════════════════════════════════════════
    # SECTION 4: M5 ENTRY (Stage 3)
    # ══════════════════════════════════════════════
    pdf.section_title("4. STAGE 3 — M5 ENTRY")

    if m5_result:
        pdf.colored_badge("Action",      m5_result.get("action", "—"))
        pdf.colored_badge("Confidence",  m5_result.get("confidence_score", "—"))
        pdf.kv_row("Entry Zone",         m5_result.get("entry_zone", "—"))
        pdf.kv_row("SL Reference",       m5_result.get("sl_reference", "—"))
        pdf.kv_row("TP Reference",       m5_result.get("tp_reference", "—"))
        pdf.kv_row("Geometry Reason",    m5_result.get("geometry_reason", "—"))
    else:
        pdf.set_font(fn, "I", 9); pdf.set_text_color(239, 83, 80)
        pdf.cell(0, 7, "  ✗ Stage 3 không có kết quả.", ln=True)

    if m5_payload:
        pdf.ln(2)
        pdf.set_font(fn, "B", 8); pdf.set_text_color(132, 142, 156)
        pdf.cell(0, 5, "  — Dữ liệu số M5 —", ln=True)
        pdf.kv_row("Giá hiện tại", str(m5_payload.get("current_price", "—")))
        pdf.kv_row("EMA 21",       str(m5_payload.get("ema_21", "—")))
        pdf.kv_row("Price vs EMA", m5_payload.get("price_vs_ema21", "—"))
        choch = m5_payload.get("choch")
        if choch:
            pdf.kv_row("CHoCH",
                       f"{choch.get('type','?')} tại {choch.get('broken_level','?')} "
                       f"({choch.get('candles_ago','?')} nến trước)")
        fvg = m5_payload.get("entry_fvg")
        if fvg:
            pdf.kv_row("FVG Entry",
                       f"{fvg.get('type','?')} [{fvg.get('bottom','?')} – {fvg.get('top','?')}]"
                       f"  mid={fvg.get('mid','?')}")

    pdf.ln(3)
    pdf.divider()

    # ══════════════════════════════════════════════
    # SECTION 5: THÔNG TIN LỆNH (nếu có)
    # ══════════════════════════════════════════════
    if trade_info:
        pdf.section_title("5. THÔNG TIN LỆNH PHÁT SINH")
        action = trade_info.get("action", "HOLD")
        pdf.colored_badge("Action",   action)
        pdf.kv_row("Ticket MT5",  str(trade_info.get("ticket", "—")))
        pdf.kv_row("Lot size",    str(trade_info.get("lot", "—")))
        pdf.kv_row("SL (points)", str(trade_info.get("sl_pts", "—")))
        pdf.kv_row("Risk USD",    str(trade_info.get("risk_usd", "—")))
        pdf.kv_row("TP Reference",str(trade_info.get("tp", "—")))
        result_val = str(trade_info.get("result", "PENDING"))
        profit_val = str(trade_info.get("profit", "—"))
        pdf.kv_row("Kết quả",    f"{result_val}  |  P&L: {profit_val}")
        pdf.ln(3)
        pdf.divider()
    else:
        pdf.section_title("5. LỆNH")
        pdf.set_font(fn, "I", 9); pdf.set_text_color(168, 168, 168)
        pdf.cell(0, 7, "  Phiên này HOLD — không phát sinh lệnh.", ln=True)
        pdf.ln(3)
        pdf.divider()

    # ══════════════════════════════════════════════
    # SECTION 6: CHART PNG
    # ══════════════════════════════════════════════
    chart_section = 6 if trade_info else 6
    pdf.section_title(f"{chart_section}. BIỂU ĐỒ KỸ THUẬT ĐA KHUNG THỜI GIAN")

    chart_data = [
        (daily_img, "Daily — BSL/SSL + PDH/PDL + Equilibrium"),
        (h1_img,    "H1 — FVG / Order Block / EMA 50"),
        (m5_img,    "M5 — CHoCH / FVG Entry / EMA 21"),
    ]

    for img_path, caption in chart_data:
        pdf.insert_chart(img_path, caption)

    # ── Xuất file ──────────────────────────────────
    pdf.output(output_path)
    print(f"✅ [PDF] Báo cáo xuất thành công → {output_path}")
    return output_path


# ═══════════════════════════════════════════════════════════════
# HELPER: build output path chuẩn
# ═══════════════════════════════════════════════════════════════

def build_report_path(
    report_folder: str,
    symbol: str,
    trigger_hour: int,
    dt: Optional[datetime.datetime] = None
) -> str:
    """
    Tạo đường dẫn PDF theo quy ước:
    <report_folder>/<symbol>_<YYYYMMDD>_H<trigger_hour>.pdf
    Ví dụ: data/reports/XAUUSD_20260616_H08.pdf
    """
    dt = dt or datetime.datetime.utcnow()
    os.makedirs(report_folder, exist_ok=True)
    filename = f"{symbol}_{dt.strftime('%Y%m%d')}_H{trigger_hour:02d}.pdf"
    return os.path.join(report_folder, filename)
