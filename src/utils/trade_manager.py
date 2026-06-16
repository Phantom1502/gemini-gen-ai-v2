"""
trade_manager.py  (V2.2)
========================
Quản lý lệnh đang mở theo phương pháp ICT Pullback:

  1. PARTIAL CLOSE tại 50% target:
     - Khi giá chạm half_target (midpoint entry → TP) → đóng 50% volume
     - Sau đó dời SL về Breakeven (giá mở lệnh ± buffer nhỏ)
     - Phần còn lại (50%) để chạy đến full target

  2. TRAILING SL (tùy chọn, chỉ kích hoạt sau khi đã partial close):
     - Sau khi partial close + SL về BE, nếu TRAILING_ENABLED=True
       thì tiếp tục dịch SL theo giá (mỗi TRAILING_STEP_POINTS)

  3. FORCE CLOSE cuối tuần:
     - Đóng toàn bộ lệnh Thứ 6 sau FORCE_CLOSE_FRIDAY_TIME

Cấu trúc state mỗi lệnh:
  {
    ticket          : int
    open_price      : float         # giá mở lệnh (entry)
    tp_price        : float         # full target (từ H1TradingContext)
    half_target     : float         # midpoint entry → tp (trigger partial close)
    sl_price        : float         # SL hiện tại
    initial_sl      : float         # SL ban đầu (để tính R)
    position_type   : int           # ORDER_TYPE_BUY / SELL
    original_volume : float         # volume ban đầu
    partial_done    : bool          # đã partial close chưa
    be_done         : bool          # đã dời SL về BE chưa
  }
"""

import datetime
import MetaTrader5 as mt5
from typing import Optional, List, Dict

import config


# ═══════════════════════════════════════════════════════════════
# SESSION FILTER (giữ nguyên từ V2)
# ═══════════════════════════════════════════════════════════════

class SessionFilter:
    """Kiểm tra phiên giao dịch cho phép."""

    @staticmethod
    def is_allowed_now(
        now: Optional[datetime.datetime] = None,
        sessions: Optional[List[Dict]]  = None,
        allowed_weekdays: Optional[List[int]] = None,
    ) -> tuple:
        if now is None:
            now = datetime.datetime.now()

        sessions         = sessions         or config.ALLOWED_SESSIONS
        allowed_weekdays = allowed_weekdays or config.ALLOWED_WEEKDAYS

        weekday = now.weekday()
        if weekday not in allowed_weekdays:
            return False, f"Ngoài ngày giao dịch (weekday={weekday})"

        if weekday == 4:
            fc_time = datetime.datetime.strptime(
                config.FORCE_CLOSE_FRIDAY_TIME, "%H:%M"
            ).time()
            if now.time() >= fc_time:
                return False, f"Thứ 6 sau {config.FORCE_CLOSE_FRIDAY_TIME}"

        now_time = now.time()
        for session in sessions:
            start = datetime.datetime.strptime(session["start"], "%H:%M").time()
            end   = datetime.datetime.strptime(session["end"],   "%H:%M").time()
            if start <= now_time <= end:
                return True, f"Trong phiên {session['name']} ({session['start']}–{session['end']})"

        return False, f"Ngoài phiên giao dịch ({now.strftime('%H:%M')})"

    @staticmethod
    def should_force_close_friday(now: Optional[datetime.datetime] = None) -> bool:
        if now is None:
            now = datetime.datetime.now()
        if now.weekday() != 4:
            return False
        fc_time = datetime.datetime.strptime(
            config.FORCE_CLOSE_FRIDAY_TIME, "%H:%M"
        ).time()
        return now.time() >= fc_time


# ═══════════════════════════════════════════════════════════════
# TRADE MANAGER
# ═══════════════════════════════════════════════════════════════

# Buffer breakeven: đặt SL cách entry một chút để cover spread
BE_BUFFER_POINTS = getattr(config, 'BE_BUFFER_POINTS', 50)


class TradeManager:
    """
    Quản lý vòng đời lệnh ICT Pullback:
      - Partial close 50% khi đạt half_target
      - Dời SL về Breakeven sau partial close
      - Trailing SL tùy chọn (chỉ sau khi BE đã set)
      - Force close cuối tuần
    """

    def __init__(self, symbol: str):
        self.symbol      = symbol
        sym_info         = mt5.symbol_info(symbol)
        self.point       = sym_info.point  if sym_info else 0.01
        self.digits      = sym_info.digits if sym_info else 2
        self._trades: Dict[int, Dict] = {}   # ticket → state

    # ── Đăng ký lệnh mới ────────────────────────────────────────

    def register(
        self,
        ticket:         int,
        open_price:     float,
        tp_price:       float,        # full TP từ H1 target (giá thực, không phải points)
        sl_price:       float,        # SL ban đầu (giá thực)
        position_type:  int,          # mt5.ORDER_TYPE_BUY / SELL
        volume:         float,        # volume đã vào
    ) -> None:
        """
        Đăng ký lệnh mới vào TradeManager.

        half_target = midpoint giữa open_price và tp_price.
        Khi giá chạm half_target → partial close + BE.
        """
        half_target = (open_price + tp_price) / 2.0

        self._trades[ticket] = {
            "ticket":          ticket,
            "open_price":      open_price,
            "tp_price":        tp_price,
            "half_target":     half_target,
            "sl_price":        sl_price,
            "initial_sl":      sl_price,
            "position_type":   position_type,
            "original_volume": volume,
            "partial_done":    False,
            "be_done":         False,
        }

        r_distance = abs(open_price - sl_price)
        tp_distance = abs(tp_price - open_price)
        estimated_rr = round(tp_distance / r_distance, 2) if r_distance > 0 else "?"

        print(
            f"📌 [TM] Đăng ký Ticket={ticket} | "
            f"Entry={open_price} | TP={tp_price} | SL={sl_price}\n"
            f"        Half-target={half_target:.{self.digits}f} | "
            f"Estimated RR≈{estimated_rr}R | Vol={volume}"
        )

    # ── Cập nhật mỗi nến M5 ─────────────────────────────────────

    def update(self) -> List[int]:
        """
        Gọi mỗi nến M5 mới.
        Kiểm tra từng lệnh đang theo dõi:
          1. Nếu giá chạm half_target và chưa partial → partial close 50% + BE
          2. Nếu đã BE và TRAILING_ENABLED → trailing SL
        Returns danh sách ticket đã được xử lý trong lượt này.
        """
        acted = []

        for ticket, state in list(self._trades.items()):
            positions = mt5.positions_get(ticket=ticket)
            if not positions:
                # Lệnh đã đóng hết (TP/SL hoặc manual) → dọn dẹp
                print(f"🏁 [TM] Ticket={ticket} không còn position, dọn dẹp.")
                del self._trades[ticket]
                continue

            pos  = positions[0]
            tick = mt5.symbol_info_tick(self.symbol)
            if tick is None:
                continue

            ptype = state["position_type"]
            current_price = tick.bid if ptype == mt5.ORDER_TYPE_BUY else tick.ask

            # ── Bước 1: Partial close tại half_target ─────────
            if not state["partial_done"]:
                hit_half = (
                    (ptype == mt5.ORDER_TYPE_BUY  and current_price >= state["half_target"]) or
                    (ptype == mt5.ORDER_TYPE_SELL and current_price <= state["half_target"])
                )
                if hit_half:
                    close_vol = self._round_volume(pos.volume / 2.0)
                    success   = self._partial_close(ticket, close_vol, ptype, tick)
                    if success:
                        state["partial_done"] = True
                        acted.append(ticket)
                        print(
                            f"✂️  [TM] PARTIAL CLOSE Ticket={ticket} | "
                            f"Đóng {close_vol} lots tại {current_price:.{self.digits}f} | "
                            f"Half-target={state['half_target']:.{self.digits}f}"
                        )

                        # ── Bước 2: Dời SL về Breakeven ──────
                        be_sl = self._calc_be_sl(state["open_price"], ptype)
                        # Chỉ dời SL nếu BE tốt hơn SL hiện tại
                        should_move = (
                            (ptype == mt5.ORDER_TYPE_BUY  and be_sl > state["sl_price"]) or
                            (ptype == mt5.ORDER_TYPE_SELL and be_sl < state["sl_price"])
                        )
                        if should_move:
                            if self._modify_sl(ticket, be_sl, pos.tp):
                                state["sl_price"] = be_sl
                                state["be_done"]  = True
                                print(
                                    f"🔐 [TM] BREAKEVEN Ticket={ticket} | "
                                    f"SL dời về {be_sl:.{self.digits}f} "
                                    f"(entry={state['open_price']} ± buffer)"
                                )

            # ── Bước 3: Trailing SL (sau khi BE) ──────────────
            if (state["be_done"]
                    and getattr(config, 'TRAILING_ENABLED', False)):
                self._trail_sl(ticket, state, pos, current_price, ptype)
                acted_trail = ticket not in acted
                # (chỉ append nếu chưa append ở bước partial)

        return acted

    # ── Force close ─────────────────────────────────────────────

    def force_close_all(self) -> None:
        """Đóng tất cả lệnh đang mở (dùng cuối tuần)."""
        positions = mt5.positions_get(symbol=self.symbol)
        if not positions:
            return
        print(f"🔔 [TM] Force close {len(positions)} lệnh cuối tuần...")
        for pos in positions:
            close_type = (mt5.ORDER_TYPE_SELL if pos.type == mt5.ORDER_TYPE_BUY
                          else mt5.ORDER_TYPE_BUY)
            tick  = mt5.symbol_info_tick(self.symbol)
            price = tick.bid if close_type == mt5.ORDER_TYPE_SELL else tick.ask
            req = {
                "action":       mt5.TRADE_ACTION_DEAL,
                "symbol":       self.symbol,
                "volume":       pos.volume,
                "type":         close_type,
                "position":     pos.ticket,
                "price":        price,
                "deviation":    30,
                "magic":        pos.magic,
                "comment":      "force_close_friday",
                "type_time":    mt5.ORDER_TIME_GTC,
                "type_filling": mt5.ORDER_FILLING_FOK,
            }
            result = mt5.order_send(req)
            if result and result.retcode == mt5.TRADE_RETCODE_DONE:
                print(f"   ✅ Ticket={pos.ticket} đóng OK")
            else:
                code = result.retcode if result else "N/A"
                print(f"   ❌ Ticket={pos.ticket} thất bại retcode={code}")

    def unregister(self, ticket: int) -> None:
        self._trades.pop(ticket, None)

    def is_tracking(self, ticket: int) -> bool:
        return ticket in self._trades

    # ── Internal helpers ─────────────────────────────────────────

    def _partial_close(
        self,
        ticket:     int,
        volume:     float,
        ptype:      int,
        tick,
    ) -> bool:
        """Đóng một phần lệnh (counter-trade)."""
        close_type = (mt5.ORDER_TYPE_SELL if ptype == mt5.ORDER_TYPE_BUY
                      else mt5.ORDER_TYPE_BUY)
        price = tick.bid if close_type == mt5.ORDER_TYPE_SELL else tick.ask
        req = {
            "action":       mt5.TRADE_ACTION_DEAL,
            "symbol":       self.symbol,
            "volume":       volume,
            "type":         close_type,
            "position":     ticket,
            "price":        price,
            "deviation":    30,
            "comment":      "partial_close_50pct",
            "type_time":    mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_FOK,
        }
        result = mt5.order_send(req)
        if result and result.retcode == mt5.TRADE_RETCODE_DONE:
            return True
        code = result.retcode if result else "N/A"
        print(f"   ⚠️  Partial close thất bại Ticket={ticket} retcode={code}")
        return False

    def _calc_be_sl(self, open_price: float, ptype: int) -> float:
        """Tính giá SL breakeven = entry ± buffer nhỏ."""
        buf = BE_BUFFER_POINTS * self.point
        if ptype == mt5.ORDER_TYPE_BUY:
            return round(open_price + buf, self.digits)   # SL trên entry chút xíu
        else:
            return round(open_price - buf, self.digits)   # SL dưới entry chút xíu

    def _modify_sl(self, ticket: int, new_sl: float, current_tp: float) -> bool:
        """Gửi lệnh sửa SL lên MT5."""
        req = {
            "action":   mt5.TRADE_ACTION_SLTP,
            "position": ticket,
            "sl":       new_sl,
            "tp":       current_tp,
        }
        result = mt5.order_send(req)
        if result and result.retcode == mt5.TRADE_RETCODE_DONE:
            return True
        code = result.retcode if result else "N/A"
        print(f"   ⚠️  Modify SL thất bại Ticket={ticket} retcode={code}")
        return False

    def _trail_sl(
        self,
        ticket:        int,
        state:         Dict,
        pos,
        current_price: float,
        ptype:         int,
    ) -> None:
        """Trailing SL sau khi đã BE (tùy chọn)."""
        step_pts  = getattr(config, 'TRAILING_STEP_POINTS', 150) * self.point
        risk_pts  = abs(state["open_price"] - state["initial_sl"])

        if ptype == mt5.ORDER_TYPE_BUY:
            new_sl = round(current_price - risk_pts, self.digits)
            if new_sl > state["sl_price"] + step_pts:
                if self._modify_sl(ticket, new_sl, pos.tp):
                    state["sl_price"] = new_sl
                    print(f"🔼 [TM TRAIL] Ticket={ticket} SL → {new_sl:.{self.digits}f}")
        else:
            new_sl = round(current_price + risk_pts, self.digits)
            if new_sl < state["sl_price"] - step_pts:
                if self._modify_sl(ticket, new_sl, pos.tp):
                    state["sl_price"] = new_sl
                    print(f"🔽 [TM TRAIL] Ticket={ticket} SL → {new_sl:.{self.digits}f}")

    def _round_volume(self, vol: float) -> float:
        """Làm tròn volume theo step của broker."""
        sym = mt5.symbol_info(self.symbol)
        if sym is None:
            return round(vol, 2)
        step = sym.volume_step
        import math
        vol = math.floor(vol / step) * step
        vol = max(vol, sym.volume_min)
        return round(vol, max(0, int(round(-math.log10(step)))))
