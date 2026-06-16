"""
trader.py  (V2 - ICT Multi-Timeframe, Hoàn chỉnh)
===================================================
Kế thừa toàn bộ kiến trúc v1, bổ sung:
  - Pipeline 3-stage ICT: Daily Bias → H1 Structure → M5 Entry
  - Bộ lọc phiên giao dịch (SessionFilter)
  - Trailing Stop Loss tự động (TrailingStopManager)
  - Force-close Thứ 6
  - Log đầy đủ 3 stage vào CSV
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

        # ── Kết nối MT5 ─────────────────────────────────────────
        MT5Util.init_mt5(username, password, server, symbol)

        # ── AI Agent 3-stage ────────────────────────────────────
        self.agent = ICTAIAgent(api_key=api_key, model_name=model_name)

        # ── Session Filter & Trailing SL ────────────────────────
        self.session_filter  = SessionFilter()
        self.trailing_manager = TrailingStopManager(symbol)

        # ── Thư mục output ──────────────────────────────────────
        self.chart_folder = config.CHART_FOLDER
        self.log_folder   = config.LOG_FOLDER
        os.makedirs(self.chart_folder, exist_ok=True)
        os.makedirs(self.log_folder,   exist_ok=True)

        # Lệnh đang theo dõi (chưa được log kết quả)
        self.active_trade_log: Optional[dict] = None

        print("🤖 [BOT V2 ICT] Khởi tạo xong. Sẵn sàng giao dịch.\n")

    # ══════════════════════════════════════════════════════════════
    # VÒNG LẶP CHÍNH
    # ══════════════════════════════════════════════════════════════
    def run(self, timeframe: int = mt5.TIMEFRAME_M5):
        last_checked_candle_time = 0
        print("▶️  Bot đang chạy. Ctrl+C để dừng.\n")

        while True:
            try:
                current_candle_time = MT5Util.get_current_open_time(self.symbol, timeframe)

                # Chờ nến mới
                if current_candle_time <= last_checked_candle_time:
                    time.sleep(1)
                    continue

                now = datetime.datetime.now()
                print(f"\n{'─'*60}")
                print(f"🕯️  Nến M5 mới | {now.strftime('%Y-%m-%d %H:%M:%S')}")
                last_checked_candle_time = current_candle_time

                # ── Force close Thứ 6 ─────────────────────────
                if SessionFilter.should_force_close_friday(now):
                    print("📅 [THỨU 6] Qua giờ force-close. Đóng tất cả lệnh...")
                    self.trailing_manager.force_close_all()
                    self._check_and_log_previous_trade()
                    time.sleep(10)
                    continue

                # ── Cập nhật Trailing SL ──────────────────────
                updated = self.trailing_manager.update()
                if updated:
                    print(f"🔄 [TRAIL] Đã cập nhật SL cho {len(updated)} lệnh: {updated}")

                # ── Kiểm tra & log lệnh cũ ───────────────────
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
                allowed, reason = SessionFilter.is_allowed_now(now)
                if not allowed:
                    print(f"⏸️  [{reason}] – Không vào lệnh.")
                    continue
                print(f"✅ Phiên: {reason}")

                # ── Chạy pipeline ICT 3 stage ─────────────────
                pipeline = self._run_ict_pipeline()
                action   = pipeline.get("final_action", "HOLD")

                print(f"\n{'═'*60}")
                print(f"  🎯  KẾT QUẢ PIPELINE ICT:  {action}")
                print(f"{'═'*60}")

                # ── HOLD: log và bỏ qua ───────────────────────
                if action not in ("BUY", "SELL"):
                    self._write_to_csv(self._build_log(
                        action, pipeline,
                        ticket="NO_ORDER", sl_pts=0,
                        risk_usd=0, lot=0,
                        profit=0, result="HOLD"
                    ))
                    continue

                # ── Tính SL theo nến M5 vừa đóng ─────────────
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

                # Tối thiểu 50 points để tránh SL quá hẹp
                sl_pts = max(sl_pts, 50)

                # ── Tính Risk USD ─────────────────────────────
                account      = mt5.account_info()
                equity       = account.equity
                default_risk = equity * (self.risk_percent / 100.0)

                last_profit  = MT5Util.get_last_closed_deal_profit(
                    self.symbol, self.magic_number
                )
                final_risk   = (
                    last_profit / 2
                    if last_profit > default_risk * 2
                    else default_risk
                )

                # ── Tính lot và vào lệnh ─────────────────────
                lot = MT5Util.calculate_volume_by_cash(
                    self.symbol, sl_pts, final_risk
                )
                ticket = MT5Util.open_position(
                    self.symbol, lot, position_type, sl_pts,
                    rr=self.rr,
                    magic_number=self.magic_number,
                    comment=f"ICT_V2_{action}"
                )

                if ticket:
                    # Đăng ký trailing
                    self.trailing_manager.register_trade(
                        ticket=ticket,
                        open_price=tick_price,
                        initial_sl=sl_price,
                        initial_risk_pts=sl_pts,
                        position_type=position_type,
                    )
                    # Lưu log tạm (chưa ghi CSV, chờ lệnh đóng)
                    self.active_trade_log = self._build_log(
                        action, pipeline,
                        ticket=ticket,
                        sl_pts=round(sl_pts, 1),
                        risk_usd=round(final_risk, 2),
                        lot=lot,
                        profit="PENDING",
                        result="PENDING"
                    )
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
    # PIPELINE ICT 3 STAGE
    # ══════════════════════════════════════════════════════════════
    def _run_ict_pipeline(self) -> dict:
        """Lấy dữ liệu 3 TF → tạo chart → gọi AI → trả về kết quả."""

        EMPTY = {
            "final_action": "HOLD", "pipeline_ok": False,
            "stage1_daily": None, "stage2_h1": None, "stage3_m5": None
        }

        # ── 1. Lấy dữ liệu từ MT5 ──────────────────────────────
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

        # ── 2. Chart Daily + payload ────────────────────────────
        try:
            daily_img, daily_payload = DailyBiasUtil.generate_daily_chart(
                df_daily, folder=self.chart_folder
            )
        except Exception as e:
            print(f"❌ [CHART-D] {e}")
            return EMPTY

        # ── Stage 1: AI → Daily Bias ────────────────────────────
        daily_result = self.agent.analyze_daily(daily_img, daily_payload)
        if not daily_result:
            return {**EMPTY, "stage1_daily": None}

        daily_bias = daily_result.get("daily_bias", "NEUTRAL")
        print(f"\n📊 Daily Bias={daily_bias} | Confidence={daily_result.get('confidence_score')}")
        print(f"   DOL: {daily_result.get('draw_on_liquidity')}")
        print(f"   Kịch bản LTF: {daily_result.get('ltf_execution_context', {}).get('primary_scenario', '')}")

        # ── 3. Chart H1 + payload ───────────────────────────────
        try:
            h1_img, h1_payload = H1StructureUtil.generate_h1_chart(
                df_h1,
                daily_bias=daily_bias,
                daily_payload=daily_payload,
                folder=self.chart_folder,
            )
        except Exception as e:
            print(f"❌ [CHART-H1] {e}")
            return {**EMPTY, "stage1_daily": daily_result}

        # Bổ sung PDH/PDL vào h1_payload để M5 dùng làm reference
        h1_payload['pdh'] = daily_payload['yesterday_anchors']['PDH']
        h1_payload['pdl'] = daily_payload['yesterday_anchors']['PDL']

        # ── Stage 2: AI → H1 Context ────────────────────────────
        h1_result = self.agent.analyze_h1(h1_img, daily_bias, h1_payload)
        if not h1_result:
            return {**EMPTY, "stage1_daily": daily_result, "stage2_h1": None}

        print(f"📊 H1 Trend={h1_result.get('h1_trend')} | Confidence={h1_result.get('confidence_score')}")
        print(f"   POI: {h1_result.get('key_poi')}")
        print(f"   Kịch bản: {h1_result.get('h1_scenario')}")

        # ── 4. Chart M5 + payload ───────────────────────────────
        try:
            m5_img, m5_payload = M5EntryUtil.generate_m5_chart(
                df_m5,
                daily_bias=daily_bias,
                h1_payload=h1_payload,
                folder=self.chart_folder,
            )
        except Exception as e:
            print(f"❌ [CHART-M5] {e}")
            return {**EMPTY, "stage1_daily": daily_result, "stage2_h1": h1_result}

        # ── Stage 3: AI → M5 Entry ──────────────────────────────
        m5_result = self.agent.analyze_m5(m5_img, daily_bias, h1_result, m5_payload)
        if not m5_result:
            return {**EMPTY, "stage1_daily": daily_result, "stage2_h1": h1_result}

        print(f"🎯 M5 Action={m5_result.get('action')} | Confidence={m5_result.get('confidence_score')}")
        print(f"   Entry: {m5_result.get('entry_zone')}")
        print(f"   SL   : {m5_result.get('sl_reference')}")
        print(f"   TP   : {m5_result.get('tp_reference')}")
        print(f"   Lý do: {m5_result.get('geometry_reason')}")

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
        }

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
            # ── Thời gian ─────────────────────
            "Open_Timestamp":    now,
            "Close_Timestamp":   now if result == "HOLD" else "PENDING",
            "Symbol":            self.symbol,
            "Action":            action,

            # ── Daily Stage ───────────────────
            "Daily_Bias":              daily_r.get("daily_bias", ""),
            "Daily_Confidence":        daily_r.get("confidence_score", ""),
            "Daily_Market_State":      daily_r.get("current_market_state", ""),
            "Daily_DOL":               daily_r.get("draw_on_liquidity", ""),
            "Daily_LTF_Scenario":      ltf.get("primary_scenario", ""),
            "Daily_Invalidation":      ltf.get("invalidation_level", ""),

            # ── H1 Stage ──────────────────────
            "H1_Trend":          h1_r.get("h1_trend", ""),
            "H1_Confidence":     h1_r.get("confidence_score", ""),
            "H1_POI":            h1_r.get("key_poi", ""),
            "H1_Scenario":       h1_r.get("h1_scenario", ""),

            # ── M5 Stage ──────────────────────
            "M5_Action":         m5_r.get("action", ""),
            "M5_Confidence":     m5_r.get("confidence_score", ""),
            "M5_Entry_Zone":     m5_r.get("entry_zone", ""),
            "M5_SL_Ref":         m5_r.get("sl_reference", ""),
            "M5_TP_Ref":         m5_r.get("tp_reference", ""),
            "M5_Geometry_Reason":m5_r.get("geometry_reason", ""),

            # ── Lệnh ──────────────────────────
            "SL_Points":         sl_pts,
            "Risk_USD":          risk_usd,
            "Lot":               lot,
            "MT5_Ticket":        ticket,
            "Real_Profit_USD":   profit,
            "Trade_Result":      result,

            # ── Charts ────────────────────────
            "Daily_Chart":       pipeline.get("daily_img", ""),
            "H1_Chart":          pipeline.get("h1_img", ""),
            "M5_Chart":          pipeline.get("m5_img", ""),
        }
