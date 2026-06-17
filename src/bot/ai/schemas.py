"""
bot/ai/schemas.py
=================
Pydantic schemas cho 3 stage ICT AI pipeline.

Triết lý phân tầng:
  Daily → xác định xu hướng lớn và DOL
  H1    → đánh giá cấu trúc, quyết định M5 có được phép vào lệnh không
  M5    → tìm entry thuần túy dựa trên price action M5
"""

from pydantic import BaseModel, Field


# ── Output Stage 1: Daily ────────────────────────────────────────

class LiquidityTarget(BaseModel):
    label:  str = Field(description="Tên mục tiêu. Ví dụ: 'BSL tại 2345.50'")
    price:  str = Field(description="Mức giá cụ thể.")
    reason: str = Field(description="Tại sao đây là DOL (tiếng Việt, ngắn gọn).")


class DailyBiasContext(BaseModel):
    """Output Stage 1. H1 đọc context này để biết bức tranh lớn."""
    bias: str = Field(
        description="'BULLISH', 'BEARISH', hoặc 'NEUTRAL'."
    )
    market_state: str = Field(
        description="Mô tả trạng thái thị trường Daily hiện tại (tiếng Việt)."
    )
    draw_on_liquidity: LiquidityTarget = Field(
        description="Mục tiêu thanh khoản tiếp theo mà giá Daily đang hướng đến."
    )
    htf_invalidation: str = Field(
        description="Mức giá/điều kiện Daily nếu bị vi phạm thì bias sai hoàn toàn."
    )
    ltf_guidance: str = Field(
        description=(
            "Hướng dẫn ngắn gọn cho H1: LTF nên chờ điều kiện gì "
            "trước khi tìm entry. Không đề cập entry cụ thể."
        )
    )
    confidence: str = Field(description="'HIGH', 'MEDIUM', hoặc 'LOW'.")


# ── Output Stage 2: H1 ──────────────────────────────────────────

class H1TradingContext(BaseModel):
    """
    Output Stage 2. M5 nhận context này và tìm entry.

    H1 trả lời 3 câu hỏi cốt lõi:
      1. ready_to_trade  — M5 có được phép tìm entry không?
      2. direction       — BUY hay SELL?
      3. target          — đến đâu?

    M5 KHÔNG biết:
      - Daily Bias là gì
      - POI H1 ở đâu, tên gì
      - Tại sao H1 cho phép vào lệnh

    H1 tự đánh giá ready_to_trade dựa trên TOÀN BỘ cấu trúc H1:
      - Cấu trúc H1 có thuận Daily Bias không?
      - Giá H1 đã phản ứng đúng hướng chưa (rejection, BOS, displacement)?
      - Momentum H1 đang đi theo hướng kịch bản không?
    """
    direction: str = Field(
        description="'BUY', 'SELL', hoặc 'WAIT'."
    )
    ready_to_trade: bool = Field(
        description=(
            "True  = M5 được phép tìm entry ngay bây giờ.\n"
            "False = M5 phải HOLD, H1 chưa sẵn sàng.\n\n"
            "True khi TẤT CẢ đều đúng:\n"
            "  - H1 trend thuận Daily Bias\n"
            "  - Giá H1 đã tiếp cận vùng cung/cầu quan trọng (OB/FVG/swing)\n"
            "    VÀ đã có phản ứng (rejection, displacement, BOS thuận hướng)\n"
            "  - Momentum H1 đang đi theo hướng kịch bản\n\n"
            "False khi:\n"
            "  - H1 trend ngược/ranging\n"
            "  - Giá H1 chưa chạm vùng quan trọng nào\n"
            "  - Chưa có phản ứng/xác nhận ở H1"
        )
    )
    h1_summary: str = Field(
        description=(
            "Tóm tắt ngắn gọn lý do ready_to_trade=True/False (tiếng Việt, 1-2 câu). "
            "Ví dụ True: 'Giá H1 đã rejection tại OB_BEAR, nến H1 đóng cửa giảm mạnh, "
            "momentum đang hướng xuống.' "
            "Ví dụ False: 'Giá H1 đang trong vùng ranging, chưa có BOS rõ ràng.'"
        )
    )
    target: str = Field(
        description=(
            "Mục tiêu giá (TP reference) nhất quán với DOL Daily. "
            "Ví dụ: 'SSL tại 4280 — đáy swing H1 gần nhất chưa bị chạm.'"
        )
    )
    invalidation: str = Field(
        description=(
            "Điều kiện H1 làm mất hiệu lực toàn bộ kịch bản. "
            "Ví dụ: 'H1 đóng cửa trên 4360 thì kịch bản SELL hủy.'"
        )
    )
    confidence: str = Field(description="'HIGH', 'MEDIUM', hoặc 'LOW'.")


# ── Output Stage 3: M5 ──────────────────────────────────────────

class M5EntryResult(BaseModel):
    """
    Output Stage 3. Quyết định cuối cùng từ price action M5 thuần túy.
    """
    action: str = Field(description="'BUY', 'SELL', hoặc 'HOLD'.")
    entry_trigger: str = Field(
        description=(
            "Điều kiện M5 đã kích hoạt entry (tiếng Việt). "
            "Ví dụ: 'CHoCH_BEAR xác nhận tại 4332, giá retest FVG M5 [4330–4332].'"
        )
    )
    sl_reference: str = Field(
        description=(
            "Tham chiếu SL từ cấu trúc M5 (tiếng Việt + giá). "
            "Ví dụ: 'Trên high swing M5 gần nhất tại 4336.'"
        )
    )
    tp_reference: str = Field(
        description="TP reference từ target H1 (tiếng Việt + giá)."
    )
    geometry_reason: str = Field(
        description=(
            "Mô tả hình học M5 đang thấy trên chart (tiếng Việt). "
            "Ví dụ: 'CHoCH_BEAR nến 14:35, FVG M5 [4330–4332] chưa lấp, "
            "EMA21 dốc xuống, giá retest từ dưới.'"
        )
    )
    hold_reason: str = Field(
        description=(
            "Nếu HOLD: lý do cụ thể. "
            "Nếu BUY/SELL: 'N/A'."
        )
    )
    confidence: str = Field(description="'HIGH', 'MEDIUM', hoặc 'LOW'.")
