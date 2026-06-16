"""
ict_ai_agent.py
===============
ICT AI Agent - V2
Gọi AI (Gemini) với 3 giai đoạn phân tích multi-timeframe:
  Stage 1: Daily Bias  (ảnh Daily + metadata)
  Stage 2: H1 Context  (ảnh H1  + daily_bias)
  Stage 3: M5 Entry    (ảnh M5  + h1_payload + action cuối)

Kế thừa cấu trúc GeminiTradingAgent v1, mở rộng thêm multi-stage.
"""

import os
import json
from PIL import Image
from pydantic import BaseModel, Field
from typing import Optional, Dict
from google import genai
from google.genai import types


# ══════════════════════════════════════════════════════════════════
# PYDANTIC SCHEMAS
# ══════════════════════════════════════════════════════════════════

class LTFExecutionContext(BaseModel):
    primary_scenario: str = Field(
        description="Kịch bản tối ưu cho LTF (tiếng Việt). Ví dụ: Chờ pullback về FVG H1 rồi tìm CHoCH M5 để BUY."
    )
    invalidation_level: str = Field(
        description="Điều kiện/mức giá (tiếng Việt) nếu bị vi phạm thì Daily Bias sai hoàn toàn."
    )


class DailyBiasResult(BaseModel):
    current_market_state: str = Field(description="Phân tích hành động giá Daily hiện tại (tiếng Việt).")
    draw_on_liquidity: str     = Field(description="Mục tiêu thanh khoản tiếp theo HTF (tiếng Việt, kèm giá).")
    daily_bias: str            = Field(description="BULLISH, BEARISH, hoặc NEUTRAL.")
    ltf_execution_context: LTFExecutionContext
    confidence_score: str      = Field(description="HIGH, MEDIUM, hoặc LOW.")


class H1ContextResult(BaseModel):
    h1_trend: str              = Field(description="Xu hướng H1 hiện tại: UPTREND, DOWNTREND, RANGING.")
    key_poi: str               = Field(description="Vùng POI quan trọng nhất H1 cần chú ý (tiếng Việt, kèm giá).")
    h1_scenario: str           = Field(description="Kịch bản H1 cụ thể thuận theo Daily Bias (tiếng Việt).")
    confidence_score: str      = Field(description="HIGH, MEDIUM, hoặc LOW.")


class M5EntryResult(BaseModel):
    action: str                = Field(description="BUY, SELL, hoặc HOLD.")
    entry_zone: str            = Field(description="Mô tả vùng entry M5 (tiếng Việt, kèm giá).")
    sl_reference: str          = Field(description="Tham chiếu đặt SL (tiếng Việt, kèm giá gợi ý).")
    tp_reference: str          = Field(description="Tham chiếu đặt TP / DOL (tiếng Việt, kèm giá gợi ý).")
    geometry_reason: str       = Field(description="Lý do hình học cụ thể trên chart M5 (tiếng Việt).")
    confidence_score: str      = Field(description="HIGH, MEDIUM, hoặc LOW.")


# ══════════════════════════════════════════════════════════════════
# SYSTEM PROMPTS
# ══════════════════════════════════════════════════════════════════

DAILY_SYSTEM = """
Bạn là Chuyên gia phân tích Market Structure ICT (Inner Circle Trader) cấp cao.
Nhiệm vụ: Kết hợp metadata số và ảnh biểu đồ Daily để xác định DAILY BIAS cho ngày giao dịch tiếp theo.

QUY TRÌNH BẮT BUỘC:
1. Premium/Discount: Dùng price_zone_vs_equilibrium → ưu tiên SHORT ở PREMIUM, LONG ở DISCOUNT.
2. Liquidity Sweep: Kiểm tra recently_swept_liquidity + dấu 'x' vàng trên ảnh. BSL bị quét → Bearish. SSL bị quét → Bullish.
3. Order Flow: Cụm nến cuối bên phải ảnh → Expansion/Displacement nến nào lớn hơn?
4. DOL: Chọn mục tiêu từ active_liquidity đi THUẬN Daily Bias.

Ngôn ngữ: Tất cả phân tích bằng tiếng Việt.
Output: JSON thuần (không backtick), khớp schema.
"""

H1_SYSTEM = """
Bạn là Chuyên gia phân tích cấu trúc H1 theo lý thuyết ICT.
Daily Bias đã được xác định ở bước trước. Nhiệm vụ: Phân tích biểu đồ H1 để:
1. Xác nhận H1 trend có THUẬN với Daily Bias không.
2. Tìm POI quan trọng nhất (FVG / OB) để giá pullback về.
3. Mô tả kịch bản cụ thể: giá cần làm gì ở H1 trước khi M5 có thể vào lệnh.

Các vùng được đánh dấu trên ảnh:
- Vùng tô màu xanh lá = FVG Bullish (imbalance mua)
- Vùng tô màu đỏ = FVG Bearish (imbalance bán)
- Vùng gạch chéo = Order Block
- Đường vàng = EMA 50
- Đường đứt đỏ = PDH | Đứt xanh = PDL

Ngôn ngữ: tiếng Việt. Output: JSON thuần, khớp schema.
"""

M5_SYSTEM = """
Bạn là Chuyên gia tìm điểm entry ICT theo phương pháp Model 2022 (CHoCH + FVG).
Daily Bias và H1 Context đã xác định. Nhiệm vụ cuối: Quan sát biểu đồ M5 để:
1. Xác nhận CHoCH M5 thuận hướng (đường đứt dọc trên ảnh).
2. Xác nhận vùng FVG M5 entry (vùng tô màu trên ảnh).
3. Quyết định BUY / SELL / HOLD dựa trên: giá có đang ở entry zone + CHoCH đã xác nhận chưa?

HOLD nếu:
- CHoCH chưa có hoặc ngược hướng Daily Bias
- Giá đang quá xa EMA 21 (overextended)
- Không có FVG rõ ràng

Ngôn ngữ: tiếng Việt. Output: JSON thuần, khớp schema.
"""


# ══════════════════════════════════════════════════════════════════
# AGENT CLASS
# ══════════════════════════════════════════════════════════════════

class ICTAIAgent:
    """
    Multi-stage AI agent phân tích 3 timeframe tuần tự.
    """

    def __init__(self, api_key: str, model_name: str = "gemini-2.0-flash"):
        self.client     = genai.Client(api_key=api_key)
        self.model_name = model_name

    # ──────────────────────────────────────────────
    # STAGE 1: DAILY BIAS
    # ──────────────────────────────────────────────
    def analyze_daily(self, image_path: str, daily_payload: Dict) -> Optional[Dict]:
        """Phân tích Daily → trả về DailyBiasResult dict."""
        if not os.path.exists(image_path):
            print(f"❌ [DAILY AGENT] Không tìm thấy ảnh: {image_path}")
            return None
        try:
            img = Image.open(image_path)
            user_prompt = f"""
[METADATA SỐ]
- Bối cảnh thị trường: {daily_payload.get('market_context', {})}
- Đo lường toán học: {daily_payload.get('mathematical_metrics', {})}
- Mốc giá Yesterday: {daily_payload.get('yesterday_anchors', {})}
- Bản đồ thanh khoản: {daily_payload.get('liquidity_map', {})}

[NHIỆM VỤ VISION]
1. Quan sát nến bên phải: có dấu 'x' vàng nào không? (BSL/SSL bị quét)
2. Giá hiện tại nằm nửa trên hay nửa dưới biên độ?
3. Nến cuối (hôm qua) có phải là Displacement không?

Phân tích từng bước rồi đưa ra Daily Bias và DOL. JSON theo schema.
"""
            print("🔍 [Stage 1] Phân tích Daily Bias...")
            response = self.client.models.generate_content(
                model=self.model_name,
                contents=[img, user_prompt],
                config=types.GenerateContentConfig(
                    system_instruction=DAILY_SYSTEM,
                    temperature=0.0,
                    response_mime_type="application/json",
                    response_schema=DailyBiasResult,
                ),
            )
            return json.loads(response.text)
        except Exception as e:
            print(f"❌ [DAILY AGENT] Lỗi: {e}")
            return None

    # ──────────────────────────────────────────────
    # STAGE 2: H1 CONTEXT
    # ──────────────────────────────────────────────
    def analyze_h1(self, image_path: str, daily_bias: str, h1_payload: Dict) -> Optional[Dict]:
        """Phân tích H1 → trả về H1ContextResult dict."""
        if not os.path.exists(image_path):
            print(f"❌ [H1 AGENT] Không tìm thấy ảnh: {image_path}")
            return None
        try:
            img = Image.open(image_path)
            user_prompt = f"""
[DAILY BIAS ĐÃ XÁC ĐỊNH] = {daily_bias}

[DỮ LIỆU H1]
- Giá hiện tại: {h1_payload.get('current_price')}
- EMA 50: {h1_payload.get('ema_50')} | Giá vs EMA50: {h1_payload.get('price_vs_ema50')}
- POI Target từ thuật toán: {h1_payload.get('poi_target')}
- BOS gần nhất: {h1_payload.get('last_bos')}
- FVG hoạt động: {h1_payload.get('active_fvgs')}
- OB hoạt động: {h1_payload.get('active_obs')}

[YÊU CẦU]
Quan sát ảnh H1, xác nhận H1 trend có thuận Daily Bias không.
Chỉ ra POI H1 quan trọng nhất để giá pullback về trước khi vào lệnh M5.
JSON theo schema.
"""
            print("🔍 [Stage 2] Phân tích H1 Structure...")
            response = self.client.models.generate_content(
                model=self.model_name,
                contents=[img, user_prompt],
                config=types.GenerateContentConfig(
                    system_instruction=H1_SYSTEM,
                    temperature=0.0,
                    response_mime_type="application/json",
                    response_schema=H1ContextResult,
                ),
            )
            return json.loads(response.text)
        except Exception as e:
            print(f"❌ [H1 AGENT] Lỗi: {e}")
            return None

    # ──────────────────────────────────────────────
    # STAGE 3: M5 ENTRY
    # ──────────────────────────────────────────────
    def analyze_m5(
        self,
        image_path: str,
        daily_bias: str,
        h1_result: Dict,
        m5_payload: Dict
    ) -> Optional[Dict]:
        """Phân tích M5 → trả về M5EntryResult dict (action cuối cùng)."""
        if not os.path.exists(image_path):
            print(f"❌ [M5 AGENT] Không tìm thấy ảnh: {image_path}")
            return None
        try:
            img = Image.open(image_path)
            user_prompt = f"""
[BỐI CẢNH ĐA KHUNG]
- Daily Bias: {daily_bias}
- H1 Trend: {h1_result.get('h1_trend')} | H1 POI: {h1_result.get('key_poi')}
- H1 Kịch bản: {h1_result.get('h1_scenario')}

[DỮ LIỆU M5]
- Giá hiện tại: {m5_payload.get('current_price')}
- EMA 21: {m5_payload.get('ema_21')} | Giá vs EMA21: {m5_payload.get('price_vs_ema21')}
- CHoCH phát hiện: {m5_payload.get('choch')}
- FVG Entry Zone: {m5_payload.get('entry_fvg')}

[YÊU CẦU]
1. Quan sát đường đứt dọc (CHoCH) trên ảnh M5: có xác nhận hướng Daily Bias chưa?
2. Vùng tô màu (FVG): giá có đang trong/gần vùng này không?
3. Quyết định BUY / SELL / HOLD với lý do hình học cụ thể.
JSON theo schema.
"""
            print("🔍 [Stage 3] Tìm M5 Entry...")
            response = self.client.models.generate_content(
                model=self.model_name,
                contents=[img, user_prompt],
                config=types.GenerateContentConfig(
                    system_instruction=M5_SYSTEM,
                    temperature=0.0,
                    response_mime_type="application/json",
                    response_schema=M5EntryResult,
                ),
            )
            return json.loads(response.text)
        except Exception as e:
            print(f"❌ [M5 AGENT] Lỗi: {e}")
            return None

    # ──────────────────────────────────────────────
    # PIPELINE ĐẦY ĐỦ 3 STAGE
    # ──────────────────────────────────────────────
    def run_full_pipeline(
        self,
        daily_img: str, daily_payload: Dict,
        h1_img: str,    h1_payload: Dict,
        m5_img: str,    m5_payload: Dict
    ) -> Dict:
        """
        Chạy tuần tự 3 stage và trả về kết quả tổng hợp.
        """
        result = {
            "stage1_daily": None,
            "stage2_h1":    None,
            "stage3_m5":    None,
            "final_action": "HOLD",
            "pipeline_ok":  False
        }

        # Stage 1
        daily_result = self.analyze_daily(daily_img, daily_payload)
        result["stage1_daily"] = daily_result
        if not daily_result:
            print("⛔ Pipeline dừng tại Stage 1.")
            return result

        daily_bias = daily_result.get("daily_bias", "NEUTRAL")
        print(f"📊 Daily Bias = {daily_bias} | Confidence = {daily_result.get('confidence_score')}")

        # Stage 2
        h1_result = self.analyze_h1(h1_img, daily_bias, h1_payload)
        result["stage2_h1"] = h1_result
        if not h1_result:
            print("⛔ Pipeline dừng tại Stage 2.")
            return result

        print(f"📊 H1 Trend = {h1_result.get('h1_trend')} | POI = {h1_result.get('key_poi')}")

        # Stage 3
        m5_result = self.analyze_m5(m5_img, daily_bias, h1_result, m5_payload)
        result["stage3_m5"] = m5_result
        if not m5_result:
            print("⛔ Pipeline dừng tại Stage 3.")
            return result

        result["final_action"] = m5_result.get("action", "HOLD")
        result["pipeline_ok"]  = True

        print(f"🎯 Final Action = {result['final_action']} | Confidence = {m5_result.get('confidence_score')}")
        return result