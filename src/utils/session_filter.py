"""
session_filter.py
=================
Bộ lọc phiên giao dịch và quản lý Trailing Stop Loss.
Tách riêng khỏi Trader để dễ test độc lập.
"""

import datetime
import MetaTrader5 as mt5
from typing import Optional, List, Dict
import src.config_real as config_real


class SessionFilter:
    """
    Kiểm tra xem thời điểm hiện tại có thuộc phiên giao dịch
    được phép không (theo config.py).
    """

    @staticmethod
    def is_allowed_now(
        now: Optional[datetime.datetime] = None,
        sessions: Optional[List[Dict]] = None,
        allowed_weekdays: Optional[List[int]] = None,
    ) -> tuple[bool, str]:
        """
        Trả về (True/False, lý do).
        Giờ so sánh là giờ LOCAL của máy (đã cấu hình UTC+7 trong config).
        """
        if now is None:
            now = datetime.datetime.now()

        sessions        = sessions        or config_real.ALLOWED_SESSIONS
        allowed_weekdays = allowed_weekdays or config_real.ALLOWED_WEEKDAYS

        # Kiểm tra ngày trong tuần
        weekday = now.weekday()  # 0=Mon, 6=Sun
        if weekday not in allowed_weekdays:
            return False, f"Ngoài ngày giao dịch (weekday={weekday})"

        # Kiểm tra force-close Thứ 6
        if weekday == 4:
            fc_time = datetime.datetime.strptime(config_real.FORCE_CLOSE_FRIDAY_TIME, "%H:%M").time()
            if now.time() >= fc_time:
                return False, f"Thứ 6 sau {config_real.FORCE_CLOSE_FRIDAY_TIME} – không vào lệnh mới"

        # Kiểm tra phiên giờ
        now_time = now.time()
        for session in sessions:
            start = datetime.datetime.strptime(session["start"], "%H:%M").time()
            end   = datetime.datetime.strptime(session["end"],   "%H:%M").time()
            if start <= now_time <= end:
                return True, f"Trong phiên {session['name']} ({session['start']}–{session['end']})"

        time_str = now.strftime("%H:%M")
        return False, f"Ngoài phiên giao dịch ({time_str})"

    @staticmethod
    def should_force_close_friday(now: Optional[datetime.datetime] = None) -> bool:
        """True nếu là Thứ 6 và đã qua giờ force-close."""
        if now is None:
            now = datetime.datetime.now()
        if now.weekday() != 4:
            return False
        fc_time = datetime.datetime.strptime(config_real.FORCE_CLOSE_FRIDAY_TIME, "%H:%M").time()
        return now.time() >= fc_time


class TrailingStopManager:
    """
    Quản lý Trailing Stop Loss cho lệnh đang mở.
    Trigger: lợi nhuận >= TRAILING_TRIGGER_RR * initial_risk
    Step:    dịch SL mỗi TRAILING_STEP_POINTS khi giá tiến thêm 1 step
    """

    def __init__(self, symbol: str):
        self.symbol          = symbol
        self.symbol_info     = mt5.symbol_info(symbol)
        self.point           = self.symbol_info.point if self.symbol_info else 0.01
        self.digits          = self.symbol_info.digits if self.symbol_info else 2
        self._tracked: Dict[int, Dict] = {}   # ticket → state

    def register_trade(self, ticket: int, open_price: float,
                       initial_sl: float, initial_risk_pts: float,
                       position_type: int):
        """Đăng ký lệnh mới để tracking trailing."""
        self._tracked[ticket] = {
            "open_price":       open_price,
            "initial_sl":       initial_sl,
            "current_sl":       initial_sl,
            "initial_risk_pts": initial_risk_pts,
            "position_type":    position_type,
            "trailing_active":  False,
            "last_trail_price": open_price,
        }
        print(f"📌 [TRAIL] Đăng ký Ticket={ticket} | OpenPrice={open_price} | SL={initial_sl}")

    def update(self) -> List[int]:
        """
        Gọi mỗi nến mới. Cập nhật SL nếu đủ điều kiện.
        Returns: danh sách ticket đã được dịch SL.
        """
        if not config_real.TRAILING_ENABLED:
            return []

        updated = []
        for ticket, state in list(self._tracked.items()):
            positions = mt5.positions_get(ticket=ticket)
            if not positions:
                del self._tracked[ticket]
                continue

            pos      = positions[0]
            tick     = mt5.symbol_info_tick(self.symbol)
            if tick is None:
                continue

            ptype    = state["position_type"]
            risk_pts = state["initial_risk_pts"]
            trigger  = config_real.TRAILING_TRIGGER_RR * risk_pts * self.point
            step_pts = config_real.TRAILING_STEP_POINTS * self.point

            if ptype == mt5.ORDER_TYPE_BUY:
                current_price   = tick.bid
                profit_distance = current_price - state["open_price"]
                # Kích hoạt trailing
                if profit_distance >= trigger:
                    state["trailing_active"] = True
                if state["trailing_active"]:
                    # Tính SL mới: dịch lên khi giá dịch qua 1 step
                    new_sl = current_price - risk_pts * self.point
                    new_sl = round(new_sl, self.digits)
                    if new_sl > state["current_sl"] + step_pts:
                        if self._modify_sl(ticket, new_sl):
                            state["current_sl"] = new_sl
                            updated.append(ticket)
                            print(f"🔼 [TRAIL BUY] Ticket={ticket} SL dịch lên {new_sl:.{self.digits}f}")

            elif ptype == mt5.ORDER_TYPE_SELL:
                current_price   = tick.ask
                profit_distance = state["open_price"] - current_price
                if profit_distance >= trigger:
                    state["trailing_active"] = True
                if state["trailing_active"]:
                    new_sl = current_price + risk_pts * self.point
                    new_sl = round(new_sl, self.digits)
                    if new_sl < state["current_sl"] - step_pts:
                        if self._modify_sl(ticket, new_sl):
                            state["current_sl"] = new_sl
                            updated.append(ticket)
                            print(f"🔽 [TRAIL SELL] Ticket={ticket} SL dịch xuống {new_sl:.{self.digits}f}")

        return updated

    def _modify_sl(self, ticket: int, new_sl: float) -> bool:
        """Gửi lệnh sửa SL lên MT5."""
        positions = mt5.positions_get(ticket=ticket)
        if not positions:
            return False
        pos = positions[0]
        request = {
            "action":   mt5.TRADE_ACTION_SLTP,
            "position": ticket,
            "sl":       new_sl,
            "tp":       pos.tp,
        }
        result = mt5.order_send(request)
        if result and result.retcode == mt5.TRADE_RETCODE_DONE:
            return True
        code = result.retcode if result else "N/A"
        print(f"⚠️ [TRAIL] Sửa SL thất bại Ticket={ticket} retcode={code}")
        return False

    def unregister(self, ticket: int):
        """Xoá lệnh đã đóng khỏi tracking."""
        self._tracked.pop(ticket, None)

    def force_close_all(self):
        """Đóng tất cả lệnh đang mở (dùng cuối tuần)."""
        positions = mt5.positions_get(symbol=self.symbol)
        if not positions:
            return
        print(f"🔔 [FORCE CLOSE] Đóng {len(positions)} lệnh cuối tuần...")
        for pos in positions:
            ptype = mt5.ORDER_TYPE_SELL if pos.type == mt5.ORDER_TYPE_BUY else mt5.ORDER_TYPE_BUY
            tick  = mt5.symbol_info_tick(self.symbol)
            price = tick.bid if ptype == mt5.ORDER_TYPE_SELL else tick.ask
            request = {
                "action":       mt5.TRADE_ACTION_DEAL,
                "symbol":       self.symbol,
                "volume":       pos.volume,
                "type":         ptype,
                "position":     pos.ticket,
                "price":        price,
                "deviation":    30,
                "magic":        pos.magic,
                "comment":      "force_close_friday",
                "type_time":    mt5.ORDER_TIME_GTC,
                "type_filling": mt5.ORDER_FILLING_FOK,
            }
            result = mt5.order_send(request)
            if result and result.retcode == mt5.TRADE_RETCODE_DONE:
                print(f"✅ [FORCE CLOSE] Ticket={pos.ticket} đóng thành công.")
            else:
                code = result.retcode if result else "N/A"
                print(f"❌ [FORCE CLOSE] Ticket={pos.ticket} thất bại. retcode={code}")
