"""
bot/core/trader.py
==================
Trader — vòng lặp chính của bot. Chỉ điều phối, không có logic nghiệp vụ.

Mỗi nến M5:
  1. Kiểm tra force-close Thứ 6
  2. Update TradeManager (partial close / BE / trailing)
  3. Kiểm tra và log lệnh đã đóng
  4. Bỏ qua nếu đang có lệnh mở hoặc ngoài phiên
  5. Chạy ICTPipeline → nhận PipelineResult
  6. Nếu BUY/SELL → OrderManager mở lệnh, TradeManager đăng ký
  7. Tạo PDF report và ghi CSV
"""

import time
import datetime
import traceback
import MetaTrader5 as mt5

import config
from bot.broker.mt5           import MT5Util
from bot.ai.agent             import ICTAIAgent
from bot.core.pipeline        import ICTPipeline
from bot.core.order_manager   import OrderManager
from bot.management.session   import SessionFilter
from bot.management.trade_manager import TradeManager
from bot.reporting.csv_logger import CSVLogger
from bot.reporting.pdf_report import generate_session_report, build_report_path


class Trader:

    def __init__(self):
        # ── Kết nối MT5 ─────────────────────────────────────────
        MT5Util.init(
            config.MT5_USERNAME, config.MT5_PASSWORD,
            config.MT5_SERVER,   config.MT5_SYMBOL,
        )
        symbol = config.MT5_SYMBOL

        # ── Các sub-components ───────────────────────────────────
        agent              = ICTAIAgent(config.GEMINI_API_KEY, config.GEMINI_MODEL)
        self.pipeline      = ICTPipeline(symbol, agent)
        self.order_manager = OrderManager(symbol, config.MAGIC_NUMBER)
        self.trade_manager = TradeManager(symbol)
        self.logger        = CSVLogger(config.LOG_FOLDER)

        self.symbol        = symbol
        self.magic         = config.MAGIC_NUMBER

        # Lệnh đang theo dõi (chờ đóng để ghi CSV)
        self._active_log: dict | None = None

        print("🤖 [BOT V3] Khởi tạo xong. Sẵn sàng giao dịch.\n")

    # ══════════════════════════════════════════════════════════════
    # VÒNG LẶP CHÍNH
    # ══════════════════════════════════════════════════════════════

    def run(self, timeframe: int = mt5.TIMEFRAME_M5) -> None:
        last_candle_time = 0
        print("▶️  Bot đang chạy. Ctrl+C để dừng.\n")

        while True:
            try:
                candle_time = MT5Util.get_current_candle_time(self.symbol, timeframe)
                if candle_time <= last_candle_time:
                    time.sleep(1)
                    continue

                now_utc = datetime.datetime.utcnow()
                now_loc = datetime.datetime.now()
                last_candle_time = candle_time
                print(f"\n{'─'*60}")
                print(f"🕯️  Nến M5 | {now_loc.strftime('%Y-%m-%d %H:%M:%S')} "
                      f"| {now_utc.strftime('%H:%M')} GMT")

                # ── 1. Force close Thứ 6 ──────────────────────
                if SessionFilter.should_force_close(now_loc):
                    print("📅 [THỨ 6] Force-close tất cả lệnh...")
                    self.trade_manager.force_close_all()
                    self._finalize_active_trade()
                    time.sleep(10)
                    continue

                # ── 2. Update trade management ─────────────────
                acted = self.trade_manager.update()
                if acted:
                    print(f"🔄 [TM] Đã xử lý {len(acted)} lệnh: {acted}")

                # ── 3. Kiểm tra lệnh cũ đã đóng ───────────────
                self._finalize_active_trade()

                # ── 4. Skip nếu đang có lệnh ──────────────────
                if (self._active_log is not None
                        or MT5Util.has_open_position(self.symbol, self.magic)):
                    print("🚫 Đang có lệnh mở. Bỏ qua.")
                    continue

                # ── 5. Kiểm tra phiên ─────────────────────────
                allowed, reason = SessionFilter.is_allowed(now_loc)
                if not allowed:
                    print(f"⏸️  {reason}")
                    continue
                print(f"✅ Phiên: {reason}")

                # ── 6. Pipeline ICT ────────────────────────────
                result = self.pipeline.run(now_utc)
                action = result.get("final_action", "HOLD")
                print(f"\n{'═'*60}\n  🎯  {action}\n{'═'*60}")

                # ── 7. HOLD ────────────────────────────────────
                if action not in ("BUY", "SELL"):
                    record = CSVLogger.build_record(
                        action, result, self.symbol,
                        ticket="NO_ORDER", sl_pts=0, risk_usd=0, lot=0,
                        tp_price="—", actual_rr="—", profit=0, result="HOLD",
                    )
                    self.logger.write(record)
                    self._make_report(result, now_utc, trade_info=None)
                    continue

                # ── 8. Mở lệnh ────────────────────────────────
                order = self.order_manager.prepare_and_open(action, result, timeframe)
                if order is None:
                    print("❌ Mở lệnh thất bại.")
                    continue

                # ── 9. Đăng ký trade_manager ──────────────────
                self.trade_manager.register(
                    ticket        = order["ticket"],
                    open_price    = order["open_price"],
                    tp_price      = order["tp_price"],
                    sl_price      = order["sl_price"],
                    position_type = order["position_type"],
                    volume        = order["lot"],
                )

                # ── 10. Lưu log tạm + PDF ─────────────────────
                self._active_log = CSVLogger.build_record(
                    action, result, self.symbol,
                    ticket    = order["ticket"],
                    sl_pts    = order["sl_pts"],
                    risk_usd  = order["risk_usd"],
                    lot       = order["lot"],
                    tp_price  = order["tp_price"],
                    actual_rr = order["actual_rr"],
                    profit    = "PENDING",
                    result    = "PENDING",
                )
                trade_info = {**order, "action": action, "result": "PENDING",
                              "profit": "PENDING"}
                self._make_report(result, now_utc, trade_info=trade_info)
                print(f"⏳ Đang theo dõi Ticket={order['ticket']}...")

            except KeyboardInterrupt:
                print("\n🛑 Bot dừng.")
                MT5Util.disconnect()
                break
            except Exception as e:
                print(f"❌ [BOT ERROR] {e}")
                traceback.print_exc()
                time.sleep(10)

    # ══════════════════════════════════════════════════════════════
    # HELPERS
    # ══════════════════════════════════════════════════════════════

    def _finalize_active_trade(self) -> None:
        """Kiểm tra lệnh đang theo dõi; nếu đã đóng thì ghi CSV."""
        if self._active_log is None:
            return
        ticket    = self._active_log["MT5_Ticket"]
        positions = mt5.positions_get(ticket=ticket)
        if positions:
            pos = positions[0]
            print(f"⏳ Ticket={ticket} | P&L={pos.profit:.2f} USD")
            return

        print(f"✅ Ticket={ticket} đã đóng. Ghi log...")
        deal = MT5Util.get_deal_result(ticket)
        self._active_log["Close_Timestamp"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self._active_log["Real_Profit_USD"] = deal["profit"]
        self._active_log["Trade_Result"]    = deal["result"]
        self.logger.write(self._active_log)
        self.trade_manager.unregister(ticket)
        self._active_log = None

    def _make_report(
        self,
        pipeline: dict,
        now_utc:  datetime.datetime,
        trade_info: dict | None,
    ) -> None:
        """Tạo PDF report, bắt lỗi không crash bot."""
        try:
            trigger = pipeline.get("trigger_hour", 0)
            path    = build_report_path(
                config.REPORT_FOLDER, self.symbol, trigger, now_utc
            )
            import os; base, ext = os.path.splitext(path)
            path = f"{base}_{now_utc.strftime('%H%M')}{ext}"

            generate_session_report(
                output_path       = path,
                symbol            = self.symbol,
                session_time      = now_utc.strftime("%Y-%m-%d %H:%M GMT"),
                bias_trigger_hour = trigger,
                daily_result      = pipeline.get("stage1_daily"),
                h1_result         = pipeline.get("stage2_h1"),
                m5_result         = pipeline.get("stage3_m5"),
                daily_payload     = pipeline.get("daily_payload"),
                h1_payload        = pipeline.get("h1_payload"),
                m5_payload        = pipeline.get("m5_payload"),
                daily_img         = pipeline.get("daily_img", ""),
                h1_img            = pipeline.get("h1_img", ""),
                m5_img            = pipeline.get("m5_img", ""),
                trade_info        = trade_info,
            )
        except Exception as e:
            print(f"⚠️  [REPORT] {e}")
            traceback.print_exc()
