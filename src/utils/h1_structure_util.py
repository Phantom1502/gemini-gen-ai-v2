"""
h1_structure_util.py
====================
ICT H1 Structure Analyzer - V2
Nhận daily_bias payload từ DailyBiasUtil, phân tích cấu trúc H1
để xác định hướng giá ngắn hạn (Bullish/Bearish swing) và
các vùng POI (FVG, OB, Mitigation Block) làm mồi cho M5 entry.
"""

import os
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import mplfinance as mpf
from typing import Dict, List, Tuple, Optional


class H1StructureUtil:
    """
    Phân tích cấu trúc H1 theo lý thuyết ICT:
    - BOS / CHoCH (Break of Structure / Change of Character)
    - Fair Value Gap (FVG / Imbalance)
    - Order Block (OB) cuối cùng trước khi có displacement
    - Hướng dẫn bot M5 tìm entry
    """

    # ──────────────────────────────────────────────
    # 1. BOS / CHoCH
    # ──────────────────────────────────────────────
    @staticmethod
    def detect_market_structure(df: pd.DataFrame, swing_window: int = 3) -> List[Dict]:
        """
        Phát hiện chuỗi đỉnh/đáy và đánh dấu BOS (Break of Structure)
        và CHoCH (Change of Character).

        Returns list các sự kiện cấu trúc theo thứ tự thời gian.
        """
        highs  = df['High'].values
        lows   = df['Low'].values
        closes = df['Close'].values
        length = len(df)

        # Tìm swing high / low
        swing_highs = []
        swing_lows  = []
        for i in range(swing_window, length - swing_window):
            if highs[i] == max(highs[i - swing_window: i + swing_window + 1]):
                swing_highs.append((i, float(highs[i])))
            if lows[i] == min(lows[i - swing_window: i + swing_window + 1]):
                swing_lows.append((i, float(lows[i])))

        events = []

        # Phát hiện BOS tăng: close phá qua swing high trước đó
        for idx_h, price_h in swing_highs:
            for t in range(idx_h + 1, length):
                if closes[t] > price_h:
                    events.append({
                        'type': 'BOS_BULL',
                        'candle_idx': t,
                        'price': price_h,
                        'broken_at': float(closes[t])
                    })
                    break

        # Phát hiện BOS giảm: close phá qua swing low trước đó
        for idx_l, price_l in swing_lows:
            for t in range(idx_l + 1, length):
                if closes[t] < price_l:
                    events.append({
                        'type': 'BOS_BEAR',
                        'candle_idx': t,
                        'price': price_l,
                        'broken_at': float(closes[t])
                    })
                    break

        events.sort(key=lambda x: x['candle_idx'])
        return events

    # ──────────────────────────────────────────────
    # 2. FAIR VALUE GAP (FVG)
    # ──────────────────────────────────────────────
    @staticmethod
    def find_fvg(df: pd.DataFrame) -> List[Dict]:
        """
        Tìm Fair Value Gap (3-candle imbalance):
        - Bullish FVG: low[i+2] > high[i]  →  gap phía trên nến i
        - Bearish FVG: high[i+2] < low[i]  →  gap phía dưới nến i
        """
        highs  = df['High'].values
        lows   = df['Low'].values
        length = len(df)
        fvgs   = []

        for i in range(length - 2):
            # Bullish FVG
            if lows[i + 2] > highs[i]:
                fvgs.append({
                    'type':      'FVG_BULL',
                    'start_idx': i,
                    'top':       float(lows[i + 2]),
                    'bottom':    float(highs[i]),
                    'mid':       float((lows[i + 2] + highs[i]) / 2),
                    'filled':    False
                })
            # Bearish FVG
            if highs[i + 2] < lows[i]:
                fvgs.append({
                    'type':      'FVG_BEAR',
                    'start_idx': i,
                    'top':       float(lows[i]),
                    'bottom':    float(highs[i + 2]),
                    'mid':       float((lows[i] + highs[i + 2]) / 2),
                    'filled':    False
                })

        # Đánh dấu FVG đã bị lấp (price chạm vào vùng)
        for fvg in fvgs:
            for t in range(fvg['start_idx'] + 3, length):
                if fvg['type'] == 'FVG_BULL' and lows[t] <= fvg['top']:
                    fvg['filled'] = True
                    break
                if fvg['type'] == 'FVG_BEAR' and highs[t] >= fvg['bottom']:
                    fvg['filled'] = True
                    break

        return fvgs

    # ──────────────────────────────────────────────
    # 3. ORDER BLOCK (OB)
    # ──────────────────────────────────────────────
    @staticmethod
    def find_order_blocks(df: pd.DataFrame, lookback: int = 30) -> List[Dict]:
        """
        Tìm Order Block:
        - Bullish OB: nến giảm cuối cùng trước một chuỗi tăng mạnh (displacement up)
        - Bearish OB: nến tăng cuối cùng trước một chuỗi giảm mạnh (displacement down)

        Displacement được định nghĩa là nến có body > 1.5x average body 10 nến trước đó.
        """
        opens  = df['Open'].values
        highs  = df['High'].values
        lows   = df['Low'].values
        closes = df['Close'].values
        length = len(df)
        obs    = []

        for i in range(10, length - 1):
            avg_body = np.mean(np.abs(closes[i - 10:i] - opens[i - 10:i]))
            body_i1  = abs(closes[i + 1] - opens[i + 1])

            if avg_body == 0:
                continue

            # Bullish OB: nến i là nến giảm, nến i+1 là nến tăng displacement
            if (closes[i] < opens[i]
                    and closes[i + 1] > opens[i + 1]
                    and body_i1 > avg_body * 1.5
                    and i >= length - lookback):
                obs.append({
                    'type':      'OB_BULL',
                    'candle_idx': i,
                    'top':        float(highs[i]),
                    'bottom':     float(lows[i]),
                    'mitigated':  False
                })

            # Bearish OB: nến i là nến tăng, nến i+1 là nến giảm displacement
            if (closes[i] > opens[i]
                    and closes[i + 1] < opens[i + 1]
                    and body_i1 > avg_body * 1.5
                    and i >= length - lookback):
                obs.append({
                    'type':      'OB_BEAR',
                    'candle_idx': i,
                    'top':        float(highs[i]),
                    'bottom':     float(lows[i]),
                    'mitigated':  False
                })

        # Đánh dấu OB đã bị mitigation (price chạm lại vùng OB)
        for ob in obs:
            for t in range(ob['candle_idx'] + 2, length):
                if ob['type'] == 'OB_BULL' and lows[t] <= ob['top']:
                    ob['mitigated'] = True
                    break
                if ob['type'] == 'OB_BEAR' and highs[t] >= ob['bottom']:
                    ob['mitigated'] = True
                    break

        return obs

    # ──────────────────────────────────────────────
    # 4. VẼ BIỂU ĐỒ H1 + POI
    # ──────────────────────────────────────────────
    @staticmethod
    def generate_h1_chart(
        df: pd.DataFrame,
        daily_bias: str,          # "BULLISH" | "BEARISH" | "NEUTRAL"
        daily_payload: Dict,
        folder: str = "data/charts",
        right_pad_pct: float = 0.10
    ) -> Tuple[str, Dict]:
        """
        Vẽ biểu đồ H1 với các POI ICT (FVG, OB, BSL/SSL từ daily payload).
        Trả về (image_path, h1_payload) để Bot M5 tiêu thụ.
        """
        os.makedirs(folder, exist_ok=True)

        total_candles = len(df)
        pad_candles   = max(int(total_candles * right_pad_pct), 3)
        x_limits      = (-0.5, total_candles - 0.5 + pad_candles)
        end_plot_idx  = total_candles + pad_candles - 1

        highest_price = df['High'].max()
        lowest_price  = df['Low'].min()
        price_range   = highest_price - lowest_price
        y_pad         = price_range * 0.05 if price_range > 0 else 1.0
        y_limits      = (lowest_price - y_pad, highest_price + y_pad)

        mc = mpf.make_marketcolors(up='#26a69a', down='#ef5350', edge='inherit', wick='inherit')
        s  = mpf.make_mpf_style(marketcolors=mc, gridcolor='#2a2e39', facecolor='#131722')

        # EMA 50 làm xu hướng tham chiếu H1
        df_copy = df.copy()
        df_copy['EMA_50'] = df_copy['Close'].ewm(span=50, adjust=False).mean()
        ema_plot = mpf.make_addplot(df_copy['EMA_50'], color='#fbc02d', width=1.2)

        fig, axes = mpf.plot(
            df_copy, type='candle', style=s, addplot=ema_plot,
            returnfig=True, figsize=(13, 7), axisoff=False,
            xlim=x_limits, ylim=y_limits, tight_layout=True
        )
        ax = axes[0]
        ax.get_xaxis().set_visible(False)
        ax.yaxis.tick_right()
        ax.tick_params(axis='y', colors='#848e9c', labelsize=9)

        # ── Vẽ FVG ────────────────────────────────
        fvgs = H1StructureUtil.find_fvg(df_copy)
        for fvg in fvgs:
            if fvg['filled']:
                continue
            color = '#26a69a' if fvg['type'] == 'FVG_BULL' else '#ef5350'
            ax.axhspan(fvg['bottom'], fvg['top'], alpha=0.12, color=color)
            ax.axhline(fvg['mid'], color=color, linestyle=':', linewidth=0.8, alpha=0.5)

        # ── Vẽ Order Block ─────────────────────────
        obs = H1StructureUtil.find_order_blocks(df_copy, lookback=40)
        for ob in obs:
            if ob['mitigated']:
                continue
            color = '#26a69a' if ob['type'] == 'OB_BULL' else '#ef5350'
            ax.axhspan(ob['bottom'], ob['top'], alpha=0.20, color=color, hatch='//')
            label = 'OB↑' if ob['type'] == 'OB_BULL' else 'OB↓'
            ax.text(end_plot_idx, (ob['top'] + ob['bottom']) / 2,
                    f' {label}', color=color, fontsize=7, weight='bold', va='center')

        # ── Daily PDH / PDL từ payload ──────────────
        anchors = daily_payload.get('yesterday_anchors', {})
        pdh = anchors.get('PDH')
        pdl = anchors.get('PDL')
        if pdh:
            ax.axhline(pdh, color='#ff6b6b', linestyle='--', linewidth=1.0, alpha=0.7)
            ax.text(end_plot_idx, pdh, ' PDH', color='#ff6b6b', fontsize=7, va='bottom')
        if pdl:
            ax.axhline(pdl, color='#69db7c', linestyle='--', linewidth=1.0, alpha=0.7)
            ax.text(end_plot_idx, pdl, ' PDL', color='#69db7c', fontsize=7, va='top')

        # ── Label Daily Bias ───────────────────────
        bias_color = '#26a69a' if daily_bias == 'BULLISH' else '#ef5350' if daily_bias == 'BEARISH' else '#a8a8a8'
        ax.text(0.01, 0.97, f'Daily Bias: {daily_bias}',
                transform=ax.transAxes, color=bias_color,
                fontsize=10, weight='bold', va='top')

        last_time   = df.index[-1].strftime("%Y%m%d_%H%M")
        output_path = os.path.join(folder, f"h1_ict_{last_time}.png")
        fig.savefig(output_path, bbox_inches='tight', pad_inches=0.1, dpi=150)
        plt.close(fig)

        # ── H1 payload cho Bot M5 ──────────────────
        current_close = float(df_copy['Close'].iloc[-1])
        active_fvgs   = [f for f in fvgs if not f['filled']]
        active_obs    = [o for o in obs  if not o['mitigated']]

        # Tìm POI gần nhất thuận theo Daily Bias
        poi_target = None
        if daily_bias == 'BULLISH':
            # Tìm FVG_BULL / OB_BULL phía dưới giá hiện tại (vùng để giá hồi về mua)
            candidates = [
                f for f in active_fvgs if f['type'] == 'FVG_BULL' and f['top'] < current_close
            ] + [
                o for o in active_obs if o['type'] == 'OB_BULL' and o['top'] < current_close
            ]
            if candidates:
                poi_target = max(candidates, key=lambda x: x.get('top', x.get('top')))
        elif daily_bias == 'BEARISH':
            candidates = [
                f for f in active_fvgs if f['type'] == 'FVG_BEAR' and f['bottom'] > current_close
            ] + [
                o for o in active_obs if o['type'] == 'OB_BEAR' and o['bottom'] > current_close
            ]
            if candidates:
                poi_target = min(candidates, key=lambda x: x.get('bottom', x.get('bottom')))

        # Đánh giá BOS gần nhất
        structure_events = H1StructureUtil.detect_market_structure(df_copy)
        last_bos = structure_events[-1] if structure_events else None

        h1_payload = {
            "timestamp": df.index[-1].strftime("%Y-%m-%d %H:%M"),
            "daily_bias": daily_bias,
            "current_price": current_close,
            "ema_50": float(df_copy['EMA_50'].iloc[-1]),
            "price_vs_ema50": "ABOVE" if current_close > float(df_copy['EMA_50'].iloc[-1]) else "BELOW",
            "poi_target": poi_target,
            "last_bos": last_bos,
            "active_fvg_count": len(active_fvgs),
            "active_ob_count": len(active_obs),
            "active_fvgs": active_fvgs[-3:],   # chỉ giữ 3 FVG gần nhất
            "active_obs":  active_obs[-3:],
        }

        print(f"✅ [H1] Chart saved → {output_path}")
        return output_path, h1_payload
