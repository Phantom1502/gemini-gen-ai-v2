"""
main.py — ICT Auto Trading Bot V3
===================================
Cách dùng:
    python main.py            # Live trading
    python main.py --dry-run  # Kiểm tra pipeline, không đặt lệnh
"""

import argparse
import sys
import os
import json

sys.path.insert(0, os.path.dirname(__file__))

import MetaTrader5 as mt5
import config

from bot.broker.mt5        import MT5Util
from bot.ai.agent          import ICTAIAgent
from bot.core.pipeline     import ICTPipeline
from bot.core.trader       import Trader


def run_live() -> None:
    print("═" * 60)
    print("  ICT AUTO TRADING BOT V3 — LIVE")
    print(f"  Symbol   : {config.MT5_SYMBOL}")
    print(f"  Risk     : {config.RISK_PERCENT}% equity")
    print(f"  AI Model : {config.GEMINI_MODEL}")
    print(f"  BE Buffer: {config.BE_BUFFER_POINTS} pts | Trailing: {config.TRAILING_ENABLED}")
    print("═" * 60 + "\n")
    Trader().run(timeframe=mt5.TIMEFRAME_M5)


def run_dry_run() -> None:
    import datetime
    print("═" * 60)
    print("  DRY-RUN — Không đặt lệnh thật")
    print("═" * 60 + "\n")

    MT5Util.init(
        config.MT5_USERNAME, config.MT5_PASSWORD,
        config.MT5_SERVER,   config.MT5_SYMBOL,
    )
    agent    = ICTAIAgent(config.GEMINI_API_KEY, config.GEMINI_MODEL)
    pipeline = ICTPipeline(config.MT5_SYMBOL, agent)
    result   = pipeline.run(datetime.datetime.utcnow())

    print("\n" + "═" * 60)
    print(f"  Final action : {result['final_action']}")
    print(f"  Pipeline OK  : {result['pipeline_ok']}")
    if result.get("stage1_daily"):
        d = result["stage1_daily"]
        dol = d.get("draw_on_liquidity") or {}
        print(f"  Daily Bias   : {d.get('bias')} ({d.get('confidence')})")
        print(f"  DOL          : {dol.get('label')} @ {dol.get('price')}")
    if result.get("stage2_h1"):
        h = result["stage2_h1"]
        ez = h.get("entry_zone") or {}
        print(f"  H1 Direction : {h.get('direction')} ({h.get('confidence')})")
        print(f"  H1 Zone      : {ez.get('zone_type')} [{ez.get('price_bot')}–{ez.get('price_top')}]")
    if result.get("stage3_m5"):
        m = result["stage3_m5"]
        print(f"  M5 Action    : {m.get('action')} ({m.get('confidence')})")
        print(f"  M5 Trigger   : {m.get('entry_trigger')}")
    print("═" * 60)
    MT5Util.disconnect()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ICT Bot V3")
    parser.add_argument("--dry-run", action="store_true",
                        help="Chạy pipeline 1 lần, không đặt lệnh")
    args = parser.parse_args()

    if args.dry_run:
        run_dry_run()
    else:
        run_live()
