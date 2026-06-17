"""
bot/management/trade_manager.py
================================
TradeManager — quản lý vòng đời lệnh ICT pullback:

  1. Partial close 50% khi giá chạm half_target (midpoint entry→TP)
  2. Dời SL về Breakeven sau partial close
  3. Trailing SL tùy chọn (sau khi BE)
  4. Force close cuối tuần
"""

import math
from typing import Dict, List, Optional
import MetaTrader5 as mt5

import config
from bot.broker.mt5 import MT5Util


class TradeManager:

    def __init__(self, symbol: str):
        self.symbol  = symbol
        si           = mt5.symbol_info(symbol)
        self.point   = si.point  if si else 0.01
        self.digits  = si.digits if si else 2
        self._trades: Dict[int, Dict] = {}

    # ── Đăng ký lệnh ────────────────────────────────────────────

    def register(
        self,
        ticket:        int,
        open_price:    float,
        tp_price:      float,
        sl_price:      float,
        position_type: int,
        volume:        float,
    ) -> None:
        """
        Đăng ký lệnh mới. half_target = midpoint(open_price, tp_price).
        """
        half = (open_price + tp_price) / 2.0
        self._trades[ticket] = {
            "ticket":          ticket,
            "open_price":      open_price,
            "tp_price":        tp_price,
            "half_target":     half,
            "sl_price":        sl_price,
            "initial_sl":      sl_price,
            "position_type":   position_type,
            "original_volume": volume,
            "partial_done":    False,
            "be_done":         False,
        }
        r_dist  = abs(open_price - sl_price)
        tp_dist = abs(tp_price   - open_price)
        rr      = round(tp_dist / r_dist, 2) if r_dist > 0 else "?"
        print(
            f"📌 [TM] Ticket={ticket} | Entry={open_price} | "
            f"TP={tp_price} | SL={sl_price}\n"
            f"        Half={half:.{self.digits}f} | RR≈{rr}R | Vol={volume}"
        )

    # ── Update mỗi nến M5 ────────────────────────────────────────

    def update(self) -> List[int]:
        """
        Kiểm tra từng lệnh:
          - Nếu giá chạm half_target → partial close + BE
          - Nếu đã BE và TRAILING_ENABLED → trailing SL
        Returns: list ticket đã được xử lý.
        """
        acted = []
        for ticket, state in list(self._trades.items()):
            positions = mt5.positions_get(ticket=ticket)
            if not positions:
                print(f"🏁 [TM] Ticket={ticket} đã đóng hết, dọn dẹp.")
                del self._trades[ticket]
                continue

            pos  = positions[0]
            tick = mt5.symbol_info_tick(self.symbol)
            if tick is None:
                continue

            ptype = state["position_type"]
            cur   = tick.bid if ptype == mt5.ORDER_TYPE_BUY else tick.ask

            # ── Step 1: Partial close tại half_target ─────────
            if not state["partial_done"]:
                hit = (
                    (ptype == mt5.ORDER_TYPE_BUY  and cur >= state["half_target"]) or
                    (ptype == mt5.ORDER_TYPE_SELL and cur <= state["half_target"])
                )
                if hit:
                    close_vol = MT5Util.round_volume(self.symbol, pos.volume / 2.0)
                    ok = MT5Util.partial_close(self.symbol, ticket, close_vol, ptype)
                    if ok:
                        state["partial_done"] = True
                        acted.append(ticket)
                        print(
                            f"✂️  [TM] Partial close Ticket={ticket} | "
                            f"{close_vol} lots @ {cur:.{self.digits}f} | "
                            f"half_target={state['half_target']:.{self.digits}f}"
                        )
                        # ── Step 2: Dời SL về BE ──────────────
                        be_sl   = self._be_price(state["open_price"], ptype)
                        move_be = (
                            (ptype == mt5.ORDER_TYPE_BUY  and be_sl > state["sl_price"]) or
                            (ptype == mt5.ORDER_TYPE_SELL and be_sl < state["sl_price"])
                        )
                        if move_be and MT5Util.modify_sl_tp(ticket, be_sl, pos.tp):
                            state["sl_price"] = be_sl
                            state["be_done"]  = True
                            print(
                                f"🔐 [TM] Breakeven Ticket={ticket} | "
                                f"SL → {be_sl:.{self.digits}f}"
                            )

            # ── Step 3: Trailing SL (sau BE) ──────────────────
            if state["be_done"] and getattr(config, "TRAILING_ENABLED", False):
                self._trail(ticket, state, pos, cur, ptype)

        return acted

    # ── Force close ──────────────────────────────────────────────

    def force_close_all(self) -> None:
        MT5Util.close_all(self.symbol)

    def unregister(self, ticket: int) -> None:
        self._trades.pop(ticket, None)

    def is_tracking(self, ticket: int) -> bool:
        return ticket in self._trades

    # ── Internals ────────────────────────────────────────────────

    def _be_price(self, open_price: float, ptype: int) -> float:
        buf = getattr(config, "BE_BUFFER_POINTS", 50) * self.point
        if ptype == mt5.ORDER_TYPE_BUY:
            return round(open_price + buf, self.digits)
        return round(open_price - buf, self.digits)

    def _trail(self, ticket, state, pos, cur, ptype) -> None:
        step = getattr(config, "TRAILING_STEP_POINTS", 150) * self.point
        risk = abs(state["open_price"] - state["initial_sl"])
        if ptype == mt5.ORDER_TYPE_BUY:
            new_sl = round(cur - risk, self.digits)
            if new_sl > state["sl_price"] + step:
                if MT5Util.modify_sl_tp(ticket, new_sl, pos.tp):
                    state["sl_price"] = new_sl
                    print(f"🔼 [TM TRAIL] Ticket={ticket} SL→{new_sl:.{self.digits}f}")
        else:
            new_sl = round(cur + risk, self.digits)
            if new_sl < state["sl_price"] - step:
                if MT5Util.modify_sl_tp(ticket, new_sl, pos.tp):
                    state["sl_price"] = new_sl
                    print(f"🔽 [TM TRAIL] Ticket={ticket} SL→{new_sl:.{self.digits}f}")
