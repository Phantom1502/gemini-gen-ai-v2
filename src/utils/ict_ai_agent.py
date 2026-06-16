"""
ict_ai_agent.py  (V2.2 — Phân tầng trách nhiệm nghiêm ngặt)
=============================================================

Nguyên tắc thiết kế:
─────────────────────
  Stage 1 — Daily:
    Input  : chart Daily + daily_payload (BSL/SSL/PDH/PDL/EQ/liquidity)
    Output : DailyBiasContext  — bức tranh toàn cảnh, DOL, ngữ cảnh LTF

  Stage 2 — H1:
    Input  : chart H1 + h1_payload + DailyBiasContext (từ Stage 1)
    Output : H1TradingContext  — kịch bản cụ thể: hướng, từ đâu, đến đâu

  Stage 3 — M5:
    Input  : chart M5 + m5_payload + H1TradingContext (từ Stage 2)
    Output : M5EntryResult     — tìm entry: BUY/SELL/HOLD + geometry

  ⚠️  M5 TUYỆT ĐỐI không nhận bất kỳ thông tin nào từ Daily.
      M5 chỉ biết H1 context: hướng giao dịch, vùng entry, mục tiêu.
      Điều này buộc M5 phải ra quyết định thuần túy từ price action M5.

Luồng dữ liệu:
─────────────
  daily_payload ──► [AI Daily] ──► DailyBiasContext
                                        │
                    h1_payload ─────────▼
                                [AI H1]  ──► H1TradingContext
                                                  │
                              m5_payload ─────────▼
                                          [AI M5]  ──► M5EntryResult
"""

import os
import json
from PIL import Image
from pydantic import BaseModel, Field
from typing import Optional, Dict, List
from google import genai
from google.genai import types


# ═══════════════════════════════════════════════════════════════════
# SCHEMAS — Pydantic, dùng làm response_schema cho Gemini
# ═══════════════════════════════════════════════════════════════════

# ── Output Stage 1 ──────────────────────────────────────────────

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


# ═══════════════════════════════════════════════════════════════════
# SYSTEM PROMPTS
# ═══════════════════════════════════════════════════════════════════

# ── Stage 1: Daily ──────────────────────────────────────────────

DAILY_SYSTEM = """\
Bạn là chuyên gia phân tích HTF (Higher Time Frame) theo lý thuyết ICT.
Nhiệm vụ DUY NHẤT: đọc chart Daily + metadata số → xác định DAILY BIAS và DOL.

QUY TRÌNH PHÂN TÍCH (bắt buộc theo thứ tự):
1. XÁC ĐỊNH ZONE: Giá đang ở Premium hay Discount so với Equilibrium (EQ)?
   - DISCOUNT (dưới EQ) → thiên về BULLISH
   - PREMIUM  (trên EQ) → thiên về BEARISH

2. ĐÁNH GIÁ LIQUIDITY SWEEP gần nhất:
   - Có dấu 'x' vàng trên ảnh (SSL hoặc BSL bị quét)?
   - SSL bị quét + giá bật lên  → BULLISH sweep confirmation
   - BSL bị quét + giá đảo xuống → BEARISH sweep confirmation

3. ORDER FLOW — đọc cụm nến bên phải chart:
   - Nến tăng mạnh (Bullish Engulfing / Displacement Up) → Bullish
   - Nến giảm mạnh (Bearish Engulfing / Displacement Down) → Bearish

4. DOL — xác định mục tiêu thanh khoản tiếp theo:
   - Nếu BULLISH → DOL là BSL (đường cam) chưa bị quét gần nhất phía trên
   - Nếu BEARISH → DOL là SSL (đường xanh) chưa bị quét gần nhất phía dưới

5. INVALIDATION — xác định điều kiện phủ nhận bias:
   - Đặt ở mức cấu trúc sẽ xác nhận bias ngược lại nếu bị phá vỡ

GIỚI HẠN: Bạn CHỈ phân tích Daily. Không đề xuất entry, không nói đến FVG M5/H1.
Kết quả của bạn là 'ltf_guidance' — định hướng chung cho H1, không phải lệnh cụ thể.

Ngôn ngữ phân tích: tiếng Việt.
Output: JSON thuần theo schema, không backtick, không giải thích ngoài JSON.
"""

# ── Stage 2: H1 ─────────────────────────────────────────────────

H1_SYSTEM = """\
Bạn là chuyên gia phân tích cấu trúc H1 theo lý thuyết ICT.
Bạn đã nhận được DailyBiasContext từ phân tích Daily — đây là bức tranh lớn.
Nhiệm vụ: Đọc chart H1 + payload H1 → xây dựng KỊCH BẢN GIAO DỊCH cụ thể.

DỮ LIỆU BẠN CÓ:
- DailyBiasContext: hướng thiên vị, DOL, ltf_guidance từ Daily
- Chart H1: cấu trúc hiện tại với FVG (vùng tô màu), OB (hatch), EMA50 (vàng), PDH/PDL (đứt)
- H1 payload: số liệu FVG/OB active, BOS gần nhất, EMA50

QUY TRÌNH (bắt buộc theo thứ tự):
1. XÁC NHẬN ALIGNMENT:
   - H1 trend có thuận với Daily Bias không?
   - Nếu H1 đang ngược Daily (ranging/counter) → direction='WAIT', giải thích rõ

2. XÁC ĐỊNH CẤU TRÚC H1:
   - BOS gần nhất theo hướng Daily là gì? (xác nhận swing đang hình thành)
   - Giá đang expansion hay đang pullback?

3. TÌM ENTRY ZONE (vùng M5 sẽ canh entry):
   - Nếu BULLISH: tìm FVG_BULL hoặc OB_BULL phía dưới giá (pullback zone)
   - Nếu BEARISH: tìm FVG_BEAR hoặc OB_BEAR phía trên giá (supply zone)
   - Ưu tiên vùng gần giá nhất, chưa bị lấp/mitigation

4. XÁC ĐỊNH MỤC TIÊU (target):
   - Nếu BULLISH: BSL hoặc swing high H1 gần nhất chưa bị chạm
   - Nếu BEARISH: SSL hoặc swing low H1 gần nhất chưa bị chạm
   - Target phải NHẤT QUÁN với DOL trong DailyBiasContext

5. INVALIDATION H1:
   - Mức đóng cửa H1 nào sẽ phủ nhận hoàn toàn kịch bản này?

GIỚI HẠN QUAN TRỌNG:
- Bạn mô tả VÙNG để M5 vào lệnh (entry_zone), không phải giá entry chính xác
- Bạn KHÔNG phân tích M5, không đề cập CHoCH M5
- scenario_note: chỉ dẫn thêm cho M5 nếu cần (ví dụ: PDH ở giữa đường có thể gây tắc)

Ngôn ngữ: tiếng Việt.
Output: JSON thuần theo schema, không backtick.
"""

# ── Stage 3: M5 ─────────────────────────────────────────────────

M5_SYSTEM = """\
Bạn là chuyên gia tìm điểm entry M5 theo ICT Model 2022 (CHoCH + FVG).

BẠN CHỈ CÓ:
- H1TradingContext: hướng (BUY/SELL/WAIT), entry_zone H1, target, invalidation
- Chart M5: price action chi tiết với CHoCH (đường đứt dọc), FVG (vùng tô màu), EMA21 (tím)
- M5 payload: CHoCH gần nhất, FVG M5 gần nhất, EMA21, giá hiện tại

BẠN KHÔNG BIẾT và KHÔNG CẦN BIẾT:
- Daily Bias là gì
- Tại sao H1 chọn hướng đó
- BSL/SSL/PDH/PDL Daily

NHIỆM VỤ DUY NHẤT: Dựa vào H1TradingContext + price action M5 → quyết định vào lệnh hay không.

QUY TRÌNH (bắt buộc):
1. KIỂM TRA ALIGNMENT:
   - Nếu H1TradingContext.direction = 'WAIT' → action='HOLD', hold_reason='H1 chưa có kịch bản rõ ràng'
   - Nếu direction = 'BUY' → chỉ tìm BUY setup, KHÔNG xem xét SELL
   - Nếu direction = 'SELL' → chỉ tìm SELL setup, KHÔNG xem xét BUY

2. KIỂM TRA VỊ TRÍ GIÁ:
   - Giá M5 hiện tại có đang trong hoặc rất gần entry_zone H1 không?
   - Nếu giá còn xa entry_zone → HOLD (chưa đến vùng)

3. XÁC NHẬN CHoCH M5 (bắt buộc để vào lệnh):
   - BUY: phải có CHoCH_BULL gần đây (đường đứt dọc xanh) trong hoặc ngay trên entry_zone
   - SELL: phải có CHoCH_BEAR gần đây (đường đứt dọc đỏ) trong hoặc ngay dưới entry_zone
   - Nếu CHoCH chưa xuất hiện → HOLD

4. XÁC NHẬN FVG M5 (tùy chọn nhưng tăng chất lượng):
   - FVG M5 cùng hướng nằm trong entry_zone H1 → entry có chất lượng cao hơn
   - Không có FVG M5 vẫn có thể vào nếu CHoCH đủ mạnh

5. KIỂM TRA EMA21:
   - BUY: giá không được quá xa EMA21 về phía trên (overextended)
   - SELL: giá không được quá xa EMA21 về phía dưới

6. ĐẶT SL / TP:
   - SL: dựa trên cấu trúc M5 (low swing gần nhất cho BUY, high swing cho SELL)
   - TP: dùng target từ H1TradingContext (không tự đặt target khác)

HOLD nếu BẤT KỲ điều kiện nào sau đây đúng:
- CHoCH M5 chưa xuất hiện hoặc ngược hướng
- Giá chưa vào entry_zone H1
- Giá overextended so với EMA21
- H1 direction = 'WAIT'

Ngôn ngữ: tiếng Việt.
Output: JSON thuần theo schema, không backtick.
"""


# ═══════════════════════════════════════════════════════════════════
# AGENT CLASS
# ═══════════════════════════════════════════════════════════════════

class ICTAIAgent:
    """
    Multi-stage AI agent — phân tầng trách nhiệm nghiêm ngặt.

    Luồng:
        daily_payload → analyze_daily() → DailyBiasContext
                                               ↓
        h1_payload   → analyze_h1(context) → H1TradingContext
                                                    ↓
        m5_payload   → analyze_m5(context) → M5EntryResult
    """

    def __init__(self, api_key: str, model_name: str = "gemini-2.0-flash"):
        self.client     = genai.Client(api_key=api_key)
        self.model_name = model_name

    # ── Stage 1: Daily Bias ─────────────────────────────────────

    def analyze_daily(
        self,
        image_path: str,
        daily_payload: Dict,
    ) -> Optional[Dict]:
        """
        Stage 1: Chart Daily + payload → DailyBiasContext.

        Parameters
        ----------
        image_path    : đường dẫn PNG chart Daily
        daily_payload : dict số từ DailyBiasUtil (BSL/SSL, EQ, PDH/PDL...)

        Returns
        -------
        dict khớp DailyBiasContext schema, hoặc None nếu lỗi.
        """
        if not os.path.exists(image_path):
            print(f"❌ [DAILY] Không tìm thấy chart: {image_path}")
            return None
        try:
            img = Image.open(image_path)

            # Chuẩn bị metadata số — súc tích, chỉ những gì AI cần
            liq_map  = daily_payload.get("liquidity_map", {})
            anchors  = daily_payload.get("yesterday_anchors", {})
            metrics  = daily_payload.get("mathematical_metrics", {})
            mctx     = daily_payload.get("market_context", {})

            active_liq = liq_map.get("active_liquidity", [])
            swept_liq  = liq_map.get("recently_swept_liquidity", [])

            prompt = f"""\
[DỮ LIỆU SỐ DAILY]
Giá hiện tại    : {mctx.get('current_price')}
Vùng giá        : {mctx.get('price_zone_vs_equilibrium')} (so với EQ)
Equilibrium     : {metrics.get('equilibrium')}  \
(khoảng cách: {metrics.get('distance_to_equilibrium_pct')}%)
PDH / PDL       : {anchors.get('PDH')} / {anchors.get('PDL')}
Hôm qua đóng   : {anchors.get('yesterday_close')}  \
({'Bearish' if anchors.get('is_yesterday_bearish') else 'Bullish'})

Thanh khoản ACTIVE (chưa bị quét):
{_fmt_list(active_liq, lambda x: f"  {x['type']} @ {x['price']}  ({x['distance_pct']:+.2f}%)")}

Thanh khoản vừa bị SWEPT (≤5 nến gần nhất):
{_fmt_list(swept_liq, lambda x: f"  {x['type']} @ {x['price']}  ({x['swept_at_candles_ago']} nến trước)") or '  (không có)'}

[YÊU CẦU VISION — đọc chart theo thứ tự]
1. Xác nhận vùng Premium/Discount từ vị trí giá vs EQ trên chart.
2. Tìm dấu 'x' vàng (swept liquidity) — BSL hay SSL vừa bị quét?
3. Đọc cụm nến cuối bên phải: displacement tăng hay giảm?
4. Kết luận Daily Bias và chọn DOL phù hợp.
5. Viết ltf_guidance cho H1 — định hướng chung, không đề cập entry cụ thể.

Output JSON theo schema DailyBiasContext.
"""
            print("🔍 [Stage 1] Phân tích Daily Bias...")
            response = self.client.models.generate_content(
                model=self.model_name,
                contents=[img, prompt],
                config=types.GenerateContentConfig(
                    system_instruction=DAILY_SYSTEM,
                    temperature=0.0,
                    response_mime_type="application/json",
                    response_schema=DailyBiasContext,
                ),
            )
            result = json.loads(response.text)
            print(
                f"   ✅ Bias={result.get('bias')} | "
                f"DOL={result.get('draw_on_liquidity', {}).get('label')} | "
                f"Confidence={result.get('confidence')}"
            )
            return result

        except Exception as e:
            import traceback
            print(f"❌ [DAILY] Lỗi: {e}")
            traceback.print_exc()
            return None

    # ── Stage 2: H1 Structure ───────────────────────────────────

    def analyze_h1(
        self,
        image_path: str,
        h1_payload: Dict,
        daily_context: Dict,     # DailyBiasContext từ Stage 1
    ) -> Optional[Dict]:
        """
        Stage 2: Chart H1 + payload + DailyBiasContext → H1TradingContext.

        Parameters
        ----------
        image_path    : đường dẫn PNG chart H1
        h1_payload    : dict số từ H1StructureUtil (FVG/OB/BOS/EMA50...)
        daily_context : dict DailyBiasContext từ analyze_daily()

        Returns
        -------
        dict khớp H1TradingContext schema, hoặc None nếu lỗi.
        """
        if not os.path.exists(image_path):
            print(f"❌ [H1] Không tìm thấy chart: {image_path}")
            return None

        # Guard: daily_context phải là dict
        if not isinstance(daily_context, dict):
            print(f"❌ [H1] daily_context sai kiểu: {type(daily_context)!r} — "
                  f"{str(daily_context)[:200]}")
            return None

        try:
            img = Image.open(image_path)

            # draw_on_liquidity: Gemini đôi khi trả nested object dưới dạng str
            _dol_raw = daily_context.get("draw_on_liquidity") or {}
            if isinstance(_dol_raw, dict):
                dol = _dol_raw
            else:
                try:
                    dol = json.loads(_dol_raw) if isinstance(_dol_raw, str) else {}
                except Exception:
                    dol = {"label": str(_dol_raw), "price": "—", "reason": "—"}

            prompt = f"""\
[DAILY BIAS CONTEXT — từ phân tích Daily]
Hướng thiên vị  : {daily_context.get('bias')}
Trạng thái Daily: {daily_context.get('market_state')}
Draw on Liquidity: {dol.get('label')} @ {dol.get('price')} — {dol.get('reason')}
HTF Invalidation: {daily_context.get('htf_invalidation')}
Hướng dẫn cho H1: {daily_context.get('ltf_guidance')}

[DỮ LIỆU SỐ H1]
Giá hiện tại    : {h1_payload.get('current_price')}
EMA 50          : {h1_payload.get('ema_50')}  ({h1_payload.get('price_vs_ema50')})
PDH / PDL       : {h1_payload.get('pdh')} / {h1_payload.get('pdl')}
FVG active      : {h1_payload.get('active_fvg_count')}  |  OB active: {h1_payload.get('active_ob_count')}
BOS gần nhất    : {_fmt_bos(h1_payload.get('last_bos'))}

FVG active gần nhất (tối đa 3):
{_fmt_list(h1_payload.get('active_fvgs', []), _fmt_fvg)}

OB active gần nhất (tối đa 3):
{_fmt_list(h1_payload.get('active_obs', []), _fmt_ob)}

[YÊU CẦU VISION — đọc chart H1 theo thứ tự]
1. H1 trend có THUẬN với Daily Bias không? Nếu không → direction='WAIT'.
2. Cấu trúc H1: BOS gần nhất theo hướng Daily ở đâu? Giá đang expansion hay pullback?
3. Tìm entry_zone tốt nhất (FVG hoặc OB) thuận hướng, gần giá nhất, chưa lấp.
4. Target: BSL/SSL H1 hoặc swing phù hợp với DOL Daily ở trên.
5. Điều kiện vô hiệu kịch bản này (invalidation H1).
6. scenario_note: chỉ dẫn thêm cho M5 nếu có cản cục bộ giữa entry và target.

Output JSON theo schema H1TradingContext.
"""
            print("🔍 [Stage 2] Phân tích H1 Structure...")
            response = self.client.models.generate_content(
                model=self.model_name,
                contents=[img, prompt],
                config=types.GenerateContentConfig(
                    system_instruction=H1_SYSTEM,
                    temperature=0.0,
                    response_mime_type="application/json",
                    response_schema=H1TradingContext,
                ),
            )
            result = json.loads(response.text)
            ez = result.get("entry_zone") or {}
            print(
                f"   ✅ Direction={result.get('direction')} | "
                f"Zone={ez.get('zone_type')} [{ez.get('price_bot')}–{ez.get('price_top')}] | "
                f"Target={result.get('target')} | "
                f"Confidence={result.get('confidence')}"
            )
            return result

        except Exception as e:
            import traceback
            print(f"❌ [H1] Lỗi: {e}")
            traceback.print_exc()
            return None

    # ── Stage 3: M5 Entry ───────────────────────────────────────

    def analyze_m5(
        self,
        image_path: str,
        m5_payload: Dict,
        h1_context: Dict,        # H1TradingContext từ Stage 2
    ) -> Optional[Dict]:
        """
        Stage 3: Chart M5 + payload + H1TradingContext → M5EntryResult.

        ⚠️  Không nhận bất kỳ thông tin Daily nào.
            M5 chỉ cần biết: hướng, entry_zone, target, invalidation từ H1.

        Parameters
        ----------
        image_path  : đường dẫn PNG chart M5
        m5_payload  : dict số từ M5EntryUtil (CHoCH/FVG/EMA21...)
        h1_context  : dict H1TradingContext từ analyze_h1()

        Returns
        -------
        dict khớp M5EntryResult schema, hoặc None nếu lỗi.
        """
        if not os.path.exists(image_path):
            print(f"❌ [M5] Không tìm thấy chart: {image_path}")
            return None

        # Guard: h1_context phải là dict
        if not isinstance(h1_context, dict):
            print(f"❌ [M5] h1_context sai kiểu: {type(h1_context)!r} — "
                  f"{str(h1_context)[:200]}")
            return None

        try:
            img = Image.open(image_path)

            # entry_zone: guard nếu Gemini trả về string thay vì dict
            _ez_raw = h1_context.get("entry_zone") or {}
            if isinstance(_ez_raw, dict):
                ez = _ez_raw
            else:
                try:
                    ez = json.loads(_ez_raw) if isinstance(_ez_raw, str) else {}
                except Exception:
                    ez = {"zone_type": str(_ez_raw), "price_top": "—",
                          "price_bot": "—", "description": "—"}

            prompt = f"""\
[H1 TRADING CONTEXT — nhiệm vụ của bạn]
Hướng giao dịch  : {h1_context.get('direction')}
Cấu trúc H1      : {h1_context.get('h1_structure')}
Entry Zone H1     : {ez.get('zone_type')}  [{ez.get('price_bot')} – {ez.get('price_top')}]
                    → {ez.get('description')}
Target (TP H1)    : {h1_context.get('target')}
Invalidation H1   : {h1_context.get('invalidation')}
Ghi chú kịch bản : {h1_context.get('scenario_note')}

[DỮ LIỆU SỐ M5]
Thời điểm        : {m5_payload.get('timestamp')}
Giá hiện tại     : {m5_payload.get('current_price')}
EMA 21           : {m5_payload.get('ema_21')}  ({m5_payload.get('price_vs_ema21')})

CHoCH gần nhất   : {_fmt_choch(m5_payload.get('choch'))}

FVG M5 entry     : {_fmt_fvg_m5(m5_payload.get('entry_fvg'))}

[YÊU CẦU VISION — đọc chart M5 theo thứ tự]
1. Hướng H1 là '{h1_context.get('direction')}' — chỉ tìm setup theo hướng này.
2. Giá M5 hiện tại có đang trong Entry Zone [{ez.get('price_bot')} – {ez.get('price_top')}] không?
3. CHoCH M5 (đường đứt dọc trên chart) cùng hướng đã xuất hiện chưa?
4. FVG M5 (vùng tô màu) có nằm trong entry zone H1 không?
5. EMA21: giá có overextended không?
6. Kết luận: BUY / SELL / HOLD với lý do cụ thể từ price action M5.

Output JSON theo schema M5EntryResult.
"""
            print("🔍 [Stage 3] Tìm M5 Entry...")
            response = self.client.models.generate_content(
                model=self.model_name,
                contents=[img, prompt],
                config=types.GenerateContentConfig(
                    system_instruction=M5_SYSTEM,
                    temperature=0.0,
                    response_mime_type="application/json",
                    response_schema=M5EntryResult,
                ),
            )
            result = json.loads(response.text)
            print(
                f"   ✅ Action={result.get('action')} | "
                f"Confidence={result.get('confidence')}"
            )
            if result.get('action') == 'HOLD':
                print(f"   ⏸  Hold reason: {result.get('hold_reason')}")
            else:
                print(f"   🎯 Trigger : {result.get('entry_trigger')}")
                print(f"   📐 Geometry: {result.get('geometry_reason')}")
            return result

        except Exception as e:
            import traceback
            print(f"❌ [M5] Lỗi: {e}")
            traceback.print_exc()
            return None

    # ── Full pipeline helper ────────────────────────────────────

    def run_full_pipeline(
        self,
        daily_img: str, daily_payload: Dict,
        h1_img: str,    h1_payload: Dict,
        m5_img: str,    m5_payload: Dict,
    ) -> Dict:
        """
        Chạy tuần tự 3 stage với phân tầng context đúng chuẩn.
        Dùng trong backtester hoặc dry-run.
        """
        result = {
            "stage1_daily": None, "stage2_h1": None, "stage3_m5": None,
            "final_action": "HOLD", "pipeline_ok": False,
        }

        # Stage 1
        daily_ctx = self.analyze_daily(daily_img, daily_payload)
        result["stage1_daily"] = daily_ctx
        if not daily_ctx:
            print("⛔ Pipeline dừng tại Stage 1.")
            return result

        # Stage 2
        h1_ctx = self.analyze_h1(h1_img, h1_payload, daily_ctx)
        result["stage2_h1"] = h1_ctx
        if not h1_ctx:
            print("⛔ Pipeline dừng tại Stage 2.")
            return result

        # Stage 3 — chỉ nhận h1_ctx, không có daily_ctx
        m5_ctx = self.analyze_m5(m5_img, m5_payload, h1_ctx)
        result["stage3_m5"] = m5_ctx
        if not m5_ctx:
            print("⛔ Pipeline dừng tại Stage 3.")
            return result

        result["final_action"] = m5_ctx.get("action", "HOLD")
        result["pipeline_ok"]  = True
        return result


# ═══════════════════════════════════════════════════════════════════
# FORMAT HELPERS (nội bộ)
# ═══════════════════════════════════════════════════════════════════

def _fmt_list(items: list, fmt_fn) -> str:
    if not items:
        return "  (không có)"
    return "\n".join(fmt_fn(x) for x in items)

def _fmt_bos(bos: Optional[Dict]) -> str:
    if not bos:
        return "(chưa có BOS)"
    return (
        f"{bos.get('type')} tại {bos.get('price')} "
        f"(nến #{bos.get('candle_idx')})"
    )

def _fmt_fvg(f: Dict) -> str:
    return (
        f"  {f.get('type')}  [{f.get('bottom'):.4f} – {f.get('top'):.4f}]"
        f"  mid={f.get('mid'):.4f}"
        f"  {'✓ filled' if f.get('filled') else '○ open'}"
    )

def _fmt_ob(o: Dict) -> str:
    return (
        f"  {o.get('type')}  [{o.get('bottom'):.4f} – {o.get('top'):.4f}]"
        f"  nến #{o.get('candle_idx')}"
        f"  {'✓ mitigated' if o.get('mitigated') else '○ fresh'}"
    )

def _fmt_choch(c: Optional[Dict]) -> str:
    if not c:
        return "(chưa phát hiện)"
    return (
        f"{c.get('type')}  broken_level={c.get('broken_level')}  "
        f"broken_at={c.get('broken_at')}  "
        f"({c.get('candles_ago')} nến trước)"
    )

def _fmt_fvg_m5(f: Optional[Dict]) -> str:
    if not f:
        return "(không có FVG M5 gần nhất)"
    return (
        f"{f.get('type')}  [{f.get('bottom')} – {f.get('top')}]"
        f"  mid={f.get('mid')}"
        f"  {'filled' if f.get('filled') else 'open'}"
    )
