"""
bot/ai/agent.py
===============
ICTAIAgent — orchestrates 3-stage Gemini AI calls.
Imports schemas from .schemas, prompts from .prompts.
"""

import os
import json
import traceback
from PIL import Image
from typing import Optional, Dict
from google import genai
from google.genai import types

from bot.ai.schemas import (
    DailyBiasContext, H1TradingContext, M5EntryResult,
)
from bot.ai.prompts import DAILY_SYSTEM, H1_SYSTEM, M5_SYSTEM


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
