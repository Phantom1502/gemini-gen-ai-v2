"""
mt5util.py  (V2.1 - fix start_pos=0, daily resample offset 20h GMT)
=====================================================================
- Tất cả copy_rates_from_pos dùng start_pos=0 để lấy nến đang chạy
- Resample Daily dùng '24H' offset='20h' để khớp chart OANDA (ngày bắt đầu 20:00 GMT)
- get_multi_tf_data trả về cả nến hiện tại (chưa đóng)
"""

import MetaTrader5 as mt5
import pandas as pd
from typing import Optional, Dict, Tuple
import math
import datetime


# ═══════════════════════════════════════════════════════════════
# HELPER: Resample H1 → Daily theo chuẩn OANDA (ngày bắt 20h GMT)
# ═══════════════════════════════════════════════════════════════

def resample_h1_to_daily_oanda(df_h1: pd.DataFrame, tail: int = 22) -> pd.DataFrame:
    """
    Resample H1 → Daily khớp với chart OANDA:
      - Mỗi ngày bắt đầu lúc 20:00 GMT (Chủ nhật tối) và kết thúc 19:59 GMT ngày hôm sau
      - offset='20h' để canh đúng ranh giới nến ngày
      - label='right' → index của nến là thời điểm ĐÓNG (20h hôm sau)
      - Bỏ qua nến chưa đủ dữ liệu (dropna)

    Parameters
    ----------
    df_h1 : DataFrame H1 với DatetimeIndex UTC/GMT
    tail  : số nến Daily cuối cần giữ lại (mặc định 22 để vẽ 20 nến + buffer)

    Returns
    -------
    DataFrame Daily với cột Open/High/Low/Close
    """
    df_daily = (
        df_h1.resample('24h', origin='start_day', offset='20h', label='right')
        .agg({'Open': 'first', 'High': 'max', 'Low': 'min', 'Close': 'last'})
        .dropna()
    )
    return df_daily.tail(tail)


class MT5Util:

    # ══════════════════════════════════════════════
    # KẾT NỐI
    # ══════════════════════════════════════════════

    @staticmethod
    def init_mt5(username: int, password: str, server: str, symbol: str) -> bool:
        term_info = mt5.terminal_info()
        if term_info is not None:
            if hasattr(term_info, 'connected') and term_info.connected:
                symbol_info = mt5.symbol_info(symbol)
                if symbol_info and symbol_info.visible:
                    return True

        if not mt5.initialize(login=int(username), password=password, server=server):
            raise ConnectionError(f"MT5 init failed: {mt5.last_error()}")

        symbol_info = mt5.symbol_info(symbol)
        if symbol_info is None:
            mt5.shutdown()
            raise ValueError(f"Symbol '{symbol}' không tồn tại.")

        if not symbol_info.visible:
            if not mt5.symbol_select(symbol, True):
                mt5.shutdown()
                raise RuntimeError(f"Không thể kích hoạt {symbol}: {mt5.last_error()}")

        print(f"✅ [MT5] Kết nối thành công tài khoản {username} | Symbol: {symbol}")
        return True

    # ══════════════════════════════════════════════
    # LẤY DỮ LIỆU (start_pos=0 → bao gồm nến đang chạy)
    # ══════════════════════════════════════════════

    @staticmethod
    def get_current_open_time(symbol: str, timeframe: int) -> int:
        """Thời gian mở của nến M5 hiện tại (dùng để phát hiện nến mới)."""
        # start_pos=0 → nến đang chạy
        rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, 1)
        if rates is None or len(rates) == 0:
            raise RuntimeError(f"Không lấy được dữ liệu nến: {mt5.last_error()}")
        return int(rates[0]['time'])

    @staticmethod
    def is_existing_position(symbol: str, magic_number: Optional[int] = None) -> bool:
        positions = mt5.positions_get(symbol=symbol)
        if positions is None or len(positions) == 0:
            return False
        if magic_number is not None:
            return any(pos.magic == magic_number for pos in positions)
        return True

    @staticmethod
    def get_historical_data(symbol: str, timeframe: int, count: int = 50) -> pd.DataFrame:
        """
        Lấy dữ liệu lịch sử bao gồm nến đang chạy (start_pos=0).
        """
        rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, count)
        if rates is None or len(rates) == 0:
            raise RuntimeError(f"Không lấy được dữ liệu lịch sử: {mt5.last_error()}")
        return MT5Util._rates_to_df(rates)

    @staticmethod
    def get_last_close_candle_info(symbol: str, timeframe: int) -> Dict[str, float]:
        """Nến vừa đóng (start_pos=1 → bỏ nến đang chạy)."""
        rates = mt5.copy_rates_from_pos(symbol, timeframe, 1, 1)
        if rates is None or len(rates) == 0:
            raise RuntimeError(f"Không lấy được dữ liệu nến: {mt5.last_error()}")
        return {
            'open':  float(rates[0]['open']),
            'high':  float(rates[0]['high']),
            'low':   float(rates[0]['low']),
            'close': float(rates[0]['close']),
            'time':  int(rates[0]['time'])
        }

    # ══════════════════════════════════════════════
    # MỚI V2.1: ĐA KHUNG THỜI GIAN (bao gồm nến đang chạy)
    # ══════════════════════════════════════════════

    @staticmethod
    def get_multi_tf_data(
        symbol: str,
        h1_count: int  = 700,   # ~29 ngày H1 để resample Daily + buffer
        h1_window: int = 60,    # số nến H1 gần nhất cho chart H1
        m5_window: int = 120,   # số nến M5 gần nhất cho chart M5
    ) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
        """
        Lấy dữ liệu 3 timeframe, bao gồm nến đang chạy (start_pos=0).

        Returns
        -------
        df_daily  : nến Daily resample theo chuẩn OANDA (offset 20h GMT)
        df_h1     : h1_window nến H1 gần nhất (kể cả nến đang chạy)
        df_m5     : m5_window nến M5 gần nhất (kể cả nến đang chạy)
        """
        # ── H1 raw (start_pos=0 → lấy cả nến đang chạy) ──────────
        rates_h1_raw = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_H1, 0, h1_count)
        if rates_h1_raw is None or len(rates_h1_raw) == 0:
            raise RuntimeError(f"Không lấy được dữ liệu H1: {mt5.last_error()}")
        df_h1_raw = MT5Util._rates_to_df(rates_h1_raw)

        # ── Resample → Daily (OANDA offset 20h GMT) ───────────────
        df_daily = resample_h1_to_daily_oanda(df_h1_raw, tail=22)

        # ── H1 window (nến gần nhất, kể cả đang chạy) ────────────
        df_h1 = df_h1_raw.tail(h1_window)

        # ── M5 (start_pos=0 → kể cả nến đang chạy) ───────────────
        rates_m5 = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M5, 0, m5_window)
        if rates_m5 is None or len(rates_m5) == 0:
            raise RuntimeError(f"Không lấy được dữ liệu M5: {mt5.last_error()}")
        df_m5 = MT5Util._rates_to_df(rates_m5)

        print(
            f"📦 [MT5] Daily={len(df_daily)} nến | "
            f"H1={len(df_h1)} nến | "
            f"M5={len(df_m5)} nến (bao gồm nến đang chạy)"
        )
        return df_daily, df_h1, df_m5

    # ══════════════════════════════════════════════
    # QUẢN LÝ LỆNH
    # ══════════════════════════════════════════════

    @staticmethod
    def open_position(
        symbol: str, lot: float, position_type: int,
        sl_in_point: float, rr: float = 2.0,
        magic_number: int = 0, deviation: int = 20, comment: str = ""
    ) -> Optional[int]:
        symbol_info = mt5.symbol_info(symbol)
        if symbol_info is None:
            print("❌ [ORDER] Không lấy được symbol info.")
            return None

        point     = symbol_info.point
        tick_info = mt5.symbol_info_tick(symbol)
        if tick_info is None:
            print("❌ [ORDER] Không lấy được tick.")
            return None

        if position_type == mt5.ORDER_TYPE_BUY:
            price = tick_info.ask
            sl    = round(price - sl_in_point * point, symbol_info.digits)
            tp    = round(price + sl_in_point * rr * point, symbol_info.digits)
        elif position_type == mt5.ORDER_TYPE_SELL:
            price = tick_info.bid
            sl    = round(price + sl_in_point * point, symbol_info.digits)
            tp    = round(price - sl_in_point * rr * point, symbol_info.digits)
        else:
            print(f"❌ [ORDER] Loại lệnh không hợp lệ: {position_type}")
            return None

        request = {
            "action":       mt5.TRADE_ACTION_DEAL,
            "symbol":       symbol,
            "volume":       float(lot),
            "type":         position_type,
            "price":        price,
            "sl":           sl,
            "tp":           tp,
            "deviation":    deviation,
            "magic":        magic_number,
            "comment":      comment,
            "type_time":    mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_FOK,
        }
        print(f"📡 [ORDER] Type={position_type} | Price={price} | SL={sl} | TP={tp}")
        result = mt5.order_send(request)
        if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
            code = result.retcode if result else "N/A"
            msg  = result.comment if result else "No response"
            print(f"❌ [ORDER FAILED] Retcode={code}: {msg}")
            return None
        print(f"🚀 [ORDER OK] Ticket: {result.order}")
        return result.order

    @staticmethod
    def calculate_volume_by_cash(symbol: str, sl_in_point: float, risk_cash: float) -> float:
        symbol_info = mt5.symbol_info(symbol)
        if symbol_info is None:
            return 0.0
        point      = symbol_info.point
        tick_size  = symbol_info.trade_tick_size
        tick_value = symbol_info.trade_tick_value
        loss_per_lot = (sl_in_point * point / tick_size) * tick_value
        if loss_per_lot == 0:
            return symbol_info.volume_min
        volume = risk_cash / loss_per_lot
        step   = symbol_info.volume_step
        volume = math.floor(volume / step) * step
        volume = max(volume, symbol_info.volume_min)
        volume = min(volume, symbol_info.volume_max)
        lot_digits = max(0, int(round(-math.log10(step))))
        return round(volume, lot_digits)

    @staticmethod
    def get_last_closed_deal_profit(symbol: str, magic_number: Optional[int] = None) -> float:
        end_date   = datetime.datetime.now()
        start_date = end_date - datetime.timedelta(days=3)
        deals = mt5.history_deals_get(start_date, end_date, group=f"*{symbol}*")
        if not deals:
            return 0.0
        deals_list = sorted(list(deals), key=lambda x: x.time, reverse=True)
        for deal in deals_list:
            if magic_number is not None and deal.magic != magic_number:
                continue
            if deal.entry in [mt5.DEAL_ENTRY_OUT, mt5.DEAL_ENTRY_INOUT]:
                return float(deal.profit)
        return 0.0

    @staticmethod
    def get_deal_result_by_ticket(ticket: int) -> Dict:
        deals = mt5.history_deals_get(position=ticket)
        profit = 0.0
        result = "LOSE/BREAKEVEN"
        if deals:
            for deal in deals:
                if deal.entry in [mt5.DEAL_ENTRY_OUT, mt5.DEAL_ENTRY_INOUT]:
                    profit += deal.profit
            if profit > 0:
                result = "WIN"
        return {"profit": round(profit, 2), "result": result}


    @staticmethod
    def open_position_with_tp(
        symbol:       str,
        lot:          float,
        position_type: int,
        sl_price:     float,        # SL giá thực (đã tính sẵn)
        tp_price:     float,        # TP giá thực từ H1 target (không fix RR)
        magic_number: int  = 0,
        deviation:    int  = 20,
        comment:      str  = "",
    ) -> Optional[int]:
        """
        Mở lệnh với SL và TP là giá thực (không tính từ RR cố định).
        Dùng cho phương pháp ICT pullback — TP lấy từ H1TradingContext.target.
        """
        sym_info  = mt5.symbol_info(symbol)
        tick_info = mt5.symbol_info_tick(symbol)
        if sym_info is None or tick_info is None:
            print("❌ [ORDER] Không lấy được symbol/tick info.")
            return None

        if position_type == mt5.ORDER_TYPE_BUY:
            price = tick_info.ask
        elif position_type == mt5.ORDER_TYPE_SELL:
            price = tick_info.bid
        else:
            print(f"❌ [ORDER] Loại lệnh không hợp lệ: {position_type}")
            return None

        request = {
            "action":       mt5.TRADE_ACTION_DEAL,
            "symbol":       symbol,
            "volume":       float(lot),
            "type":         position_type,
            "price":        price,
            "sl":           sl_price,
            "tp":           tp_price,
            "deviation":    deviation,
            "magic":        magic_number,
            "comment":      comment,
            "type_time":    mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_FOK,
        }
        print(f"📡 [ORDER] {('BUY' if position_type==mt5.ORDER_TYPE_BUY else 'SELL')} "
              f"| Price={price} | SL={sl_price} | TP={tp_price} | Lot={lot}")
        result = mt5.order_send(request)
        if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
            code = result.retcode if result else "N/A"
            msg  = result.comment if result else "No response"
            print(f"❌ [ORDER FAILED] Retcode={code}: {msg}")
            return None
        print(f"🚀 [ORDER OK] Ticket={result.order}")
        return result.order

    @staticmethod
    def disconnect() -> None:
        mt5.shutdown()
        print("🔌 [MT5] Đã đóng kết nối.")

    # ══════════════════════════════════════════════
    # INTERNAL HELPER
    # ══════════════════════════════════════════════

    @staticmethod
    def _rates_to_df(rates) -> pd.DataFrame:
        df = pd.DataFrame(rates)
        df['Datetime'] = pd.to_datetime(df['time'], unit='s')
        df.set_index('Datetime', inplace=True)
        df.rename(columns={
            'open': 'Open', 'high': 'High',
            'low': 'Low', 'close': 'Close',
            'tick_volume': 'Volume'
        }, inplace=True)
        cols = ['Open', 'High', 'Low', 'Close', 'Volume']
        return df[[c for c in cols if c in df.columns]]
