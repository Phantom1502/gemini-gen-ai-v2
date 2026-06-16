"""
main.py
=======
Entry point chính của ICT Auto Trading Bot V2.

Cách dùng:
    python main.py            # Chạy bot live với config.py
    python main.py --dry-run  # Chạy 1 vòng pipeline, không vào lệnh thật
"""

import argparse
import sys
import os

# Thêm src vào path để import module
sys.path.insert(0, os.path.dirname(__file__))

import src.config_real as config_real
from trader import Trader
import MetaTrader5 as mt5


def run_dry_run():
    """
    Chạy 1 vòng pipeline hoàn chỉnh (Daily→H1→M5) mà không vào lệnh thật.
    Dùng để test cấu hình, API key, và kiểm tra output chart.
    """
    print("═"*60)
    print("  DRY-RUN MODE – Không vào lệnh thật")
    print("═"*60)

    from utils.mt5util           import MT5Util
    from utils.daily_bias_util   import DailyBiasUtil
    from utils.h1_structure_util import H1StructureUtil
    from utils.m5_entry_util     import M5EntryUtil
    from utils.ict_ai_agent      import ICTAIAgent
    import json

    # Kết nối MT5
    MT5Util.init_mt5(
        config_real.MT5_USERNAME,
        config_real.MT5_PASSWORD,
        config_real.MT5_SERVER,
        config_real.MT5_SYMBOL
    )

    # Lấy dữ liệu
    df_daily, df_h1, df_m5 = MT5Util.get_multi_tf_data(
        config_real.MT5_SYMBOL,
        h1_count=config_real.H1_FETCH_COUNT,
        h1_window=config_real.H1_CHART_WINDOW,
        m5_window=config_real.M5_CHART_WINDOW,
    )

    os.makedirs(config_real.CHART_FOLDER, exist_ok=True)

    # Stage 1: Daily
    print("\n[Stage 1] Daily Bias Analysis...")
    daily_img, daily_payload = DailyBiasUtil.generate_daily_chart(
        df_daily, folder=config_real.CHART_FOLDER
    )
    print(f"   Chart: {daily_img}")
    print(f"   Payload: {json.dumps(daily_payload, indent=4, ensure_ascii=False)}")

    # Gọi AI Stage 1
    agent = ICTAIAgent(api_key=config_real.GEMINI_API_KEY, model_name=config_real.GEMINI_MODEL)
    daily_result = agent.analyze_daily(daily_img, daily_payload)
    if daily_result:
        print(f"\n   ✅ Daily Bias = {daily_result.get('daily_bias')}")
        print(f"   DOL          = {daily_result.get('draw_on_liquidity')}")
        print(f"   Confidence   = {daily_result.get('confidence_score')}")
        ltf = daily_result.get('ltf_execution_context', {})
        print(f"   LTF Scenario = {ltf.get('primary_scenario', '')}")
        print(f"   Invalidation = {ltf.get('invalidation_level', '')}")
    else:
        print("   ❌ AI Stage 1 thất bại.")
        MT5Util.disconnect()
        return

    daily_bias = daily_result.get("daily_bias", "NEUTRAL")

    # Stage 2: H1
    print("\n[Stage 2] H1 Structure Analysis...")
    h1_img, h1_payload = H1StructureUtil.generate_h1_chart(
        df_h1,
        daily_bias=daily_bias,
        daily_payload=daily_payload,
        folder=config_real.CHART_FOLDER,
    )
    h1_payload['pdh'] = daily_payload['yesterday_anchors']['PDH']
    h1_payload['pdl'] = daily_payload['yesterday_anchors']['PDL']
    print(f"   Chart: {h1_img}")

    h1_result = agent.analyze_h1(h1_img, daily_bias, h1_payload)
    if h1_result:
        print(f"\n   ✅ H1 Trend    = {h1_result.get('h1_trend')}")
        print(f"   Key POI       = {h1_result.get('key_poi')}")
        print(f"   H1 Scenario   = {h1_result.get('h1_scenario')}")
        print(f"   Confidence    = {h1_result.get('confidence_score')}")
    else:
        print("   ❌ AI Stage 2 thất bại.")
        MT5Util.disconnect()
        return

    # Stage 3: M5
    print("\n[Stage 3] M5 Entry Scan...")
    m5_img, m5_payload = M5EntryUtil.generate_m5_chart(
        df_m5,
        daily_bias=daily_bias,
        h1_payload=h1_payload,
        folder=config_real.CHART_FOLDER,
    )
    print(f"   Chart: {m5_img}")

    m5_result = agent.analyze_m5(m5_img, daily_bias, h1_result, m5_payload)
    if m5_result:
        print(f"\n   ✅ Action     = {m5_result.get('action')}")
        print(f"   Entry Zone  = {m5_result.get('entry_zone')}")
        print(f"   SL Ref      = {m5_result.get('sl_reference')}")
        print(f"   TP Ref      = {m5_result.get('tp_reference')}")
        print(f"   Reason      = {m5_result.get('geometry_reason')}")
        print(f"   Confidence  = {m5_result.get('confidence_score')}")
    else:
        print("   ❌ AI Stage 3 thất bại.")

    print("\n" + "═"*60)
    print("  DRY-RUN HOÀN THÀNH. Không có lệnh nào được đặt.")
    print("═"*60)

    MT5Util.disconnect()


def run_live():
    """Chạy bot live."""
    print("═"*60)
    print("  ICT AUTO TRADING BOT V2 – LIVE MODE")
    print(f"  Symbol      : {config_real.MT5_SYMBOL}")
    print(f"  Risk/Trade  : {config_real.RISK_PERCENT}% equity")
    print(f"  R:R         : 1:{config_real.RR_RATIO}")
    print(f"  Magic       : {config_real.MAGIC_NUMBER}")
    print(f"  AI Model    : {config_real.GEMINI_MODEL}")
    print(f"  Trailing SL : {'ON' if config_real.TRAILING_ENABLED else 'OFF'}")
    print("═"*60 + "\n")

    trader = Trader()
    trader.run(timeframe=mt5.TIMEFRAME_M5)


# ══════════════════════════════════════════════════════════════════
# ENTRY POINT
# ══════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="ICT Auto Trading Bot V2",
        formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Chạy 1 vòng pipeline đầy đủ mà không vào lệnh thật.\nDùng để test API key và kiểm tra chart output."
    )
    args = parser.parse_args()

    if args.dry_run:
        run_dry_run()
    else:
        run_live()
