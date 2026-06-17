"""
m5_entry_util.py  (V2.2)
========================
ICT M5 Entry Finder — Phân tầng nghiêm ngặt

Thay đổi V2.2:
  1. TẤT CẢ giải thuật (FVG, CHoCH, find_nearest_fvg) đều loại bỏ nến
     đang chạy trước khi tính toán → df_closed = df.iloc[:-1]
     Nến cuối (index -1) là nến ĐANG CHẠY, chưa đóng → không được dùng
     để xác định cấu trúc.

  2. generate_m5_chart() KHÔNG nhận daily_bias nữa.
     Chart M5 không hiển thị label "Daily Bias" — M5 không được biết Daily.
     Thay vào đó nhận h1_context (H1TradingContext dict) để vẽ entry_zone H1
     lên chart M5 làm tham chiếu trực quan.

  3. m5_payload trả về chứa swing_low_for_sl / swing_high_for_sl để
     trader.py tính SL dựa trên cấu trúc M5 thực sự (pullback method).
"""

import os
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import mplfinance as mpf
from typing import Dict, List, Tuple, Optional


class M5EntryUtil:

    # ──────────────────────────────────────────────
    # HELPER: lấy slice nến đã đóng (bỏ nến cuối)
    # ──────────────────────────────────────────────
    @staticmethod
    def _closed(df: pd.DataFrame) -> pd.DataFrame:
        """
        Trả về DataFrame chỉ gồm những nến ĐÃ ĐÓNG.
        Nến cuối (df.iloc[-1]) là nến đang chạy → loại bỏ.
        Nếu df chỉ có 1 nến → trả về empty DataFrame.
        """
        if len(df) <= 1:
            return df.iloc[:0]
        return df.iloc[:-1]

    # ──────────────────────────────────────────────
    # 1. CHoCH — chỉ dùng nến đã đóng
    # ──────────────────────────────────────────────
    @staticmethod
    def detect_choch(df: pd.DataFrame, swing_window: int = 3) -> Optional[Dict]:
        """
        Phát hiện CHoCH gần nhất trên M5.
        Chỉ dùng nến đã đóng (loại bỏ nến đang chạy).

        Returns dict hoặc None.
        """
        dc = M5EntryUtil._closed(df)
        if len(dc) < swing_window * 2 + 2:
            return None

        highs  = dc['High'].values
        lows   = dc['Low'].values
        closes = dc['Close'].values
        length = len(dc)

        swing_highs, swing_lows = [], []
        for i in range(swing_window, length - swing_window):
            if highs[i] == max(highs[i - swing_window: i + swing_window + 1]):
                swing_highs.append((i, float(highs[i])))
            if lows[i] == min(lows[i - swing_window: i + swing_window + 1]):
                swing_lows.append((i, float(lows[i])))

        choch_events = []

        for idx_h, price_h in swing_highs[-5:]:
            for t in range(idx_h + 1, length):
                if closes[t] > price_h:
                    choch_events.append({
                        'type': 'CHoCH_BULL',
                        'candle_idx': t,
                        'broken_level': price_h,
                        'broken_at': float(closes[t]),
                        'candles_ago': length - 1 - t
                    })
                    break

        for idx_l, price_l in swing_lows[-5:]:
            for t in range(idx_l + 1, length):
                if closes[t] < price_l:
                    choch_events.append({
                        'type': 'CHoCH_BEAR',
                        'candle_idx': t,
                        'broken_level': price_l,
                        'broken_at': float(closes[t]),
                        'candles_ago': length - 1 - t
                    })
                    break

        if not choch_events:
            return None
        return max(choch_events, key=lambda x: x['candle_idx'])

    # ──────────────────────────────────────────────
    # 2. FVG — chỉ dùng nến đã đóng
    # ──────────────────────────────────────────────
    @staticmethod
    def find_nearest_fvg(
        df: pd.DataFrame,
        direction: str,
        current_price: float,
    ) -> Optional[Dict]:
        """
        Tìm FVG M5 chưa bị lấp gần nhất theo hướng H1.
        Chỉ tính FVG từ các nến đã đóng → loại bỏ nến đang chạy.

        direction: "BUY"  → tìm FVG_BULL dưới giá (vùng pullback để mua)
                   "SELL" → tìm FVG_BEAR trên giá (vùng pullback để bán)
        """
        dc = M5EntryUtil._closed(df)
        if len(dc) < 3:
            return None

        highs  = dc['High'].values
        lows   = dc['Low'].values
        closes = dc['Close'].values
        length = len(dc)

        fvgs = []
        # FVG cần ít nhất 3 nến: i, i+1, i+2 — tất cả phải đã đóng
        for i in range(length - 2):
            if lows[i + 2] > highs[i]:       # Bullish FVG
                fvgs.append({
                    'type': 'FVG_BULL',
                    'start_idx': i,
                    'top':    float(lows[i + 2]),
                    'bottom': float(highs[i]),
                    'mid':    float((lows[i + 2] + highs[i]) / 2),
                    'filled': False
                })
            if highs[i + 2] < lows[i]:       # Bearish FVG
                fvgs.append({
                    'type': 'FVG_BEAR',
                    'start_idx': i,
                    'top':    float(lows[i]),
                    'bottom': float(highs[i + 2]),
                    'mid':    float((lows[i] + highs[i + 2]) / 2),
                    'filled': False
                })

        # Đánh dấu đã lấp (price chạm vào vùng) — chỉ xét nến đã đóng
        for fvg in fvgs:
            for t in range(fvg['start_idx'] + 3, length):
                if fvg['type'] == 'FVG_BULL' and lows[t] <= fvg['top']:
                    fvg['filled'] = True; break
                if fvg['type'] == 'FVG_BEAR' and highs[t] >= fvg['bottom']:
                    fvg['filled'] = True; break

        unfilled = [f for f in fvgs if not f['filled']]

        if direction == 'BUY':
            # FVG_BULL phía dưới giá hiện tại
            candidates = [f for f in unfilled
                          if f['type'] == 'FVG_BULL' and f['top'] < current_price]
            return max(candidates, key=lambda x: x['top']) if candidates else None

        elif direction == 'SELL':
            # FVG_BEAR phía trên giá hiện tại
            candidates = [f for f in unfilled
                          if f['type'] == 'FVG_BEAR' and f['bottom'] > current_price]
            return min(candidates, key=lambda x: x['bottom']) if candidates else None

        return None

    # ──────────────────────────────────────────────
    # 3. SWING LOW / HIGH cho SL (pullback method)
    # ──────────────────────────────────────────────
    @staticmethod
    def find_sl_swing(
        df: pd.DataFrame,
        direction: str,
        swing_window: int = 3,
        lookback: int = 20,
    ) -> Optional[float]:
        """
        Tìm swing low/high M5 gần nhất để đặt SL (phương pháp pullback).

        BUY  → SL = swing LOW gần nhất trong `lookback` nến đã đóng
        SELL → SL = swing HIGH gần nhất trong `lookback` nến đã đóng

        Đây là mức cấu trúc M5 — nếu giá phá vỡ thì cấu trúc entry sai.
        """
        dc = M5EntryUtil._closed(df)
        if len(dc) < swing_window * 2 + 2:
            return None

        # Chỉ nhìn lookback nến gần nhất trong nến đã đóng
        dc = dc.iloc[-lookback:] if len(dc) > lookback else dc
        highs = dc['High'].values
        lows  = dc['Low'].values
        length = len(dc)

        swings = []
        for i in range(swing_window, length - swing_window):
            if direction == 'BUY':
                if lows[i] == min(lows[i - swing_window: i + swing_window + 1]):
                    swings.append((i, float(lows[i])))
            else:
                if highs[i] == max(highs[i - swing_window: i + swing_window + 1]):
                    swings.append((i, float(highs[i])))

        if not swings:
            return None

        # Lấy swing gần nhất (index lớn nhất)
        return swings[-1][1]

    # ──────────────────────────────────────────────
    # 4. VẼ CHART M5
    # ──────────────────────────────────────────────
    @staticmethod
    def generate_m5_chart(
        df: pd.DataFrame,
        h1_context: Dict,              # H1TradingContext — để vẽ entry zone
        folder: str = "data/charts",
        right_pad_pct: float = 0.08,
    ) -> Tuple[str, Dict]:
        """
        Vẽ chart M5 với EMA21, FVG M5, CHoCH marker, và entry_zone H1.

        KHÔNG nhận daily_bias — M5 không được biết Daily.
        KHÔNG hiển thị bất kỳ label nào liên quan đến Daily.

        Parameters
        ----------
        df          : DataFrame M5 (bao gồm cả nến đang chạy ở cuối)
        h1_context  : H1TradingContext dict — chứa direction, entry_zone, target
        folder      : thư mục lưu ảnh
        right_pad_pct : % khoảng trắng bên phải chart

        Returns
        -------
        (image_path, m5_payload)
        """
        os.makedirs(folder, exist_ok=True)

        df_copy       = df.copy()
        total_candles = len(df_copy)
        pad_candles   = max(int(total_candles * right_pad_pct), 3)
        x_limits      = (-0.5, total_candles - 0.5 + pad_candles)
        end_plot_idx  = total_candles + pad_candles - 1

        df_copy['EMA_21'] = df_copy['Close'].ewm(span=21, adjust=False).mean()

        mc = mpf.make_marketcolors(up='#26a69a', down='#ef5350', edge='inherit', wick='inherit')
        s  = mpf.make_mpf_style(marketcolors=mc, gridcolor='#2a2e39', facecolor='#131722')
        ema_plot = mpf.make_addplot(df_copy['EMA_21'], color='#ce93d8', width=1.2)

        highest_price = df_copy['High'].max()
        lowest_price  = df_copy['Low'].min()
        price_range   = highest_price - lowest_price
        y_pad         = price_range * 0.05 if price_range > 0 else 1.0

        fig, axes = mpf.plot(
            df_copy, type='candle', style=s, addplot=ema_plot,
            returnfig=True, figsize=(13, 7), axisoff=False,
            xlim=x_limits,
            ylim=(lowest_price - y_pad, highest_price + y_pad),
            tight_layout=True
        )
        ax = axes[0]
        ax.get_xaxis().set_visible(False)
        ax.yaxis.tick_right()
        ax.tick_params(axis='y', colors='#848e9c', labelsize=9)

        current_close = float(df_copy['Close'].iloc[-1])

        # ── H1 Entry Zone (tham chiếu từ H1 context) ──────────────
        direction = h1_context.get('direction', 'WAIT')
        ez = h1_context.get('entry_zone') or {}
        try:
            ez_top = float(ez.get('price_top', 0))
            ez_bot = float(ez.get('price_bot', 0))
        except (TypeError, ValueError):
            ez_top = ez_bot = 0.0

        if ez_top > 0 and ez_bot > 0 and ez_top != ez_bot:
            zone_color = '#26a69a' if direction == 'BUY' else '#ef5350'
            ax.axhspan(ez_bot, ez_top, alpha=0.18, color=zone_color)
            ax.axhline(ez_top, color=zone_color, linestyle='--', linewidth=0.8, alpha=0.7)
            ax.axhline(ez_bot, color=zone_color, linestyle='--', linewidth=0.8, alpha=0.7)
            ax.text(end_plot_idx, (ez_top + ez_bot) / 2,
                    f' H1 Zone\n {ez.get("zone_type","")}',
                    color=zone_color, fontsize=6, weight='bold', va='center')

        # ── FVG M5 (chỉ từ nến đã đóng) ──────────────────────────
        entry_fvg = M5EntryUtil.find_nearest_fvg(df_copy, direction, current_close)
        if entry_fvg:
            fvg_color = '#26a69a' if entry_fvg['type'] == 'FVG_BULL' else '#ef5350'
            ax.axhspan(entry_fvg['bottom'], entry_fvg['top'],
                       alpha=0.30, color=fvg_color)
            ax.axhline(entry_fvg['mid'],
                       color=fvg_color, linestyle='--', linewidth=1.0, alpha=0.9)
            ax.text(end_plot_idx, entry_fvg['mid'],
                    ' FVG M5', color=fvg_color, fontsize=7, weight='bold', va='center')

        # ── CHoCH marker (chỉ từ nến đã đóng) ────────────────────
        choch = M5EntryUtil.detect_choch(df_copy)
        if choch:
            choch_color = '#26a69a' if choch['type'] == 'CHoCH_BULL' else '#ef5350'
            ax.axvline(x=choch['candle_idx'],
                       color=choch_color, linestyle=':', linewidth=1.2, alpha=0.8)
            ax.text(choch['candle_idx'], highest_price + y_pad * 0.3,
                    f" {choch['type']}", color=choch_color,
                    fontsize=7, weight='bold', va='top', rotation=90)

        # ── PDH / PDL từ H1 context (nếu có) ─────────────────────
        pdh = h1_context.get('pdh')
        pdl = h1_context.get('pdl')
        if pdh:
            ax.axhline(float(pdh), color='#ff6b6b',
                       linestyle='--', linewidth=0.8, alpha=0.5)
            ax.text(end_plot_idx, float(pdh), ' PDH',
                    color='#ff6b6b', fontsize=6, va='bottom')
        if pdl:
            ax.axhline(float(pdl), color='#69db7c',
                       linestyle='--', linewidth=0.8, alpha=0.5)
            ax.text(end_plot_idx, float(pdl), ' PDL',
                    color='#69db7c', fontsize=6, va='top')

        # ── Label H1 Direction (không có Daily) ───────────────────
        dir_color = ('#26a69a' if direction == 'BUY'
                     else '#ef5350' if direction == 'SELL'
                     else '#a8a8a8')
        ax.text(0.01, 0.97,
                f'H1: {direction} | M5 Entry Scan',
                transform=ax.transAxes, color=dir_color,
                fontsize=9, weight='bold', va='top')

        last_time   = df.index[-1].strftime("%Y%m%d_%H%M")
        output_path = os.path.join(folder, f"m5_ict_{last_time}.png")
        fig.savefig(output_path, bbox_inches='tight', pad_inches=0.1, dpi=150)
        plt.close(fig)

        # ── Swing SL reference (pullback method) ──────────────────
        swing_sl_buy  = M5EntryUtil.find_sl_swing(df_copy, 'BUY')
        swing_sl_sell = M5EntryUtil.find_sl_swing(df_copy, 'SELL')

        # ── M5 payload ────────────────────────────────────────────
        m5_payload = {
            "timestamp":        df.index[-1].strftime("%Y-%m-%d %H:%M"),
            # Hướng từ H1 (để find_nearest_fvg biết tìm loại nào)
            "h1_direction":     direction,
            "current_price":    current_close,
            "ema_21":           float(df_copy['EMA_21'].iloc[-1]),
            "price_vs_ema21":   "ABOVE" if current_close > float(df_copy['EMA_21'].iloc[-1])
                                else "BELOW",
            # CHoCH & FVG — chỉ từ nến đã đóng
            "choch":            choch,
            "entry_fvg":        entry_fvg,
            # Swing SL cho trader.py (pullback method)
            "swing_low_for_sl":  swing_sl_buy,    # dùng khi BUY
            "swing_high_for_sl": swing_sl_sell,   # dùng khi SELL
            # H1 entry zone để AI M5 tham chiếu
            "h1_entry_zone":    ez,
            "h1_target":        h1_context.get('target'),
            "h1_invalidation":  h1_context.get('invalidation'),
        }

        print(f"✅ [M5] Chart saved → {output_path}")
        return output_path, m5_payload
