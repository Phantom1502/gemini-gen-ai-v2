"""
bot/reporting/csv_logger.py
============================
CSVLogger — ghi log giao dịch hàng ngày ra file CSV.
Tách riêng khỏi Trader để dễ test và mở rộng.
"""

import os
import datetime
import pandas as pd
from typing import Dict


class CSVLogger:

    def __init__(self, log_folder: str):
        self.log_folder = log_folder
        os.makedirs(log_folder, exist_ok=True)

    def write(self, log_data: Dict) -> str:
        """Ghi một record vào CSV của ngày hôm nay. Trả về đường dẫn file."""
        today = datetime.datetime.now().strftime("%Y%m%d")
        path  = os.path.join(self.log_folder, f"trading_log_{today}.csv")

        if os.path.exists(path):
            try:
                df = pd.read_csv(path)
                df = pd.concat([df, pd.DataFrame([log_data])], ignore_index=True)
            except Exception:
                df = pd.DataFrame([log_data])
        else:
            df = pd.DataFrame([log_data])

        df.to_csv(path, index=False, encoding="utf-8-sig")
        print(f"📝 [LOG] → {path}")
        return path

    @staticmethod
    def build_record(
        action:   str,
        pipeline: Dict,
        symbol:   str,
        ticket,
        sl_pts:   float,
        risk_usd: float,
        lot:      float,
        tp_price,
        actual_rr,
        profit,
        result:   str,
    ) -> Dict:
        """Xây dựng dict log từ kết quả pipeline."""
        now     = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        daily_r = pipeline.get("stage1_daily") or {}
        h1_r    = pipeline.get("stage2_h1")    or {}
        m5_r    = pipeline.get("stage3_m5")    or {}
        dol     = (daily_r.get("draw_on_liquidity") or {})

        return {
            "Open_Timestamp":   now,
            "Close_Timestamp":  now if result == "HOLD" else "PENDING",
            "Symbol":           symbol,
            "Action":           action,
            "Daily_Trigger_H":  pipeline.get("trigger_hour", "—"),

            # DailyBiasContext
            "Daily_Bias":         daily_r.get("bias", ""),
            "Daily_Confidence":   daily_r.get("confidence", ""),
            "Daily_Market_State": daily_r.get("market_state", ""),
            "Daily_DOL":          f"{dol.get('label','')} @ {dol.get('price','')}",
            "Daily_HTF_Invalid":  daily_r.get("htf_invalidation", ""),
            "Daily_LTF_Guidance": daily_r.get("ltf_guidance", ""),

            # H1TradingContext
            "H1_Direction":      h1_r.get("direction", ""),
            "H1_Ready":          h1_r.get("ready_to_trade", ""),
            "H1_Summary":        h1_r.get("h1_summary", ""),
            "H1_Target":         h1_r.get("target", ""),
            "H1_Invalidation":   h1_r.get("invalidation", ""),
            "H1_Confidence":     h1_r.get("confidence", ""),

            # M5EntryResult
            "M5_Action":          m5_r.get("action", ""),
            "M5_Confidence":      m5_r.get("confidence", ""),
            "M5_Entry_Trigger":   m5_r.get("entry_trigger", ""),
            "M5_SL_Ref":          m5_r.get("sl_reference", ""),
            "M5_TP_Ref":          m5_r.get("tp_reference", ""),
            "M5_Geometry_Reason": m5_r.get("geometry_reason", ""),
            "M5_Hold_Reason":     m5_r.get("hold_reason", ""),

            # Lệnh
            "SL_Points":      sl_pts,
            "Risk_USD":       risk_usd,
            "Lot":            lot,
            "TP_Price":       tp_price,
            "Actual_RR":      actual_rr,
            "MT5_Ticket":     ticket,
            "Real_Profit_USD": profit,
            "Trade_Result":   result,

            # Charts
            "Daily_Chart": pipeline.get("daily_img", ""),
            "H1_Chart":    pipeline.get("h1_img", ""),
            "M5_Chart":    pipeline.get("m5_img", ""),
        }
