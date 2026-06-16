"""
m5_entry_util.py
================
ICT M5 Entry Finder - V2
Nhận H1 payload, phân tích M5 để tìm cấu trúc entry:
- CHoCH M5 xác nhận hướng
- FVG M5 / Breaker Block làm entry zone
- Vẽ chart M5 cho AI Vision phân tích
"""

import os
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import mplfinance as mpf
from typing import Dict, List, Tuple, Optional


class M5EntryUtil:
    """
    Phân tích M5 để tìm điểm vào lệnh ICT:
    1. Xác nhận CHoCH M5 thuận với Daily Bias
    2. Tìm FVG / OB M5 làm entry zone
    3. Vẽ chart M5 clean cho AI Vision
    """

    # ──────────────────────────────────────────────
    # 1. CHoCH M5 - CHANGE OF CHARACTER
    # ──────────────────────────────────────────────
    @staticmethod
    def detect_choch(df: pd.DataFrame, swing_window: int = 3) -> Optional[Dict]:
        """
        Phát hiện CHoCH (Change of Character) gần nhất trên M5.
        CHoCH = cấu trúc thị trường vừa đảo chiều (BOS ngược hướng cũ).
        Trả về sự kiện CHoCH gần nhất, hoặc None nếu chưa có.
        """
        highs  = df['High'].values
        lows   = df['Low'].values
        closes = df['Close'].values
        length = len(df)

        swing_highs = []
        swing_lows  = []
        for i in range(swing_window, length - swing_window):
            if highs[i] == max(highs[i - swing_window: i + swing_window + 1]):
                swing_highs.append((i, float(highs[i])))
            if lows[i] == min(lows[i - swing_window: i + swing_window + 1]):
                swing_lows.append((i, float(lows[i])))

        # CHoCH Bullish: sau một chuỗi đáy thấp dần, giá phá qua swing high gần nhất
        # CHoCH Bearish: sau một chuỗi đỉnh cao dần, giá phá qua swing low gần nhất
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

        # Trả về CHoCH gần nhất
        return max(choch_events, key=lambda x: x['candle_idx'])

    # ──────────────────────────────────────────────
    # 2. FVG M5 GẦN NHẤT (ENTRY ZONE)
    # ──────────────────────────────────────────────
    @staticmethod
    def find_nearest_fvg(df: pd.DataFrame, direction: str, current_price: float) -> Optional[Dict]:
        """
        Tìm FVG M5 chưa bị lấp gần nhất theo hướng.
        direction: "BULLISH" → tìm FVG_BULL dưới giá (pullback zone)
                   "BEARISH" → tìm FVG_BEAR trên giá
        """
        highs  = df['High'].values
        lows   = df['Low'].values
        closes = df['Close'].values
        length = len(df)

        fvgs = []
        for i in range(length - 2):
            if lows[i + 2] > highs[i]:      # Bullish FVG
                fvgs.append({
                    'type': 'FVG_BULL',
                    'start_idx': i,
                    'top':    float(lows[i + 2]),
                    'bottom': float(highs[i]),
                    'mid':    float((lows[i + 2] + highs[i]) / 2),
                    'filled': False
                })
            if highs[i + 2] < lows[i]:      # Bearish FVG
                fvgs.append({
                    'type': 'FVG_BEAR',
                    'start_idx': i,
                    'top':    float(lows[i]),
                    'bottom': float(highs[i + 2]),
                    'mid':    float((lows[i] + highs[i + 2]) / 2),
                    'filled': False
                })

        # Đánh dấu đã lấp
        for fvg in fvgs:
            for t in range(fvg['start_idx'] + 3, length):
                if fvg['type'] == 'FVG_BULL' and lows[t] <= fvg['top']:
                    fvg['filled'] = True; break
                if fvg['type'] == 'FVG_BEAR' and highs[t] >= fvg['bottom']:
                    fvg['filled'] = True; break

        unfilled = [f for f in fvgs if not f['filled']]

        if direction == 'BULLISH':
            candidates = [f for f in unfilled if f['type'] == 'FVG_BULL' and f['top'] < current_price]
            return max(candidates, key=lambda x: x['top']) if candidates else None
        elif direction == 'BEARISH':
            candidates = [f for f in unfilled if f['type'] == 'FVG_BEAR' and f['bottom'] > current_price]
            return min(candidates, key=lambda x: x['bottom']) if candidates else None
        return None

    # ──────────────────────────────────────────────
    # 3. VẼ CHART M5 ENTRY
    # ──────────────────────────────────────────────
    @staticmethod
    def generate_m5_chart(
        df: pd.DataFrame,
        daily_bias: str,
        h1_payload: Dict,
        folder: str = "data/charts",
        right_pad_pct: float = 0.08
    ) -> Tuple[str, Dict]:
        """
        Vẽ biểu đồ M5 với EMA 21, FVG entry zone, CHoCH marker.
        Trả về (image_path, m5_payload) cho AI Vision phán quyết cuối cùng.
        """
        os.makedirs(folder, exist_ok=True)

        df_copy = df.copy()
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

        # ── FVG M5 ────────────────────────────────
        entry_fvg = M5EntryUtil.find_nearest_fvg(df_copy, daily_bias, current_close)
        if entry_fvg:
            fvg_color = '#26a69a' if entry_fvg['type'] == 'FVG_BULL' else '#ef5350'
            ax.axhspan(entry_fvg['bottom'], entry_fvg['top'], alpha=0.25, color=fvg_color)
            ax.axhline(entry_fvg['mid'], color=fvg_color, linestyle='--', linewidth=1.0, alpha=0.8)
            ax.text(end_plot_idx, entry_fvg['mid'],
                    ' FVG Entry', color=fvg_color, fontsize=7, weight='bold', va='center')

        # ── CHoCH marker ───────────────────────────
        choch = M5EntryUtil.detect_choch(df_copy)
        if choch:
            choch_color = '#26a69a' if choch['type'] == 'CHoCH_BULL' else '#ef5350'
            ax.axvline(x=choch['candle_idx'], color=choch_color, linestyle=':', linewidth=1.0, alpha=0.6)
            ax.text(choch['candle_idx'], highest_price,
                    f" {choch['type']}", color=choch_color,
                    fontsize=7, weight='bold', va='top', rotation=90)

        # ── PDH / PDL từ H1 payload ────────────────
        anchors = h1_payload.get('daily_payload_anchors', {})
        pdh = h1_payload.get('pdh')
        pdl = h1_payload.get('pdl')
        if pdh:
            ax.axhline(pdh, color='#ff6b6b', linestyle='--', linewidth=0.8, alpha=0.6)
        if pdl:
            ax.axhline(pdl, color='#69db7c', linestyle='--', linewidth=0.8, alpha=0.6)

        # ── Label ─────────────────────────────────
        bias_color = '#26a69a' if daily_bias == 'BULLISH' else '#ef5350' if daily_bias == 'BEARISH' else '#a8a8a8'
        ax.text(0.01, 0.97, f'Daily: {daily_bias} | M5 Entry Scan',
                transform=ax.transAxes, color=bias_color,
                fontsize=9, weight='bold', va='top')

        last_time   = df.index[-1].strftime("%Y%m%d_%H%M")
        output_path = os.path.join(folder, f"m5_ict_{last_time}.png")
        fig.savefig(output_path, bbox_inches='tight', pad_inches=0.1, dpi=150)
        plt.close(fig)

        # ── M5 payload cho AI Vision ───────────────
        m5_payload = {
            "timestamp": df.index[-1].strftime("%Y-%m-%d %H:%M"),
            "daily_bias": daily_bias,
            "current_price": current_close,
            "ema_21": float(df_copy['EMA_21'].iloc[-1]),
            "price_vs_ema21": "ABOVE" if current_close > float(df_copy['EMA_21'].iloc[-1]) else "BELOW",
            "choch": choch,
            "entry_fvg": entry_fvg,
            "h1_poi": h1_payload.get('poi_target'),
            "h1_last_bos": h1_payload.get('last_bos'),
        }

        print(f"✅ [M5] Chart saved → {output_path}")
        return output_path, m5_payload
