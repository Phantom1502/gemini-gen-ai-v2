"""
backtester.py
=============
Backtest ICT V2 với file CSV lịch sử H1.
Mô phỏng đúng luồng: resample Daily → chart → AI → entry → log kết quả.

Cách dùng:
    python backtester.py
    python backtester.py --start 700 --end 1500 --step 4  (mỗi 4 nến H1 = 4 giờ)
"""

import argparse
import os
import json
import datetime
import pandas as pd
import matplotlib.pyplot as plt
from PIL import Image

import config
from utils.daily_bias_util   import DailyBiasUtil
from utils.h1_structure_util import H1StructureUtil
from utils.m5_entry_util     import M5EntryUtil
from utils.ict_ai_agent      import ICTAIAgent


# ══════════════════════════════════════════════════════════════════
# BACKTEST ENGINE
# ══════════════════════════════════════════════════════════════════

class Backtester:

    def __init__(
        self,
        csv_path:  str   = config.BACKTEST_CSV_PATH,
        start_idx: int   = config.BACKTEST_START_IDX,
        end_idx:   int   = None,
        step:      int   = config.BACKTEST_STEP,
        api_key:   str   = config.GEMINI_API_KEY,
        model_name: str  = config.GEMINI_MODEL,
        chart_folder: str = "data/backtest_charts",
        log_path:  str   = "data/logs/backtest_result.csv",
        call_ai:   bool  = True,   # False = chỉ tạo chart, không gọi AI (tiết kiệm quota)
    ):
        self.csv_path     = csv_path
        self.start_idx    = start_idx
        self.step         = step
        self.chart_folder = chart_folder
        self.log_path     = log_path
        self.call_ai      = call_ai

        os.makedirs(self.chart_folder, exist_ok=True)
        os.makedirs(os.path.dirname(log_path), exist_ok=True)

        # Load toàn bộ H1
        print(f"📂 Đọc CSV: {csv_path}")
        self.df_h1_full = pd.read_csv(
            csv_path,
            parse_dates=['Datetime']
        ).set_index('Datetime').sort_index()

        total = len(self.df_h1_full)
        self.end_idx = end_idx if end_idx else total
        print(f"   Tổng nến H1: {total} | Backtest từ {start_idx} đến {self.end_idx}")

        # AI agent (chỉ dùng nếu call_ai=True)
        self.agent = ICTAIAgent(api_key=api_key, model_name=model_name) if call_ai else None

        # Kết quả tích lũy
        self.results = []

    # ──────────────────────────────────────────────
    # CHẠY BACKTEST
    # ──────────────────────────────────────────────
    def run(self):
        indices = range(self.start_idx, self.end_idx, self.step)
        total   = len(indices)
        print(f"\n🚀 Bắt đầu backtest {total} bước (step={self.step})...\n")

        for step_num, current_idx in enumerate(indices, 1):

            # Lấy slice H1 để resample Daily (600 nến trước điểm hiện tại)
            h1_slice  = self.df_h1_full.iloc[max(0, current_idx - 600): current_idx + 1]
            h1_window = self.df_h1_full.iloc[max(0, current_idx - 60):  current_idx + 1]
            m5_proxy  = h1_window.tail(30)  # Dùng H1 giả lập M5 trong backtest

            if len(h1_slice) < 20:
                continue

            # Resample → Daily 20 nến
            df_daily = h1_slice.resample('D').agg(
                {'Open': 'first', 'High': 'max', 'Low': 'min', 'Close': 'last'}
            ).dropna().tail(20)

            if len(df_daily) < 5:
                continue

            current_time = self.df_h1_full.index[current_idx]
            print(f"\n[{step_num}/{total}] {current_time.strftime('%Y-%m-%d %H:%M')} | H1 idx={current_idx}")

            record = {
                "step":          step_num,
                "datetime":      current_time.strftime("%Y-%m-%d %H:%M"),
                "h1_idx":        current_idx,
                "daily_bias":    "",
                "h1_trend":      "",
                "m5_action":     "",
                "confidence":    "",
                "daily_img":     "",
                "h1_img":        "",
                "m5_img":        "",
                "daily_payload": {},
            }

            # ── Chart Daily ──────────────────────
            try:
                folder = os.path.join(self.chart_folder, f"step_{step_num:05d}")
                os.makedirs(folder, exist_ok=True)

                daily_img, daily_payload = DailyBiasUtil.generate_daily_chart(
                    df_daily, folder=folder
                )
                record["daily_img"]     = daily_img
                record["daily_payload"] = daily_payload
                print(f"   📊 Daily chart OK | Giá={daily_payload['market_context']['current_price']}")

            except Exception as e:
                print(f"   ❌ Daily chart lỗi: {e}")
                self.results.append(record)
                continue

            # ── Chart H1 ─────────────────────────
            try:
                h1_img, h1_payload = H1StructureUtil.generate_h1_chart(
                    h1_window.tail(60),
                    daily_bias="NEUTRAL",     # Sẽ cập nhật sau khi AI phân tích
                    daily_payload=daily_payload,
                    folder=folder,
                )
                record["h1_img"] = h1_img
            except Exception as e:
                print(f"   ❌ H1 chart lỗi: {e}")

            # ── Chart M5 (giả lập bằng H1 ngắn) ─
            try:
                m5_img, m5_payload = M5EntryUtil.generate_m5_chart(
                    m5_proxy,
                    daily_bias="NEUTRAL",
                    h1_payload=h1_payload if "h1_payload" in dir() else {},
                    folder=folder,
                )
                record["m5_img"] = m5_img
            except Exception as e:
                print(f"   ❌ M5 chart lỗi: {e}")

            # ── AI pipeline (nếu bật) ─────────────
            if self.call_ai and self.agent:
                try:
                    pipeline = self.agent.run_full_pipeline(
                        daily_img=daily_img,
                        daily_payload=daily_payload,
                        h1_img=h1_img if record["h1_img"] else daily_img,
                        h1_payload=h1_payload if "h1_payload" in dir() else {},
                        m5_img=m5_img if record["m5_img"] else daily_img,
                        m5_payload=m5_payload if "m5_payload" in dir() else {},
                    )
                    record["daily_bias"] = (pipeline.get("stage1_daily") or {}).get("daily_bias", "")
                    record["h1_trend"]   = (pipeline.get("stage2_h1")    or {}).get("h1_trend", "")
                    record["m5_action"]  = (pipeline.get("stage3_m5")    or {}).get("action", "HOLD")
                    record["confidence"] = (pipeline.get("stage3_m5")    or {}).get("confidence_score", "")
                    print(f"   🤖 Bias={record['daily_bias']} | H1={record['h1_trend']} | Action={record['m5_action']}")
                except Exception as e:
                    print(f"   ❌ AI pipeline lỗi: {e}")

            # ── Kiểm tra thực tế sau 24H ──────────
            future_idx = min(current_idx + 24, len(self.df_h1_full) - 1)
            future_df  = self.df_h1_full.iloc[current_idx + 1: future_idx + 1]
            if not future_df.empty:
                record["actual_next_24h_high"]  = float(future_df['High'].max())
                record["actual_next_24h_low"]   = float(future_df['Low'].min())
                record["actual_next_24h_close"] = float(future_df['Close'].iloc[-1])
                current_close = daily_payload['market_context']['current_price']
                record["actual_move_pct"] = round(
                    (record["actual_next_24h_close"] - current_close) / current_close * 100, 3
                )

            self.results.append(record)

        # ── Ghi CSV kết quả ──────────────────────
        self._save_results()
        self._print_summary()

    # ──────────────────────────────────────────────
    # LƯU & THỐNG KÊ
    # ──────────────────────────────────────────────
    def _save_results(self):
        rows = []
        for r in self.results:
            row = {k: v for k, v in r.items() if k != "daily_payload"}
            rows.append(row)

        df = pd.DataFrame(rows)
        df.to_csv(self.log_path, index=False, encoding="utf-8-sig")
        print(f"\n💾 Kết quả backtest → {self.log_path}")

    def _print_summary(self):
        print("\n" + "═"*60)
        print("  TỔNG KẾT BACKTEST ICT V2")
        print("═"*60)
        print(f"  Tổng bước phân tích : {len(self.results)}")

        if not self.call_ai:
            print("  (Chưa gọi AI – chỉ tạo chart)")
            return

        actions = [r.get("m5_action", "") for r in self.results]
        buys    = actions.count("BUY")
        sells   = actions.count("SELL")
        holds   = actions.count("HOLD") + actions.count("")

        print(f"  BUY  : {buys}")
        print(f"  SELL : {sells}")
        print(f"  HOLD : {holds}")

        # Accuracy thô: Daily Bias vs actual next-24h move
        correct = 0
        evaluated = 0
        for r in self.results:
            bias = r.get("daily_bias", "")
            move = r.get("actual_move_pct")
            if bias and move is not None:
                evaluated += 1
                if (bias == "BULLISH" and move > 0) or (bias == "BEARISH" and move < 0):
                    correct += 1

        if evaluated > 0:
            acc = correct / evaluated * 100
            print(f"\n  Daily Bias Accuracy (next-24h): {correct}/{evaluated} = {acc:.1f}%")
        print("═"*60)


# ══════════════════════════════════════════════════════════════════
# ENTRY POINT
# ══════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ICT V2 Backtester")
    parser.add_argument("--csv",   default=config.BACKTEST_CSV_PATH, help="Đường dẫn CSV H1")
    parser.add_argument("--start", type=int, default=config.BACKTEST_START_IDX)
    parser.add_argument("--end",   type=int, default=None)
    parser.add_argument("--step",  type=int, default=4,    help="Bước nhảy nến H1 (mặc định 4 = 4H)")
    parser.add_argument("--no-ai", action="store_true",    help="Chỉ tạo chart, không gọi AI")
    args = parser.parse_args()

    bt = Backtester(
        csv_path=args.csv,
        start_idx=args.start,
        end_idx=args.end,
        step=args.step,
        call_ai=not args.no_ai,
    )
    bt.run()
