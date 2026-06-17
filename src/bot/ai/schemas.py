"""
bot/ai/schemas.py
=================
Pydantic schemas cho 3 stage ICT AI pipeline.
"""

from pydantic import BaseModel, Field
from typing import Optional

class LiquidityTarget(BaseModel):
    """Mục tiêu thanh khoản mà giá đang hướng đến."""
    label: str  = Field(description="Tên mục tiêu. Ví dụ: 'BSL tại 2345.50' hoặc 'SSL tại 2310.00'")
    price: str  = Field(description="Mức giá cụ thể (string để linh hoạt format).")
    reason: str = Field(description="Tại sao đây là DOL — ngắn gọn (tiếng Việt).")


class DailyBiasContext(BaseModel):
    """
    Output của Stage 1 (Daily). Là 'hợp đồng' truyền xuống Stage 2 (H1).
    H1 đọc context này để biết bức tranh lớn, sau đó xây kịch bản riêng.
    """
    bias: str = Field(
        description="Hướng thiên vị ngày: 'BULLISH', 'BEARISH', hoặc 'NEUTRAL'."
    )
    market_state: str = Field(
        description=(
            "Mô tả trạng thái thị trường Daily hiện tại bằng tiếng Việt. "
            "Ví dụ: 'Giá đang ở vùng Discount sau khi quét SSL tại 2310, "
            "nến hôm qua đóng cửa tăng mạnh vượt EQ.'"
        )
    )
    draw_on_liquidity: LiquidityTarget = Field(
        description="Mục tiêu thanh khoản tiếp theo mà giá Daily đang hướng đến."
    )
    htf_invalidation: str = Field(
        description=(
            "Mức giá / điều kiện Daily nếu bị vi phạm thì bias sai hoàn toàn. "
            "Ví dụ: 'Nếu giá đóng cửa Daily dưới 2305.00 thì bias Bullish vô hiệu.'"
        )
    )
    ltf_guidance: str = Field(
        description=(
            "Hướng dẫn ngắn gọn cho H1 — LTF nên tìm gì và tránh gì. "
            "Không đề cập entry cụ thể, chỉ định hướng tổng quan. "
            "Ví dụ: 'H1 nên tìm pullback về FVG hoặc OB Bullish để BUY, "
            "tránh SELL khi chưa có dấu hiệu đảo chiều cấu trúc.'"
        )
    )
    confidence: str = Field(description="'HIGH', 'MEDIUM', hoặc 'LOW'.")


# ── Output Stage 2 ──────────────────────────────────────────────

class H1EntryZone(BaseModel):
    """Vùng giá H1 mà M5 sẽ tìm entry bên trong."""
    zone_type: str  = Field(
        description="Loại POI: 'FVG_BULL', 'FVG_BEAR', 'OB_BULL', 'OB_BEAR', 'MITIGATION_BLOCK', v.v."
    )
    price_top: str  = Field(description="Biên trên của vùng (giá).")
    price_bot: str  = Field(description="Biên dưới của vùng (giá).")
    description: str = Field(
        description="Mô tả ngắn về vùng này và tại sao nó có giá trị (tiếng Việt)."
    )


class H1TradingContext(BaseModel):
    """
    Output của Stage 2 (H1). Là 'lệnh tác chiến' truyền xuống Stage 3 (M5).
    M5 đọc context này để biết: cần làm gì, ở đâu, mục tiêu là gì.
    M5 KHÔNG biết gì về Daily — chỉ làm theo H1TradingContext.
    """
    direction: str = Field(
        description="Hướng giao dịch H1 đề xuất: 'BUY', 'SELL', hoặc 'WAIT'."
    )
    h1_structure: str = Field(
        description=(
            "Mô tả cấu trúc H1 hiện tại bằng tiếng Việt. "
            "Ví dụ: 'H1 đang trong Bullish Swing — BOS tăng gần nhất tại 2330, "
            "giá đang pullback về FVG H1 [2318–2322].'"
        )
    )
    entry_zone: H1EntryZone = Field(
        description="Vùng cụ thể trên H1 mà M5 sẽ canh entry bên trong."
    )
    target: str = Field(
        description=(
            "Mục tiêu giá H1 (TP reference). "
            "Ví dụ: 'BSL tại 2345 — đỉnh swing H1 gần nhất chưa bị chạm.'"
        )
    )
    invalidation: str = Field(
        description=(
            "Điều kiện H1 làm mất hiệu lực kịch bản này. "
            "Ví dụ: 'Nếu H1 đóng cửa dưới 2310 (phá vỡ OB Bullish) thì kịch bản BUY hủy.'"
        )
    )
    scenario_note: str = Field(
        description=(
            "Ghi chú kịch bản — những điều M5 cần biết thêm ngoài entry zone. "
            "Ví dụ: 'Chú ý vùng PDH 2340 có thể là kháng cự tạm — M5 entry sớm "
            "có thể chốt một phần tại đây.'"
        )
    )
    confidence: str = Field(description="'HIGH', 'MEDIUM', hoặc 'LOW'.")


# ── Output Stage 3 ──────────────────────────────────────────────

class M5EntryResult(BaseModel):
    """
    Output của Stage 3 (M5). Quyết định cuối cùng để đặt lệnh.
    Được xây dựng hoàn toàn từ price action M5 + H1TradingContext.
    """
    action: str = Field(
        description="'BUY', 'SELL', hoặc 'HOLD'."
    )
    entry_trigger: str = Field(
        description=(
            "Điều kiện kỹ thuật M5 đã kích hoạt entry (tiếng Việt). "
            "Ví dụ: 'CHoCH Bullish M5 tại 2319.50 xác nhận, giá đang chạm FVG M5 [2318–2320].'"
        )
    )
    sl_reference: str = Field(
        description=(
            "Tham chiếu đặt SL dựa trên cấu trúc M5 (tiếng Việt + giá). "
            "Ví dụ: 'Dưới low swing M5 gần nhất tại 2316.20 (buffer ~3–5 điểm).'"
        )
    )
    tp_reference: str = Field(
        description=(
            "Tham chiếu đặt TP — lấy từ target H1 (tiếng Việt + giá). "
            "Ví dụ: 'BSL H1 tại 2345 — khớp với target H1 đã xác định.'"
        )
    )
    geometry_reason: str = Field(
        description=(
            "Mô tả ngắn gọn cấu trúc hình học M5 đang thấy trên chart (tiếng Việt). "
            "Ví dụ: 'CHoCH tại nến 14:35, FVG M5 [2318–2320] chưa lấp, EMA21 hội tụ, "
            "giá đang retest vùng này từ dưới lên.'"
        )
    )
    hold_reason: str = Field(
        description=(
            "Nếu action=HOLD: lý do cụ thể tại sao chưa vào (tiếng Việt). "
            "Nếu action=BUY/SELL: để trống hoặc ghi 'N/A'."
        )
    )
    confidence: str = Field(description="'HIGH', 'MEDIUM', hoặc 'LOW'.")


