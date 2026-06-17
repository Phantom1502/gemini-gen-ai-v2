"""
bot/core/pipeline.py
====================
ICTPipeline — quản lý luồng phân tích 3 stage ICT và cache.

Cache strategy:
  Stage 1 Daily : cache 4h — refresh tại 0h/4h/8h/12h GMT
  Stage 2 H1    : cache 1h — refresh khi giờ UTC thay đổi
  Stage 3 M5    : không cache — chạy mỗi nến M5

Trách nhiệm của class này:
  - Lấy dữ liệu từ MT5
  - Vẽ chart 3 TF
  - Gọi AI 3 stage theo đúng thứ tự và phân tầng
  - Quản lý cache Daily và H1
  - Trả về PipelineResult dict chuẩn
"""

import datetime
import traceback
from typing import Optional, Dict, Tuple

import config
from bot.broker.mt5       import MT5Util
from bot.analysis.daily   import DailyBiasUtil
from bot.analysis.h1      import H1StructureUtil
from bot.analysis.m5      import M5EntryUtil
from bot.ai.agent         import ICTAIAgent


# ── Trigger hours cho Daily Bias ────────────────────────────────
_TRIGGER_HOURS = tuple(getattr(config, "DAILY_BIAS_REFRESH_HOURS_GMT", (0, 4, 8, 12)))


def _get_trigger_hour(utc_hour: int) -> int:
    trigger = 0
    for h in _TRIGGER_HOURS:
        if utc_hour >= h:
            trigger = h
    return trigger


# ── Kiểu trả về ─────────────────────────────────────────────────
EMPTY_RESULT: Dict = {
    "final_action":  "HOLD",
    "pipeline_ok":   False,
    "trigger_hour":  0,
    "stage1_daily":  None,
    "stage2_h1":     None,
    "stage3_m5":     None,
    "daily_img":     "",
    "h1_img":        "",
    "m5_img":        "",
    "daily_payload": None,
    "h1_payload":    None,
    "m5_payload":    None,
}


class ICTPipeline:
    """
    Chạy pipeline ICT 3 stage với cache tối ưu.
    Khởi tạo một lần, gọi run() mỗi nến M5.
    """

    def __init__(self, symbol: str, agent: ICTAIAgent):
        self.symbol = symbol
        self.agent  = agent

        self._daily_cache: Dict = {
            "key":     None,   # (date_str, trigger_hour)
            "result":  None,
            "payload": None,
            "img":     None,
        }
        self._h1_cache: Dict = {
            "key":     None,   # (date_str, hour_int)
            "result":  None,
            "payload": None,
            "img":     None,
        }

    def run(self, now_utc: datetime.datetime) -> Dict:
        """
        Chạy pipeline đầy đủ cho thời điểm now_utc.
        Trả về dict chuẩn (luôn có 'final_action' key).
        """
        # ── 1. Lấy dữ liệu MT5 ───────────────────────────────────
        try:
            df_daily, df_h1, df_m5 = MT5Util.get_multi_tf_data(
                self.symbol,
                h1_count  = config.H1_FETCH_COUNT,
                h1_window = config.H1_CHART_WINDOW,
                m5_window = config.M5_CHART_WINDOW,
            )
        except Exception as e:
            print(f"❌ [PIPELINE] Lỗi lấy dữ liệu: {e}")
            return {**EMPTY_RESULT}

        date_str     = now_utc.strftime("%Y%m%d")
        trigger_hour = _get_trigger_hour(now_utc.hour)
        trigger_key  = (date_str, trigger_hour)
        hour_key     = (date_str, now_utc.hour)

        # ══════════════════════════════════════════════════════════
        # STAGE 1: Daily Bias (cache 4h)
        # ══════════════════════════════════════════════════════════
        daily_context, daily_payload, daily_img = self._run_stage1(
            df_daily, trigger_key
        )
        if daily_context is None:
            return {**EMPTY_RESULT, "trigger_hour": trigger_hour}

        # ══════════════════════════════════════════════════════════
        # STAGE 2: H1 Structure (cache per-hour)
        # ══════════════════════════════════════════════════════════
        h1_result, h1_payload, h1_img = self._run_stage2(
            df_h1, daily_context, daily_payload, daily_context, hour_key
        )
        if h1_result is None:
            return {
                **EMPTY_RESULT,
                "trigger_hour": trigger_hour,
                "stage1_daily": daily_context,
                "daily_img":    daily_img,
                "daily_payload": daily_payload,
            }

        # ══════════════════════════════════════════════════════════
        # STAGE 3: M5 Entry (mỗi nến M5, không cache)
        # ══════════════════════════════════════════════════════════
        m5_result, m5_payload, m5_img = self._run_stage3(
            df_m5, h1_result
        )
        if m5_result is None:
            return {
                **EMPTY_RESULT,
                "trigger_hour":  trigger_hour,
                "stage1_daily":  daily_context,
                "stage2_h1":     h1_result,
                "daily_img":     daily_img,
                "h1_img":        h1_img,
                "daily_payload": daily_payload,
                "h1_payload":    h1_payload,
            }

        return {
            "final_action":  m5_result.get("action", "HOLD"),
            "pipeline_ok":   True,
            "trigger_hour":  trigger_hour,
            "stage1_daily":  daily_context,
            "stage2_h1":     h1_result,
            "stage3_m5":     m5_result,
            "daily_img":     daily_img,
            "h1_img":        h1_img,
            "m5_img":        m5_img,
            "daily_payload": daily_payload,
            "h1_payload":    h1_payload,
            "m5_payload":    m5_payload,
        }

    # ── Stage runners ────────────────────────────────────────────

    def _run_stage1(
        self, df_daily, trigger_key: Tuple
    ):
        """Daily Bias — cache theo trigger_key (date, hour)."""
        if self._daily_cache["key"] == trigger_key:
            c = self._daily_cache
            print(f"♻️  [DAILY] Cache | Bias={c['result'].get('bias')} | "
                  f"trigger={trigger_key[1]:02d}h GMT")
            return c["result"], c["payload"], c["img"]

        print(f"🔄 [DAILY] Refresh tại trigger={trigger_key[1]:02d}h GMT...")
        try:
            img, payload = DailyBiasUtil.generate_daily_chart(
                df_daily, folder=config.CHART_FOLDER
            )
        except Exception as e:
            print(f"❌ [DAILY CHART] {e}"); traceback.print_exc()
            return None, None, None

        result = self.agent.analyze_daily(img, payload)
        if result is None:
            return None, None, None

        self._daily_cache = {"key": trigger_key, "result": result,
                             "payload": payload, "img": img}
        # Invalidate H1 cache khi Daily mới
        self._h1_cache["key"] = None

        dol = result.get("draw_on_liquidity") or {}
        print(f"📊 [DAILY] Bias={result.get('bias')} | "
              f"Conf={result.get('confidence')} | "
              f"DOL={dol.get('label','?')} @ {dol.get('price','?')}")
        return result, payload, img

    def _run_stage2(
        self, df_h1, daily_context: Dict, daily_payload: Dict,
        daily_result: Dict, hour_key: Tuple
    ):
        """H1 Structure — cache theo hour_key (date, hour)."""
        if self._h1_cache["key"] == hour_key:
            c = self._h1_cache
            print(f"♻️  [H1] Cache | Direction={c['result'].get('direction')} | "
                  f"{hour_key[1]:02d}h GMT")
            return c["result"], c["payload"], c["img"]

        print(f"🔄 [H1] Refresh tại {hour_key[1]:02d}h GMT...")
        try:
            img, payload = H1StructureUtil.generate_h1_chart(
                df_h1,
                daily_context = daily_context,
                daily_payload = daily_payload,
                folder        = config.CHART_FOLDER,
            )
        except Exception as e:
            print(f"❌ [H1 CHART] {e}"); traceback.print_exc()
            return None, None, None

        # Bổ sung PDH/PDL vào h1_payload để M5 chart tham chiếu
        payload["pdh"] = daily_payload["yesterday_anchors"]["PDH"]
        payload["pdl"] = daily_payload["yesterday_anchors"]["PDL"]

        result = self.agent.analyze_h1(img, payload, daily_result)
        if result is None:
            return None, None, None

        self._h1_cache = {"key": hour_key, "result": result,
                          "payload": payload, "img": img}
        ez = (result.get("entry_zone") or {})
        print(f"📊 [H1] Direction={result.get('direction')} | "
              f"Zone={ez.get('zone_type','?')} "
              f"[{ez.get('price_bot','?')}–{ez.get('price_top','?')}] | "
              f"Conf={result.get('confidence')}")
        return result, payload, img

    def _run_stage3(self, df_m5, h1_result: Dict):
        """M5 Entry — chạy mỗi nến, không cache."""
        try:
            img, payload = M5EntryUtil.generate_m5_chart(
                df_m5,
                h1_context = h1_result,
                folder     = config.CHART_FOLDER,
            )
        except Exception as e:
            print(f"❌ [M5 CHART] {e}"); traceback.print_exc()
            return None, None, None

        result = self.agent.analyze_m5(img, payload, h1_result)
        if result is None:
            return None, None, None

        action = result.get("action", "HOLD")
        print(f"🎯 [M5] Action={action} | Conf={result.get('confidence')}")
        if action == "HOLD":
            print(f"   ⏸  {result.get('hold_reason','')}")
        else:
            print(f"   ▶  {result.get('entry_trigger','')}")
            print(f"   📐 {result.get('geometry_reason','')}")

        return result, payload, img
