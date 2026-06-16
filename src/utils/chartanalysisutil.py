import os
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import mplfinance as mpf

import os
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import mplfinance as mpf

class ChartAnalysisUtil:

    @staticmethod
    def _find_bob_volman_structural_barrier(df: pd.DataFrame, barrier_type: str = 'resistance', lookback: int = 60, min_touches: int = 3) -> tuple:
        """
        [PHIÊN BẢN v7.0 BREAKOUT-READY]
        Quét tìm đường cản cấu trúc (Ngang/Chéo) loại trừ nến cuối cùng khỏi bộ lọc vi phạm.
        Giúp giữ lại đường cản ngay cả khi nến hiện tại đang thực hiện cú Breakout.
        """
        highs = df['High'].values
        lows = df['Low'].values
        closes = df['Close'].values
        length = len(df)
        current_idx = length - 1  # Index của cây nến cuối cùng (nến hiện tại)
        
        # Sai số động chấp nhận được (khoảng 0.04% giá hiện tại)
        allowed_delta = closes[current_idx] * 0.0004 
        window = 3          
        min_candle_gap = 3  

        best_anchor_idx = None
        best_slope = None
        best_intercept = None
        max_touches = -1
        min_avg_dist = float('inf')

        # 1. Tìm Điểm Neo (Anchor Point) uy tín trong quá khứ làm tâm xoay
        for i in range(current_idx - 10, current_idx - lookback, -1):
            if i - window < 0 or i + window >= length: continue
            
            is_anchor = False
            price_anchor = 0.0
            if barrier_type == 'resistance' and highs[i] == max(highs[i - window : i + window + 1]):
                is_anchor = True; price_anchor = highs[i]
            elif barrier_type == 'support' and lows[i] == min(lows[i - window : i + window + 1]):
                is_anchor = True; price_anchor = lows[i]
            
            if is_anchor:
                # 2. Quét tia xoay qua các nến trung gian để tìm độ dốc (Slope)
                # Chỉ quét điểm tựa thứ hai đến nến current_idx - 2 để đảm bảo tính khách quan cho nến cuối
                for j in range(i + 4, current_idx - 1):
                    price_j = highs[j] if barrier_type == 'resistance' else lows[j]
                    slope = (price_j - price_anchor) / (j - i)
                    
                    # Bộ lọc hướng độ dốc Bob Volman
                    if barrier_type == 'resistance' and slope > 0.00001: continue
                    if barrier_type == 'support' and slope < -0.00001: continue
                    
                    # 3. SỬA LỖI TẠI ĐÂY: Vòng lặp chỉ chạy đến `current_idx` (tức là dừng lại ở nến current_idx - 1)
                    # Hoàn toàn bỏ qua hành vi của nến cuối cùng để chuẩn bị cho kịch bản Breakout
                    is_valid = True
                    touches = 1  
                    last_touch_idx = i  
                    total_dist = 0.0
                    steps = 0
                    
                    for k in range(i + 1, current_idx):
                        proj_k = price_anchor + slope * (k - i)
                        
                        # Bộ lọc vi phạm giá đóng cửa TRONG QUÁ KHỨ (không tính nến hiện tại)
                        if barrier_type == 'resistance' and closes[k] > proj_k:
                            is_valid = False; break
                        if barrier_type == 'support' and closes[k] < proj_k:
                            is_valid = False; break
                            
                        price_k = highs[k] if barrier_type == 'resistance' else lows[k]
                        dist = abs(price_k - proj_k)
                        
                        if dist <= allowed_delta:
                            if (k - last_touch_idx) >= min_candle_gap:
                                touches += 1
                                last_touch_idx = k  
                            
                        total_dist += dist
                        steps += 1
                    
                    # 4. Đánh giá đường cản dựa trên dữ liệu lịch sử sạch
                    if is_valid and touches >= min_touches:
                        avg_dist = total_dist / steps if steps > 0 else float('inf')
                        
                        if (touches > max_touches) or (touches == max_touches and avg_dist < min_avg_dist):
                            max_touches = touches
                            min_avg_dist = avg_dist
                            best_anchor_idx = i
                            best_slope = slope
                            best_intercept = price_anchor

        return best_anchor_idx, best_slope, best_intercept, max_touches

    @staticmethod
    def save_clean_chart_with_ema(df: pd.DataFrame, folder: str = "data/charts", right_pad_pct: float = 0.08, min_touches: int = 3) -> str:
        """
        Hàm chính vẽ đồ thị chuẩn AI Vision v7.0.
        Đường cản được giữ nguyên và kéo dài qua nến cuối, hiển thị rõ ràng cú đâm thủng nếu có Breakout.
        """
        if not os.path.exists(folder):
            os.makedirs(folder)

        last_time = df.index[-1].strftime("%Y%m%d_%H%M")
        output_path = os.path.join(folder, f"chart_{last_time}.png")

        df_copy = df.copy()
        total_candles = len(df_copy)
        current_idx = total_candles - 1
        
        df_copy['EMA_25'] = df_copy['Close'].ewm(span=25, adjust=False).mean()

        mc = mpf.make_marketcolors(up='#26a69a', down='#ef5350', edge='inherit', wick='inherit')
        s  = mpf.make_mpf_style(marketcolors=mc, gridcolor='#2a2e39', facecolor='#131722')
        ema_plot = mpf.make_addplot(df_copy['EMA_25'], color='#fbc02d', width=1.5)

        pad_candles = max(int(total_candles * right_pad_pct), 3) 
        x_limits = (-0.5, total_candles - 0.5 + pad_candles)

        fig, axes = mpf.plot(
            df_copy, type='candle', style=s, addplot=ema_plot,
            returnfig=True, figsize=(10, 6), axisoff=True, xlim=x_limits, tight_layout=True
        )
        ax = axes[0]

        # ==============================================================================
        # VẼ KHÁNG CỰ CẤU TRÚC (KÉO DÀI ĐẾN NẾN CUỐI ĐỂ HIỂN THỊ BREAKOUT)
        # ==============================================================================
        p_anc, p_slope, p_inter, p_touches = ChartAnalysisUtil._find_bob_volman_structural_barrier(
            df_copy, 'resistance', lookback=60, min_touches=min_touches
        )

        if p_slope is not None:
            # Tính toán tọa độ kéo dài đến tận nến hiện tại (current_idx)
            proj_p = float(p_inter + p_slope * (current_idx - p_anc))
            ax.plot([p_anc, current_idx], [p_inter, proj_p], color='#ff1744', linewidth=2.5)
            
            # Log kiểm tra trạng thái của nến cuối so với đường cản
            last_close = float(df_copy['Close'].iloc[current_idx])
            if last_close > proj_p:
                print(f"🚀 [v7.0 BREAKOUT DETECTED] Giá đóng cửa {last_close} đã VƯỢT KHỎI Kháng cự {proj_p:.4f}!")
            else:
                print(f"🎯 [v7.0 SOLID] Kháng cự giữ vững: Đi qua {p_touches} cụm cấu trúc.")
        else:
            print(f"⚠️ [v7.0] Không tìm thấy Kháng cự cấu trúc.")

        # ==============================================================================
        # VẼ HỖ TRỢ CẤU TRÚC (KÉO DÀI ĐẾN NẾN CUỐI ĐỂ HIỂN THỊ BREAKOUT)
        # ==============================================================================
        t_anc, t_slope, t_inter, t_touches = ChartAnalysisUtil._find_bob_volman_structural_barrier(
            df_copy, 'support', lookback=60, min_touches=min_touches
        )

        if t_slope is not None:
            # Tính toán tọa độ kéo dài đến tận nến hiện tại (current_idx)
            proj_t = float(t_inter + t_slope * (current_idx - t_anc))
            ax.plot([t_anc, current_idx], [t_inter, proj_t], color='#00e676', linewidth=2.5)
            
            # Log kiểm tra trạng thái của nến cuối so với đường cản
            last_close = float(df_copy['Close'].iloc[current_idx])
            if last_close < proj_t:
                print(f"🚀 [v7.0 BREAKOUT DETECTED] Giá đóng cửa {last_close} đã THỦNG Hỗ trợ {proj_t:.4f}!")
            else:
                print(f"🎯 [v7.0 SOLID] Hỗ trợ giữ vững: Đi qua {t_touches} cụm cấu trúc.")
        else:
            print(f"⚠️ [v7.0] Không tìm thấy Hỗ trợ cấu trúc.")

        fig.savefig(output_path, bbox_inches='tight', pad_inches=0.15, dpi=150)
        plt.close(fig)
        return output_path