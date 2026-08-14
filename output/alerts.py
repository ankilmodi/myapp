"""
alerts.py
=========
Push notifications for Best-Buy signals via Telegram.
"""

import requests
from loguru import logger


class TelegramAlert:
    """Send buy signal alerts to Telegram."""

    def __init__(self, bot_token: str, chat_id: str):
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.base_url = f"https://api.telegram.org/bot{bot_token}"

    def send(self, message: str) -> bool:
        """Send a message to Telegram chat."""
        try:
            url = f"{self.base_url}/sendMessage"
            payload = {
                "chat_id": self.chat_id,
                "text": message,
                "parse_mode": "HTML",
            }
            r = requests.post(url, json=payload, timeout=10)
            if r.status_code == 200:
                logger.info("Telegram alert sent.")
                return True
            else:
                logger.warning(f"Telegram error: {r.text}")
                return False
        except Exception as e:
            logger.error(f"Telegram send failed: {e}")
            return False

    def send_top_picks(self, top_picks: list, timestamp: str = ""):
        """Format and send top buy picks."""
        if not top_picks:
            return
        msg = f"<b>🏆 NSE F&O Best Buy Signals</b>\n"
        if timestamp:
            msg += f"<i>{timestamp}</i>\n"
        msg += "─────────────────────\n"
        for i, pick in enumerate(top_picks[:10], 1):
            emoji = "🔥" if pick["score"] >= 80 else "✅"
            msg += (
                f"{i}. {emoji} <b>{pick['symbol']}</b> — "
                f"Score: <b>{pick['score']:.1f}</b> | "
                f"LTP: ₹{pick['ltp']:.2f} | RSI: {pick['rsi']:.1f}\n"
                f"   Verdict: <b>{pick.get('action_verdict', 'HOLD')}</b> | SMC: {pick.get('smc_signal', 'N/A')}\n"
                f"   SL: <b>₹{pick.get('stop_loss', 0):.2f}</b> | T1: <b>₹{pick.get('target_1', 0):.2f}</b> | T2: <b>₹{pick.get('target_2', 0):.2f}</b>\n"
            )
        msg += "\n<i>⚠️ Not financial advice. Do your own research.</i>"
        self.send(msg)
