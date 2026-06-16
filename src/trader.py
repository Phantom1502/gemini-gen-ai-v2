"""
trader.py  (V2.1 — Daily Bias cache 4h, H1 cache per-hour, PDF report)
========================================================================
Thay đổi so với V2:

1. DAILY BIAS chỉ được query lại tại các mốc 0h / 4h / 8h / 12h GMT.
   Giữa các mốc đó, Daily Bias + daily_payload được dùng lại từ cache.
   → Tiết kiệm Gemini quota và đảm bảo bias nhất quán trong phiên.

2. H1 RESULT chỉ query lại mỗi khi GIỜ thay đổi (nến H1 mới).
   Trong cùng một giờ, mọi nến M5 dùng chung h1_result + h1_payload từ cache.
   → H1 không cần phân tích lại mỗi 5 phút.

3. PDF REPORT được tạo sau mỗi lần pipeline chạy đầy đủ,
   đặt tại data/reports/<SYMBOL>_<DATE>_H<trigger>.pdf

4. start_pos=0 cho tất cả TF (MT5Util đã sửa) — lấy nến đang chạy.
"""

import MetaTrader5 as mt5
import time
import os
import datetime
import pandas as pd
from typing import Optional

import config
from utils.mt5util           import MT5Util
from utils.daily_bias_util   import DailyBiasUtil
from utils.h1_structure_util import H1StructureUtil
from utils.m5_entry_util     import M5EntryUtil
from utils.ict_ai_agent      import ICTAIAgent
from utils.session_filter    import SessionFilter, TrailingStopManager
from utils.report_generator  import generate_session_report, build_report_path


# ═══════════════════════════════════════════════════════════════
# HELPER: xác định "trigger hour" của Daily Bias
# ═══════════════════════════════════════════════════════════════

DAILY_BIAS_HOURS_GMT = (0, 4, 8, 12)   # các mốc cập nhật Daily Bias

def get_daily_bias_trigger_hour(utc_hour: int) -> int:
    """
    Trả về trigger hour hiện tại của Daily Bias.
    Ví dụ: 0–3 GMT → trigger=0, 4–7 GMT → trigger=4, v.v.
    """
    trigger = 0
    for h in DAILY_BIAS_HOURS_GMT:
        if utc_hour >= h:
            trigger = h
    return trigger


class Trader:
    def __init__(
        self,
        username:     int   = config.MT5_USERNAME,
        password:     str   = config.MT5_PASSWORD,
        server:       str   = config.MT5_SERVER,
        symbol:       str   = config.MT5_SYMBOL,
        risk_percent: float = config.RISK_PERCENT,
        rr:           float = config.RR_RATIO,
        spreads:      int   = config.SPREADS,
        magic_number: int   = config.MAGIC_NUMBER,
        api_key:      str   = config.GEMINI_API_KEY,
        model_name:   str   = config.GEMINI_MODEL,
    ):
        self.symbol       = symbol
        self.risk_percent = risk_percent
        self.rr           = rr
        self.spreads      = spreads
        self.magic_number = magic_number

        MT5Util.init_mt5(username, password, server, symbol)

        self.agent            = ICTAIAgent(api_key=api_key, model_name=model_name)
        self.session_filter   = SessionFilter()
        self.trailing_manager = TrailingStopManager(symbol)

        self.chart_folder  = config.CHART_FOLDER
        self.log_folder    = config.LOG_FOLDER
        self.report_folder = getattr(config, "REPORT_FOLDER", "data/reports")

        for d in (self.chart_folder, self.log_folder, self.report_folder):
            os.makedirs(d, exist_ok=True)

        self.active_trade_log: Optional[dict] = None

        # ── Cache Daily Bias ────────────────────────────────────────
        # Lưu lại kết quả AI Stage 1 và payload số của Daily
        # Key: (date_str, trigger_hour) để xác định duy nhất mỗi session
        self._daily_cache: dict = {
            "trigger_key":  None,   # (date_str, trigger_hour)
            "daily_result": None,
            "daily_payload": None,
            "daily_img":    None,
        }

        # ── Cache H1 Result ─────────────────────────────────────────
        # Lưu lại kết quả AI Stage 2 và payload H1
        # Cập nhật mỗi khi giờ UTC thay đổi (nến H1 mới)
        self._h1_cache: dict = {
            "hour_key":   None,   # (date_str, hour_int)
            "h1_result":  None,
            "h1_payload": None,
            "h1_img":     None,
        }

        print("🤖 [BOT V2.1 ICT] Khởi tạo xong. Sẵn sàng giao dịch.\n")

    # ══════════════════════════════════════════════════════════════
    # VÒNG LẶP CHÍNH
    # ══════════════════════════════════════════════════════════════

    def run(self, timeframe: int = mt5.TIMEFRAME_M5):
        last_checked_candle_time = 0
        print("▶️  Bot đang chạy. Ctrl+C để dừng.\n")

        while True:
            try:
                current_candle_time = MT5Util.get_current_open_time(self.symbol, timeframe)

                if current_candle_time <= last_checked_candle_time:
                    time.sleep(1)
                    continue

                now_utc = datetime.datetime.utcnow()
                now_loc = datetime.datetime.now()
                print(f"\n{'─'*60}")
                print(f"🕯️  Nến M5 mới | {now_loc.strftime('%Y-%m-%d %H:%M:%S')} local "
                      f"| {now_utc.strftime('%H:%M')} GMT")
                last_checked_candle_time = current_candle_time

                # ── Force close Thứ 6 ─────────────────────────
                if SessionFilter.should_force_close_friday(now_loc):
                    print("📅 [THỨ 6] Qua giờ force-close. Đóng tất cả lệnh...")
                    self.trailing_manager.force_close_all()
                    self._check_and_log_previous_trade()
                    time.sleep(10)
                    continue

                # ── Trailing SL ───────────────────────────────
                updated = self.trailing_manager.update()
                if updated:
                    print(f"🔄 [TRAIL] Cập nhật SL cho {len(updated)} lệnh: {updated}")

                # ── Kiểm tra lệnh cũ ──────────────────────────
                self._check_and_log_previous_trade()

                # ── Bỏ qua nếu đang có lệnh ──────────────────
                has_position = (
                    self.active_trade_log is not None or
                    MT5Util.is_existing_position(self.symbol, self.magic_number)
                )
                if has_position:
                    print("🚫 Đang có lệnh mở. Bỏ qua phân tích.")
                    continue

                # ── Kiểm tra phiên giao dịch ─────────────────
                allowed, reason = SessionFilter.is_allowed_now(now_loc)
                if not allowed:
                    print(f"⏸️  [{reason}] – Không vào lệnh.")
                    continue
                print(f"✅ Phiên: {reason}")

                # ── Pipeline ICT 3 stage ──────────────────────
                pipeline = self._run_ict_pipeline(now_utc)
                action   = pipeline.get("final_action", "HOLD")

                print(f"\n{'═'*60}")
                print(f"  🎯  KẾT QUẢ PIPELINE ICT:  {action}")
                print(f"{'═'*60}")

                # ── HOLD ──────────────────────────────────────
                if action not in ("BUY", "SELL"):
                    log = self._build_log(
                        action, pipeline,
                        ticket="NO_ORDER", sl_pts=0,
                        risk_usd=0, lot=0,
                        profit=0, result="HOLD"
                    )
                    self._write_to_csv(log)
                    # Tạo PDF report cho phiên HOLD
                    self._generate_report(pipeline, now_utc, trade_info=None)
                    continue

                # ── Tính SL ───────────────────────────────────
                prev_m5  = MT5Util.get_last_close_candle_info(self.symbol, timeframe)
                sym_info = mt5.symbol_info(self.symbol)
                point    = sym_info.point
                digits   = sym_info.digits

                if action == "BUY":
                    position_type = mt5.ORDER_TYPE_BUY
                    tick_price    = mt5.symbol_info_tick(self.symbol).ask
                    sl_price      = round(prev_m5['low'] - self.spreads * point, digits)
                    sl_pts        = (tick_price - sl_price) / point
                else:
                    position_type = mt5.ORDER_TYPE_SELL
                    tick_price    = mt5.symbol_info_tick(self.symbol).bid
                    sl_price      = round(prev_m5['high'] + self.spreads * point, digits)
                    sl_pts        = (sl_price - tick_price) / point

                sl_pts = max(sl_pts, 50)

                account      = mt5.account_info()
                equity       = account.equity
                default_risk = equity * (self.risk_percent / 100.0)
                last_profit  = MT5Util.get_last_closed_deal_profit(self.symbol, self.magic_number)
                final_risk   = (
                    last_profit / 2
                    if last_profit > default_risk * 2
                    else default_risk
                )

                lot = MT5Util.calculate_volume_by_cash(self.symbol, sl_pts, final_risk)
                ticket = MT5Util.open_position(
                    self.symbol, lot, position_type, sl_pts,
                    rr=self.rr, magic_number=self.magic_number,
                    comment=f"ICT_V2_{action}"
                )

                if ticket:
                    self.trailing_manager.register_trade(
                        ticket=ticket, open_price=tick_price,
                        initial_sl=sl_price, initial_risk_pts=sl_pts,
                        position_type=position_type,
                    )
                    trade_info_dict = {
                        "action":   action,
                        "ticket":   ticket,
                        "lot":      lot,
                        "sl_pts":   round(sl_pts, 1),
                        "risk_usd": round(final_risk, 2),
                        "tp":       pipeline.get("stage3_m5", {}).get("tp_reference", "—"),
                        "result":   "PENDING",
                        "profit":   "PENDING",
                    }
                    self.active_trade_log = self._build_log(
                        action, pipeline,
                        ticket=ticket, sl_pts=round(sl_pts, 1),
                        risk_usd=round(final_risk, 2), lot=lot,
                        profit="PENDING", result="PENDING"
                    )
                    # PDF report ngay khi mở lệnh
                    self._generate_report(pipeline, now_utc, trade_info=trade_info_dict)
                    print(f"⏳ Đang theo dõi Ticket={ticket}...")
                else:
                    print("❌ Vào lệnh thất bại.")

            except KeyboardInterrupt:
                print("\n🛑 Bot dừng theo yêu cầu người dùng.")
                MT5Util.disconnect()
                break
            except Exception as e:
                print(f"❌ [BOT ERROR] {e}")
                import traceback
                traceback.print_exc()
                time.sleep(10)

    # ══════════════════════════════════════════════════════════════
    # PIPELINE ICT 3 STAGE — CÓ CACHE
    # ══════════════════════════════════════════════════════════════

    def _run_ict_pipeline(self, now_utc: datetime.datetime) -> dict:
        """
        Stage 1 (Daily Bias): chỉ chạy tại 0h/4h/8h/12h GMT.
        Stage 2 (H1):         chỉ chạy khi giờ UTC thay đổi.
        Stage 3 (M5):         chạy mỗi nến M5 mới.
        """
        EMPTY = {
            "final_action": "HOLD", "pipeline_ok": False,
            "stage1_daily": None, "stage2_h1": None, "stage3_m5": None,
            "daily_img": "", "h1_img": "", "m5_img": "",
        }

        # ── Lấy dữ liệu đa TF ────────────────────────────────────
        try:
            df_daily, df_h1, df_m5 = MT5Util.get_multi_tf_data(
                self.symbol,
                h1_count=config.H1_FETCH_COUNT,
                h1_window=config.H1_CHART_WINDOW,
                m5_window=config.M5_CHART_WINDOW,
            )
        except Exception as e:
            print(f"❌ [DATA] Lỗi lấy dữ liệu MT5: {e}")
            return EMPTY

        date_str     = now_utc.strftime("%Y%m%d")
        trigger_hour = get_daily_bias_trigger_hour(now_utc.hour)
        trigger_key  = (date_str, trigger_hour)
        hour_key     = (date_str, now_utc.hour)

        # ══════════════════════════════════════════════
        # STAGE 1: DAILY BIAS (cache 4h)
        # ══════════════════════════════════════════════
        if self._daily_cache["trigger_key"] != trigger_key:
            print(f"🔄 [DAILY] Cập nhật Daily Bias tại trigger={trigger_hour:02d}h GMT...")
            try:
                daily_img, daily_payload = DailyBiasUtil.generate_daily_chart(
                    df_daily, folder=self.chart_folder
                )
            except Exception as e:
                print(f"❌ [CHART-D] {e}")
                return EMPTY

            daily_result = self.agent.analyze_daily(daily_img, daily_payload)
            if not daily_result:
                return {**EMPTY, "stage1_daily": None}

            # Lưu cache
            self._daily_cache.update({
                "trigger_key":  trigger_key,
                "daily_result": daily_result,
                "daily_payload": daily_payload,
                "daily_img":    daily_img,
            })

            daily_bias = daily_result.get("daily_bias", "NEUTRAL")
            print(f"📊 [DAILY NEW] Bias={daily_bias} | "
                  f"Confidence={daily_result.get('confidence_score')} | "
                  f"DOL={daily_result.get('draw_on_liquidity')}")

            # Khi Daily Bias mới → invalidate H1 cache để buộc refresh
            self._h1_cache["hour_key"] = None

        else:
            daily_result  = self._daily_cache["daily_result"]
            daily_payload = self._daily_cache["daily_payload"]
            daily_img     = self._daily_cache["daily_img"]
            daily_bias    = daily_result.get("daily_bias", "NEUTRAL")
            print(f"♻️  [DAILY CACHE] Bias={daily_bias} | trigger={trigger_hour:02d}h GMT")

        # ══════════════════════════════════════════════
        # STAGE 2: H1 STRUCTURE (cache per-hour)
        # ══════════════════════════════════════════════
        if self._h1_cache["hour_key"] != hour_key:
            print(f"🔄 [H1] Cập nhật H1 Structure tại {now_utc.strftime('%H:%M')} GMT...")
            try:
                h1_img, h1_payload = H1StructureUtil.generate_h1_chart(
                    df_h1,
                    daily_bias=daily_bias,
                    daily_payload=daily_payload,
                    folder=self.chart_folder,
                )
            except Exception as e:
                print(f"❌ [CHART-H1] {e}")
                return {**EMPTY, "stage1_daily": daily_result,
                        "daily_img": daily_img}

            # Bổ sung PDH/PDL vào h1_payload
            h1_payload['pdh'] = daily_payload['yesterday_anchors']['PDH']
            h1_payload['pdl'] = daily_payload['yesterday_anchors']['PDL']

            h1_result = self.agent.analyze_h1(h1_img, daily_bias, h1_payload)
            if not h1_result:
                return {**EMPTY, "stage1_daily": daily_result,
                        "daily_img": daily_img}

            # Lưu cache H1
            self._h1_cache.update({
                "hour_key":  hour_key,
                "h1_result": h1_result,
                "h1_payload": h1_payload,
                "h1_img":    h1_img,
            })

            print(f"📊 [H1 NEW] Trend={h1_result.get('h1_trend')} | "
                  f"POI={h1_result.get('key_poi')} | "
                  f"Confidence={h1_result.get('confidence_score')}")
        else:
            h1_result  = self._h1_cache["h1_result"]
            h1_payload = self._h1_cache["h1_payload"]
            h1_img     = self._h1_cache["h1_img"]
            print(f"♻️  [H1 CACHE] Trend={h1_result.get('h1_trend')} | "
                  f"{now_utc.strftime('%H:%M')} GMT")

        # ══════════════════════════════════════════════
        # STAGE 3: M5 ENTRY (mỗi nến M5)
        # ══════════════════════════════════════════════
        try:
            m5_img, m5_payload = M5EntryUtil.generate_m5_chart(
                df_m5,
                daily_bias=daily_bias,
                h1_payload=h1_payload,
                folder=self.chart_folder,
            )
        except Exception as e:
            print(f"❌ [CHART-M5] {e}")
            return {
                **EMPTY,
                "stage1_daily": daily_result, "stage2_h1": h1_result,
                "daily_img": daily_img, "h1_img": h1_img,
                "daily_payload": daily_payload, "h1_payload": h1_payload,
            }

        m5_result = self.agent.analyze_m5(m5_img, daily_bias, h1_result, m5_payload)
        if not m5_result:
            return {
                **EMPTY,
                "stage1_daily": daily_result, "stage2_h1": h1_result,
                "daily_img": daily_img, "h1_img": h1_img,
                "daily_payload": daily_payload, "h1_payload": h1_payload,
            }

        print(f"🎯 [M5] Action={m5_result.get('action')} | "
              f"Confidence={m5_result.get('confidence_score')}")
        print(f"   Entry: {m5_result.get('entry_zone')}")
        print(f"   Reason: {m5_result.get('geometry_reason')}")

        return {
            "final_action":  m5_result.get("action", "HOLD"),
            "pipeline_ok":   True,
            "stage1_daily":  daily_result,
            "stage2_h1":     h1_result,
            "stage3_m5":     m5_result,
            "daily_img":     daily_img,
            "h1_img":        h1_img,
            "m5_img":        m5_img,
            "daily_payload": daily_payload,
            "h1_payload":    h1_payload,
            "m5_payload":    m5_payload,
            "trigger_hour":  trigger_hour,
        }

    # ══════════════════════════════════════════════════════════════
    # PDF REPORT
    # ══════════════════════════════════════════════════════════════

    def _generate_report(
        self,
        pipeline: dict,
        now_utc: datetime.datetime,
        trade_info: Optional[dict],
    ):
        """Tạo PDF báo cáo phiên phân tích và lưu vào report_folder."""
        try:
            trigger_hour = pipeline.get("trigger_hour", get_daily_bias_trigger_hour(now_utc.hour))
            output_path  = build_report_path(
                self.report_folder, self.symbol, trigger_hour, now_utc
            )
            # Thêm timestamp M5 vào tên để mỗi lần tạo file riêng
            base, ext = os.path.splitext(output_path)
            output_path = f"{base}_{now_utc.strftime('%H%M')}{ext}"

            generate_session_report(
                output_path    = output_path,
                symbol         = self.symbol,
                session_time   = now_utc.strftime("%Y-%m-%d %H:%M GMT"),
                bias_trigger_hour = trigger_hour,
                daily_result   = pipeline.get("stage1_daily"),
                h1_result      = pipeline.get("stage2_h1"),
                m5_result      = pipeline.get("stage3_m5"),
                daily_payload  = pipeline.get("daily_payload"),
                h1_payload     = pipeline.get("h1_payload"),
                m5_payload     = pipeline.get("m5_payload"),
                daily_img      = pipeline.get("daily_img", ""),
                h1_img         = pipeline.get("h1_img", ""),
                m5_img         = pipeline.get("m5_img", ""),
                trade_info     = trade_info,
            )
        except Exception as e:
            print(f"⚠️  [REPORT] Lỗi tạo PDF: {e}")
            import traceback; traceback.print_exc()

    # ══════════════════════════════════════════════════════════════
    # KIỂM TRA & LOG LỆNH CŨ
    # ══════════════════════════════════════════════════════════════

    def _check_and_log_previous_trade(self):
        if self.active_trade_log is None:
            return

        ticket    = self.active_trade_log["MT5_Ticket"]
        positions = mt5.positions_get(ticket=ticket)

        if positions is None or len(positions) == 0:
            print(f"✅ [LOG] Lệnh Ticket={ticket} đã đóng. Ghi kết quả...")
            result = MT5Util.get_deal_result_by_ticket(ticket)
            now    = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            self.active_trade_log["Close_Timestamp"] = now
            self.active_trade_log["Real_Profit_USD"] = result["profit"]
            self.active_trade_log["Trade_Result"]    = result["result"]

            self._write_to_csv(self.active_trade_log)
            self.trailing_manager.unregister(ticket)
            self.active_trade_log = None
        else:
            pos = positions[0]
            print(f"⏳ Ticket={ticket} đang chạy | P&L={pos.profit:.2f} USD")

    # ══════════════════════════════════════════════════════════════
    # LOGGING CSV
    # ══════════════════════════════════════════════════════════════

    def _write_to_csv(self, log_data: dict):
        today_str = datetime.datetime.now().strftime("%Y%m%d")
        path      = os.path.join(self.log_folder, f"trading_log_{today_str}.csv")

        if os.path.exists(path):
            try:
                df = pd.read_csv(path)
                df = pd.concat([df, pd.DataFrame([log_data])], ignore_index=True)
            except Exception:
                df = pd.DataFrame([log_data])
        else:
            df = pd.DataFrame([log_data])

        df.to_csv(path, index=False, encoding="utf-8-sig")
        print(f"📝 Log → {path}")

    def _build_log(
        self, action: str, pipeline: dict,
        ticket, sl_pts, risk_usd, lot, profit, result
    ) -> dict:
        now     = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        daily_r = pipeline.get("stage1_daily") or {}
        h1_r    = pipeline.get("stage2_h1")    or {}
        m5_r    = pipeline.get("stage3_m5")    or {}
        ltf     = daily_r.get("ltf_execution_context") or {}

        return {
            "Open_Timestamp":    now,
            "Close_Timestamp":   now if result == "HOLD" else "PENDING",
            "Symbol":            self.symbol,
            "Action":            action,
            "Daily_Trigger_H":   pipeline.get("trigger_hour", "—"),

            "Daily_Bias":              daily_r.get("daily_bias", ""),
            "Daily_Confidence":        daily_r.get("confidence_score", ""),
            "Daily_Market_State":      daily_r.get("current_market_state", ""),
            "Daily_DOL":               daily_r.get("draw_on_liquidity", ""),
            "Daily_LTF_Scenario":      ltf.get("primary_scenario", ""),
            "Daily_Invalidation":      ltf.get("invalidation_level", ""),

            "H1_Trend":          h1_r.get("h1_trend", ""),
            "H1_Confidence":     h1_r.get("confidence_score", ""),
            "H1_POI":            h1_r.get("key_poi", ""),
            "H1_Scenario":       h1_r.get("h1_scenario", ""),

            "M5_Action":         m5_r.get("action", ""),
            "M5_Confidence":     m5_r.get("confidence_score", ""),
            "M5_Entry_Zone":     m5_r.get("entry_zone", ""),
            "M5_SL_Ref":         m5_r.get("sl_reference", ""),
            "M5_TP_Ref":         m5_r.get("tp_reference", ""),
            "M5_Geometry_Reason":m5_r.get("geometry_reason", ""),

            "SL_Points":         sl_pts,
            "Risk_USD":          risk_usd,
            "Lot":               lot,
            "MT5_Ticket":        ticket,
            "Real_Profit_USD":   profit,
            "Trade_Result":      result,

            "Daily_Chart":       pipeline.get("daily_img", ""),
            "H1_Chart":          pipeline.get("h1_img", ""),
            "M5_Chart":          pipeline.get("m5_img", ""),
        }
