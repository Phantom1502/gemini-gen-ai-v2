"""
daily_bias_util.py  (V2.1)
==========================
ICT Daily Bias Generator
- Dùng resample_h1_to_daily_oanda() để chart Daily khớp với OANDA
- Helper resample_h1_to_daily giữ lại để tương thích với backtester
"""

import os
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import mplfinance as mpf
from typing import Dict, List, Tuple, Optional

from utils.mt5util import resample_h1_to_daily_oanda


class DailyBiasUtil:
    """
    Phân tích và vẽ biểu đồ Daily theo lý thuyết ICT.
    Trả về chart image + numerical payload để Bot H1 tiêu thụ.
    """

    # ──────────────────────────────────────────────
    # 1. PHÂN TÍCH VÒNG ĐỜI THANH KHOẢN BSL / SSL
    # ──────────────────────────────────────────────
    @staticmethod
    def analyze_liquidity_lifecycles(df: pd.DataFrame, swing_window: int = 2) -> List[Dict]:
        """
        Xác định vòng đời của các đường thanh khoản (BSL/SSL):
        - active  : chưa bị tác động
        - swept   : bị quét wick nhưng close chưa phá
        - broken  : close đã phá hoàn toàn
        """
        highs  = df['High'].values
        lows   = df['Low'].values
        closes = df['Close'].values
        length = len(df)

        liquidity_lines: List[Dict] = []

        for i in range(swing_window, length - swing_window):
            if highs[i] == max(highs[i - swing_window: i + swing_window + 1]):
                liquidity_lines.append({
                    'type': 'BSL', 'start_idx': i,
                    'price': float(highs[i]), 'end_idx': length - 1,
                    'status': 'active', 'swept_indices': []
                })
            if lows[i] == min(lows[i - swing_window: i + swing_window + 1]):
                liquidity_lines.append({
                    'type': 'SSL', 'start_idx': i,
                    'price': float(lows[i]), 'end_idx': length - 1,
                    'status': 'active', 'swept_indices': []
                })

        for line in liquidity_lines:
            start = line['start_idx']
            price = line['price']
            for t in range(start + 1, length):
                if line['type'] == 'BSL':
                    if closes[t] > price:
                        line['status'] = 'broken'; line['end_idx'] = t; break
                    elif highs[t] > price:
                        if line['status'] == 'active':
                            line['status'] = 'swept'
                        if t not in line['swept_indices']:
                            line['swept_indices'].append(t)
                elif line['type'] == 'SSL':
                    if closes[t] < price:
                        line['status'] = 'broken'; line['end_idx'] = t; break
                    elif lows[t] < price:
                        if line['status'] == 'active':
                            line['status'] = 'swept'
                        if t not in line['swept_indices']:
                            line['swept_indices'].append(t)

        return liquidity_lines

    # ──────────────────────────────────────────────
    # 2. VẼ ĐỒ THỊ DAILY ICT CLEAN
    # ──────────────────────────────────────────────
    @staticmethod
    def generate_daily_chart(
        df: pd.DataFrame,
        folder: str = "data/charts",
        right_pad_pct: float = 0.15
    ) -> Tuple[str, Dict]:
        """
        Vẽ biểu đồ Daily theo chuẩn ICT Dark Theme.
        Nến cuối cùng = nến Daily hiện tại (hoặc hôm qua nếu chưa kết thúc).

        Returns
        -------
        (image_path, numerical_payload)
        """
        os.makedirs(folder, exist_ok=True)

        total_candles = len(df)
        if total_candles == 0:
            raise ValueError("DataFrame trống.")

        yesterday_idx        = total_candles - 1
        yesterday            = df.iloc[yesterday_idx]
        pdh_price            = float(yesterday['High'])
        pdl_price            = float(yesterday['Low'])
        yesterday_open_price = float(yesterday['Open'])
        yesterday_close_price= float(yesterday['Close'])

        pad_candles  = max(int(total_candles * right_pad_pct), 3)
        x_limits     = (-0.5, total_candles - 0.5 + pad_candles)
        end_plot_idx = total_candles + pad_candles - 1

        highest_price = df['High'].max()
        lowest_price  = df['Low'].min()
        price_range   = highest_price - lowest_price
        y_pad         = price_range * 0.05 if price_range > 0 else 1.0
        y_limits      = (lowest_price - y_pad, highest_price + y_pad)

        mc = mpf.make_marketcolors(up='#26a69a', down='#ef5350', edge='inherit', wick='inherit')
        s  = mpf.make_mpf_style(marketcolors=mc, gridcolor='#2a2e39', facecolor='#131722')

        fig, axes = mpf.plot(
            df, type='candle', style=s, returnfig=True,
            figsize=(11, 7), axisoff=False,
            xlim=x_limits, ylim=y_limits, tight_layout=True
        )
        ax = axes[0]
        ax.get_xaxis().set_visible(False)
        ax.yaxis.tick_right()
        ax.tick_params(axis='y', colors='#848e9c', labelsize=9)

        # ── BSL / SSL ──────────────────────────────
        liq_lines = DailyBiasUtil.analyze_liquidity_lifecycles(df, swing_window=2)
        for line in liq_lines:
            base_color = '#ff9100' if line['type'] == 'BSL' else '#00b0ff'
            if line['status'] == 'broken':
                ax.plot([line['start_idx'], line['end_idx']],
                        [line['price'], line['price']],
                        color=base_color, linestyle=':', linewidth=0.8, alpha=0.3)
            elif line['status'] == 'swept':
                ax.plot([line['start_idx'], yesterday_idx],
                        [line['price'], line['price']],
                        color=base_color, linestyle='-', linewidth=1.0, alpha=0.4)
                for si in line['swept_indices']:
                    ax.scatter(si, line['price'], color='#ffea00', marker='x', s=25, zorder=5)
            elif line['status'] == 'active':
                ax.plot([line['start_idx'], end_plot_idx],
                        [line['price'], line['price']],
                        color=base_color, linestyle='-', linewidth=1.5, alpha=0.7)
                va = 'bottom' if line['type'] == 'BSL' else 'top'
                ax.text(total_candles, line['price'], f" {line['type']}",
                        color=base_color, fontsize=7, weight='bold', va=va)

        # ── PDH / PDL ──────────────────────────────
        ax.axhline(pdh_price, color='#ff6b6b', linestyle='--', linewidth=1.0, alpha=0.6)
        ax.axhline(pdl_price, color='#69db7c', linestyle='--', linewidth=1.0, alpha=0.6)
        ax.text(end_plot_idx, pdh_price, ' PDH', color='#ff6b6b', fontsize=7, va='bottom')
        ax.text(end_plot_idx, pdl_price, ' PDL', color='#69db7c', fontsize=7, va='top')

        # ── Equilibrium ────────────────────────────
        eq_price = (pdh_price + pdl_price) / 2
        ax.axhline(eq_price, color='#a8a8a8', linestyle=':', linewidth=0.8, alpha=0.5)
        ax.text(end_plot_idx, eq_price, ' EQ', color='#a8a8a8', fontsize=7, va='center')

        last_time   = df.index[-1].strftime("%Y%m%d")
        output_path = os.path.join(folder, f"daily_ict_{last_time}.png")
        fig.savefig(output_path, bbox_inches='tight', pad_inches=0.1, dpi=180)
        plt.close(fig)

        # ── Numerical payload ──────────────────────
        equilibrium_price = float(eq_price)
        price_position    = "PREMIUM" if yesterday_close_price > equilibrium_price else "DISCOUNT"

        recent_swept = []
        for l in liq_lines:
            if l['status'] == 'swept' and l['swept_indices']:
                candles_ago = yesterday_idx - l['swept_indices'][-1]
                if candles_ago <= 5:
                    recent_swept.append({
                        "type": f"{l['type']}_SWEPT",
                        "price": float(l['price']),
                        "swept_at_candles_ago": int(candles_ago)
                    })

        payload = {
            "target_date": last_time,
            "market_context": {
                "current_price": yesterday_close_price,
                "total_candles_analyzed": total_candles,
                "price_zone_vs_equilibrium": price_position
            },
            "mathematical_metrics": {
                "equilibrium": equilibrium_price,
                "distance_to_equilibrium_pct": round(
                    ((yesterday_close_price - equilibrium_price) / equilibrium_price) * 100, 3
                )
            },
            "yesterday_anchors": {
                "PDH": pdh_price,
                "PDL": pdl_price,
                "yesterday_open": yesterday_open_price,
                "yesterday_close": yesterday_close_price,
                "is_yesterday_bearish": bool(yesterday_close_price < yesterday_open_price)
            },
            "liquidity_map": {
                "active_liquidity": [
                    {
                        "type": l['type'],
                        "price": float(l['price']),
                        "distance_pct": round(
                            ((float(l['price']) - yesterday_close_price) / yesterday_close_price) * 100, 3
                        )
                    }
                    for l in liq_lines if l['status'] == 'active'
                ],
                "recently_swept_liquidity": recent_swept
            }
        }

        print(f"✅ [DAILY] Chart saved → {output_path}")
        return output_path, payload

    # ──────────────────────────────────────────────
    # 3. HELPER: Resample (backward compat)
    # ──────────────────────────────────────────────
    @staticmethod
    def resample_h1_to_daily(df_h1: pd.DataFrame, tail: int = 22) -> pd.DataFrame:
        """Wrapper backward-compatible, dùng chuẩn OANDA (offset 20h GMT)."""
        return resample_h1_to_daily_oanda(df_h1, tail=tail)
