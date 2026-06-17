"""
bot/core/order_manager.py
==========================
OrderManager — tính toán và thực thi lệnh ICT pullback.

Tách biệt hoàn toàn khỏi Trader (vòng lặp) và Pipeline (phân tích).
Trách nhiệm:
  - Tính SL từ swing M5 (pullback method)
  - Parse TP từ H1TradingContext.target string
  - Tính lot theo risk %
  - Gọi MT5Util.open_position()
"""

import re
import datetime
from typing import Optional, Dict, Tuple

import MetaTrader5 as mt5

import config
from bot.broker.mt5 import MT5Util


class OrderManager:

    def __init__(self, symbol: str, magic: int):
        self.symbol  = symbol
        self.magic   = magic
        self._spreads = config.SPREADS
        self._risk_pct = config.RISK_PERCENT

    # ── Entry point chính ────────────────────────────────────────

    def prepare_and_open(
        self,
        action:    str,         # "BUY" or "SELL"
        pipeline:  Dict,
        timeframe: int,
    ) -> Optional[Dict]:
        """
        Tính SL, TP, lot rồi mở lệnh.

        Returns dict {ticket, open_price, sl_price, tp_price,
                       sl_pts, risk_usd, lot, actual_rr}
        hoặc None nếu thất bại.
        """
        si    = MT5Util.get_symbol_info(self.symbol)
        tick  = MT5Util.get_tick(self.symbol)
        if si is None or tick is None:
            print("❌ [OM] Không lấy được symbol/tick info.")
            return None

        point  = si.point
        digits = si.digits

        # ── 1. Giá entry & SL ────────────────────────────────────
        m5_payload = pipeline.get("m5_payload") or {}

        if action == "BUY":
            position_type = mt5.ORDER_TYPE_BUY
            entry_price   = tick.ask
            swing_sl      = m5_payload.get("swing_low_for_sl")
            if swing_sl:
                sl_price = round(swing_sl - self._spreads * point, digits)
            else:
                prev = MT5Util.get_last_closed_candle(self.symbol, timeframe)
                sl_price = round(prev["low"] - self._spreads * point, digits)
                print("⚠️  [OM] Swing low không tìm được, dùng low nến trước.")
            sl_pts = (entry_price - sl_price) / point

        else:  # SELL
            position_type = mt5.ORDER_TYPE_SELL
            entry_price   = tick.bid
            swing_sl      = m5_payload.get("swing_high_for_sl")
            if swing_sl:
                sl_price = round(swing_sl + self._spreads * point, digits)
            else:
                prev = MT5Util.get_last_closed_candle(self.symbol, timeframe)
                sl_price = round(prev["high"] + self._spreads * point, digits)
                print("⚠️  [OM] Swing high không tìm được, dùng high nến trước.")
            sl_pts = (sl_price - entry_price) / point

        sl_pts = max(sl_pts, 50)
        print(f"📏 [OM] SL: swing={swing_sl} → sl_price={sl_price} | sl_pts={sl_pts:.1f}")

        # ── 2. TP từ H1 target ───────────────────────────────────
        h1_target_str = (pipeline.get("stage2_h1") or {}).get("target", "")
        tp_price = self._parse_tp(h1_target_str, entry_price, action,
                                  sl_pts, point, digits)
        tp_dist   = abs(tp_price - entry_price)
        actual_rr = round(tp_dist / (sl_pts * point), 2) if sl_pts > 0 else "?"
        print(f"🎯 [OM] TP={tp_price} | Actual RR≈{actual_rr}R")

        # ── 3. Risk & lot ────────────────────────────────────────
        equity       = MT5Util.get_account_equity()
        default_risk = equity * (self._risk_pct / 100.0)
        last_profit  = MT5Util.get_last_closed_profit(self.symbol, self.magic)
        risk_usd     = (last_profit / 2
                        if last_profit > default_risk * 2
                        else default_risk)
        lot = MT5Util.calc_lot(self.symbol, sl_pts, risk_usd)
        print(f"💰 [OM] Equity={equity:.2f} | Risk={risk_usd:.2f} USD | Lot={lot}")

        # ── 4. Mở lệnh ───────────────────────────────────────────
        ticket = MT5Util.open_position(
            symbol        = self.symbol,
            lot           = lot,
            position_type = position_type,
            sl_price      = sl_price,
            tp_price      = tp_price,
            magic         = self.magic,
            comment       = f"ICT_V3_{action}",
        )
        if ticket is None:
            return None

        return {
            "ticket":      ticket,
            "open_price":  entry_price,
            "sl_price":    sl_price,
            "tp_price":    tp_price,
            "sl_pts":      round(sl_pts, 1),
            "risk_usd":    round(risk_usd, 2),
            "lot":         lot,
            "actual_rr":   actual_rr,
            "position_type": position_type,
        }

    # ── TP parser ────────────────────────────────────────────────

    @staticmethod
    def _parse_tp(
        target_str:  str,
        entry_price: float,
        action:      str,
        sl_pts:      float,
        point:       float,
        digits:      int,
        min_rr:      float = 1.5,
    ) -> float:
        """
        Trích xuất giá TP từ chuỗi H1TradingContext.target.
        Ví dụ: "BSL tại 2345.50 — đỉnh swing H1"  →  2345.50
        Fallback: entry ± min_rr × sl_pts × point
        """
        nums = re.findall(r"\d{3,6}(?:[.,]\d{1,2})?", target_str or "")
        for n in nums:
            try:
                price = float(n.replace(",", "."))
                if action == "BUY"  and price > entry_price:
                    return round(price, digits)
                if action == "SELL" and price < entry_price:
                    return round(price, digits)
            except ValueError:
                continue

        print(f"⚠️  [OM] Không parse được TP từ '{target_str}', fallback {min_rr}R")
        offset = sl_pts * point * min_rr
        if action == "BUY":
            return round(entry_price + offset, digits)
        return round(entry_price - offset, digits)
