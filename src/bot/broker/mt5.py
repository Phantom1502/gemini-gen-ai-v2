"""
bot/broker/mt5.py
=================
MT5 connector — tất cả tương tác với MetaTrader5 tập trung tại đây.
Không có business logic, chỉ I/O thuần.
"""

import math
import datetime
import MetaTrader5 as mt5
import pandas as pd
from typing import Optional, Dict, Tuple


# ═══════════════════════════════════════════════════════════════
# RESAMPLE HELPER (OANDA daily offset)
# ═══════════════════════════════════════════════════════════════

def resample_h1_to_daily_oanda(df_h1: pd.DataFrame, tail: int = 22) -> pd.DataFrame:
    """
    Resample H1 → Daily khớp với broker OANDA:
    mỗi ngày bắt đầu lúc 20:00 GMT, kết thúc 19:59 GMT hôm sau.
    """
    return (
        df_h1
        .resample("24h", origin="start_day", offset="20h", label="right")
        .agg({"Open": "first", "High": "max", "Low": "min", "Close": "last"})
        .dropna()
        .tail(tail)
    )


# ═══════════════════════════════════════════════════════════════
# MT5Util
# ═══════════════════════════════════════════════════════════════

class MT5Util:

    # ── Kết nối ─────────────────────────────────────────────────

    @staticmethod
    def init(username: int, password: str, server: str, symbol: str) -> bool:
        info = mt5.terminal_info()
        if info and getattr(info, "connected", False):
            si = mt5.symbol_info(symbol)
            if si and si.visible:
                return True

        if not mt5.initialize(login=int(username), password=password, server=server):
            raise ConnectionError(f"MT5 init failed: {mt5.last_error()}")

        si = mt5.symbol_info(symbol)
        if si is None:
            mt5.shutdown(); raise ValueError(f"Symbol '{symbol}' không tồn tại.")
        if not si.visible:
            if not mt5.symbol_select(symbol, True):
                mt5.shutdown(); raise RuntimeError(f"Không kích hoạt được {symbol}")

        print(f"✅ [MT5] Kết nối OK — tài khoản {username} | {symbol}")
        return True

    @staticmethod
    def disconnect() -> None:
        mt5.shutdown()
        print("🔌 [MT5] Đã ngắt kết nối.")

    # ── Lấy dữ liệu ─────────────────────────────────────────────

    @staticmethod
    def get_multi_tf_data(
        symbol: str,
        h1_count: int  = 700,
        h1_window: int = 60,
        m5_window: int = 120,
    ) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
        """
        Lấy dữ liệu 3 TF cùng lúc (start_pos=0 → bao gồm nến đang chạy).

        Returns: (df_daily, df_h1, df_m5)
        """
        rates_h1 = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_H1, 0, h1_count)
        if rates_h1 is None or len(rates_h1) == 0:
            raise RuntimeError(f"Không lấy được H1: {mt5.last_error()}")
        df_h1_raw = MT5Util._to_df(rates_h1)

        df_daily = resample_h1_to_daily_oanda(df_h1_raw, tail=22)
        df_h1    = df_h1_raw.tail(h1_window)

        rates_m5 = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M5, 0, m5_window)
        if rates_m5 is None or len(rates_m5) == 0:
            raise RuntimeError(f"Không lấy được M5: {mt5.last_error()}")
        df_m5 = MT5Util._to_df(rates_m5)

        print(f"📦 [MT5] Daily={len(df_daily)} | H1={len(df_h1)} | M5={len(df_m5)} nến")
        return df_daily, df_h1, df_m5

    @staticmethod
    def get_current_candle_time(symbol: str, timeframe: int) -> int:
        """Timestamp mở của nến hiện tại (để phát hiện nến mới)."""
        rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, 1)
        if not rates:
            raise RuntimeError(f"Không lấy được tick: {mt5.last_error()}")
        return int(rates[0]["time"])

    @staticmethod
    def get_last_closed_candle(symbol: str, timeframe: int) -> Dict:
        """Nến vừa đóng (start_pos=1)."""
        rates = mt5.copy_rates_from_pos(symbol, timeframe, 1, 1)
        if not rates:
            raise RuntimeError(f"Không lấy được nến: {mt5.last_error()}")
        r = rates[0]
        return {"open": float(r["open"]), "high": float(r["high"]),
                "low":  float(r["low"]),  "close": float(r["close"]),
                "time": int(r["time"])}

    # ── Trạng thái tài khoản / vị thế ───────────────────────────

    @staticmethod
    def has_open_position(symbol: str, magic: int) -> bool:
        pos = mt5.positions_get(symbol=symbol)
        if not pos:
            return False
        return any(p.magic == magic for p in pos)

    @staticmethod
    def get_account_equity() -> float:
        info = mt5.account_info()
        return float(info.equity) if info else 0.0

    @staticmethod
    def get_tick(symbol: str):
        return mt5.symbol_info_tick(symbol)

    @staticmethod
    def get_symbol_info(symbol: str):
        return mt5.symbol_info(symbol)

    # ── Mở / sửa / đóng lệnh ────────────────────────────────────

    @staticmethod
    def open_position(
        symbol:        str,
        lot:           float,
        position_type: int,           # mt5.ORDER_TYPE_BUY / SELL
        sl_price:      float,
        tp_price:      float,
        magic:         int  = 0,
        deviation:     int  = 20,
        comment:       str  = "",
    ) -> Optional[int]:
        """Mở lệnh với SL và TP là giá thực. Trả về ticket hoặc None."""
        si   = mt5.symbol_info(symbol)
        tick = mt5.symbol_info_tick(symbol)
        if si is None or tick is None:
            print("❌ [ORDER] Không lấy được symbol/tick info.")
            return None

        price = tick.ask if position_type == mt5.ORDER_TYPE_BUY else tick.bid
        req = {
            "action":       mt5.TRADE_ACTION_DEAL,
            "symbol":       symbol,
            "volume":       float(lot),
            "type":         position_type,
            "price":        price,
            "sl":           sl_price,
            "tp":           tp_price,
            "deviation":    deviation,
            "magic":        magic,
            "comment":      comment,
            "type_time":    mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_FOK,
        }
        side = "BUY" if position_type == mt5.ORDER_TYPE_BUY else "SELL"
        print(f"📡 [ORDER] {side} | price={price} | SL={sl_price} | TP={tp_price} | lot={lot}")

        result = mt5.order_send(req)
        if result and result.retcode == mt5.TRADE_RETCODE_DONE:
            print(f"🚀 [ORDER OK] Ticket={result.order}")
            return result.order
        code = result.retcode if result else "N/A"
        msg  = result.comment if result else "no response"
        print(f"❌ [ORDER FAILED] retcode={code}: {msg}")
        return None

    @staticmethod
    def partial_close(
        symbol:        str,
        ticket:        int,
        volume:        float,
        position_type: int,
    ) -> bool:
        """Đóng một phần lệnh (counter-trade)."""
        tick       = mt5.symbol_info_tick(symbol)
        close_type = (mt5.ORDER_TYPE_SELL if position_type == mt5.ORDER_TYPE_BUY
                      else mt5.ORDER_TYPE_BUY)
        price = tick.bid if close_type == mt5.ORDER_TYPE_SELL else tick.ask
        req = {
            "action":       mt5.TRADE_ACTION_DEAL,
            "symbol":       symbol,
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
        print(f"⚠️  [PARTIAL CLOSE] thất bại ticket={ticket} "
              f"retcode={result.retcode if result else 'N/A'}")
        return False

    @staticmethod
    def modify_sl_tp(ticket: int, new_sl: float, current_tp: float) -> bool:
        """Sửa SL của lệnh đang mở."""
        req = {"action": mt5.TRADE_ACTION_SLTP,
               "position": ticket, "sl": new_sl, "tp": current_tp}
        result = mt5.order_send(req)
        if result and result.retcode == mt5.TRADE_RETCODE_DONE:
            return True
        print(f"⚠️  [MODIFY SL] thất bại ticket={ticket} "
              f"retcode={result.retcode if result else 'N/A'}")
        return False

    @staticmethod
    def close_all(symbol: str) -> None:
        """Đóng tất cả lệnh đang mở của symbol."""
        positions = mt5.positions_get(symbol=symbol)
        if not positions:
            return
        print(f"🔔 [MT5] Force close {len(positions)} lệnh...")
        for pos in positions:
            close_type = (mt5.ORDER_TYPE_SELL if pos.type == mt5.ORDER_TYPE_BUY
                          else mt5.ORDER_TYPE_BUY)
            tick  = mt5.symbol_info_tick(symbol)
            price = tick.bid if close_type == mt5.ORDER_TYPE_SELL else tick.ask
            req = {
                "action": mt5.TRADE_ACTION_DEAL, "symbol": symbol,
                "volume": pos.volume, "type": close_type,
                "position": pos.ticket, "price": price,
                "deviation": 30, "magic": pos.magic,
                "comment": "force_close",
                "type_time": mt5.ORDER_TIME_GTC,
                "type_filling": mt5.ORDER_FILLING_FOK,
            }
            result = mt5.order_send(req)
            ok = result and result.retcode == mt5.TRADE_RETCODE_DONE
            print(f"  {'✅' if ok else '❌'} Ticket={pos.ticket}")

    # ── Deal history ─────────────────────────────────────────────

    @staticmethod
    def get_deal_result(ticket: int) -> Dict:
        deals  = mt5.history_deals_get(position=ticket)
        profit = 0.0
        result = "LOSE/BREAKEVEN"
        if deals:
            for d in deals:
                if d.entry in (mt5.DEAL_ENTRY_OUT, mt5.DEAL_ENTRY_INOUT):
                    profit += d.profit
            if profit > 0:
                result = "WIN"
        return {"profit": round(profit, 2), "result": result}

    @staticmethod
    def get_last_closed_profit(symbol: str, magic: int) -> float:
        end   = datetime.datetime.now()
        start = end - datetime.timedelta(days=3)
        deals = mt5.history_deals_get(start, end, group=f"*{symbol}*")
        if not deals:
            return 0.0
        for d in sorted(deals, key=lambda x: x.time, reverse=True):
            if d.magic != magic:
                continue
            if d.entry in (mt5.DEAL_ENTRY_OUT, mt5.DEAL_ENTRY_INOUT):
                return float(d.profit)
        return 0.0

    # ── Tính lot ─────────────────────────────────────────────────

    @staticmethod
    def calc_lot(symbol: str, sl_pts: float, risk_cash: float) -> float:
        si = mt5.symbol_info(symbol)
        if si is None:
            return 0.0
        loss_per_lot = (sl_pts * si.point / si.trade_tick_size) * si.trade_tick_value
        if loss_per_lot == 0:
            return si.volume_min
        vol  = risk_cash / loss_per_lot
        step = si.volume_step
        vol  = math.floor(vol / step) * step
        vol  = max(vol, si.volume_min)
        vol  = min(vol, si.volume_max)
        digs = max(0, int(round(-math.log10(step))))
        return round(vol, digs)

    @staticmethod
    def round_volume(symbol: str, vol: float) -> float:
        si = mt5.symbol_info(symbol)
        if si is None:
            return round(vol, 2)
        step = si.volume_step
        vol  = math.floor(vol / step) * step
        vol  = max(vol, si.volume_min)
        digs = max(0, int(round(-math.log10(step))))
        return round(vol, digs)

    # ── Internal ─────────────────────────────────────────────────

    @staticmethod
    def _to_df(rates) -> pd.DataFrame:
        df = pd.DataFrame(rates)
        df["Datetime"] = pd.to_datetime(df["time"], unit="s")
        df.set_index("Datetime", inplace=True)
        df.rename(columns={"open": "Open", "high": "High", "low": "Low",
                            "close": "Close", "tick_volume": "Volume"}, inplace=True)
        cols = [c for c in ("Open", "High", "Low", "Close", "Volume") if c in df.columns]
        return df[cols]
