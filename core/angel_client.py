"""
angel_client.py
===============
Angel One SmartAPI Authentication & Session Management.

Features:
  - Login with TOTP-based 2FA
  - Auto token refresh
  - WebSocket connection manager
  - Demo/mock mode support

Usage:
    from core.angel_client import AngelClient
    client = AngelClient(api_key, client_id, password, totp_secret)
    client.login()
"""

import logging
import time
from datetime import datetime, timedelta
from typing import Optional

import pyotp
from loguru import logger

# ── Conditional import: works in real mode; mock in demo mode ──────────────
try:
    from SmartApi import SmartConnect
    SMARTAPI_AVAILABLE = True
except ImportError:
    SMARTAPI_AVAILABLE = False
    logger.warning("smartapi-python not installed. Running in demo mode.")


class MockSmartConnect:
    """Mock SmartConnect for demo/testing without real credentials."""

    def __init__(self, api_key: str):
        self.api_key = api_key

    def generateSession(self, client_id: str, password: str, totp: str) -> dict:
        logger.info("[DEMO] Mock login successful.")
        return {
            "status": True,
            "data": {
                "jwtToken": "demo_jwt_token",
                "refreshToken": "demo_refresh_token",
                "feedToken": "demo_feed_token",
            }
        }

    def getProfile(self, refresh_token: str) -> dict:
        return {"status": True, "data": {"name": "Demo User", "clientcode": "DEMO001"}}

    def ltpData(self, exchange: str, tradingsymbol: str, symboltoken: str) -> dict:
        """Return mock LTP data."""
        import random
        price = round(random.uniform(100, 5000), 2)
        return {
            "status": True,
            "data": {
                "tradingsymbol": tradingsymbol,
                "symboltoken": symboltoken,
                "open": price * 0.99,
                "high": price * 1.02,
                "low": price * 0.97,
                "close": price * 1.001,
                "ltp": price,
                "totaltradedvolume": random.randint(100000, 5000000),
            }
        }

    def getCandleData(self, historyParam: dict) -> dict:
        """Return mock historical candle data."""
        import random
        candles = []
        base_price = random.uniform(100, 3000)
        now = datetime.now()
        for i in range(100, 0, -1):
            dt = now - timedelta(days=i)
            o = base_price * random.uniform(0.98, 1.02)
            h = o * random.uniform(1.0, 1.05)
            l = o * random.uniform(0.95, 1.0)
            c = random.uniform(l, h)
            v = random.randint(50000, 2000000)
            base_price = c
            candles.append([dt.strftime("%Y-%m-%dT%H:%M:%S+05:30"), o, h, l, c, v])
        return {"status": True, "data": candles}

    def terminateSession(self, client_id: str):
        logger.info("[DEMO] Mock session terminated.")


class AngelClient:
    """
    Manages Angel One SmartAPI session.

    Parameters
    ----------
    api_key     : str  – Your Angel One API key
    client_id   : str  – Your Angel One login ID
    password    : str  – Your login password
    totp_secret : str  – TOTP secret (from developer settings)
    demo_mode   : bool – Use mock data instead of live API
    """

    def __init__(
        self,
        api_key: str,
        client_id: str,
        password: str,
        totp_secret: str,
        demo_mode: bool = False,
    ):
        self.api_key = api_key
        self.client_id = client_id
        self.password = password
        self.totp_secret = totp_secret
        self.demo_mode = demo_mode or not SMARTAPI_AVAILABLE

        self.obj: Optional[SmartConnect] = None
        self.auth_token: str = ""
        self.refresh_token: str = ""
        self.feed_token: str = ""
        self.session_valid: bool = False

    # ─────────────────────────────────────────────
    # Login / Session
    # ─────────────────────────────────────────────
    def login(self) -> bool:
        """Authenticate with Angel One API. Returns True on success."""
        try:
            if self.demo_mode:
                self.obj = MockSmartConnect(self.api_key)
                totp = "000000"   # dummy TOTP for mock
            else:
                self.obj = SmartConnect(api_key=self.api_key)
                if self.totp_secret and self.totp_secret.strip() and "YOUR_TOTP_SECRET" not in self.totp_secret:
                    totp = pyotp.TOTP(self.totp_secret).now()
                else:
                    logger.warning("🔑 TOTP secret is not configured or empty. Requesting manual TOTP entry...")
                    print("\n" + "=" * 60)
                    print(f"👉 Enter the 6-digit TOTP code for account {self.client_id}")
                    print("   (Check Google Authenticator or your AngelOne app)")
                    print("=" * 60)
                    totp = input("Enter 6-digit TOTP: ").strip()
                    while not (totp.isdigit() and len(totp) == 6):
                        logger.error("Invalid TOTP format. It must be exactly 6 digits.")
                        totp = input("Enter 6-digit TOTP: ").strip()

            data = self.obj.generateSession(self.client_id, self.password, totp)

            if data["status"]:
                self.auth_token = data["data"]["jwtToken"]
                self.refresh_token = data["data"]["refreshToken"]
                self.feed_token = data["data"]["feedToken"]
                self.session_valid = True
                logger.success(
                    f"✅ Logged in as {self.client_id} "
                    f"{'[DEMO]' if self.demo_mode else '[LIVE]'}"
                )
                return True
            else:
                logger.error(f"Login failed: {data}")
                return False

        except Exception as e:
            logger.error(f"Login exception: {e}")
            return False

    def logout(self):
        """Gracefully terminate session."""
        if self.obj and self.session_valid:
            try:
                self.obj.terminateSession(self.client_id)
                self.session_valid = False
                logger.info("Session terminated.")
            except Exception as e:
                logger.warning(f"Logout error: {e}")

    def ensure_session(self):
        """Re-login if session has expired."""
        if not self.session_valid:
            logger.info("Session expired, re-logging in...")
            self.login()

    # ─────────────────────────────────────────────
    # Data Access Proxies
    # ─────────────────────────────────────────────
    def get_ltp(self, exchange: str, symbol: str, token: str) -> dict:
        """Fetch Last Traded Price."""
        self.ensure_session()
        try:
            return self.obj.ltpData(exchange, symbol, token)
        except Exception as e:
            logger.warning(f"LTP error for {symbol}: {e}")
            return {}

    def get_candles(
        self,
        exchange: str,
        symbol_token: str,
        interval: str,
        from_date: str,
        to_date: str,
    ) -> list:
        """
        Fetch OHLCV candle data.

        interval: ONE_MINUTE | FIVE_MINUTE | FIFTEEN_MINUTE | ONE_HOUR | ONE_DAY
        from_date / to_date: 'YYYY-MM-DD HH:MM'
        """
        self.ensure_session()
        try:
            param = {
                "exchange": exchange,
                "symboltoken": symbol_token,
                "interval": interval,
                "fromdate": from_date,
                "todate": to_date,
            }
            response = self.obj.getCandleData(param)
            if response.get("status"):
                return response["data"]
            return []
        except Exception as e:
            logger.warning(f"Candle fetch error for {symbol_token}: {e}")
            return []

    def get_profile(self) -> dict:
        """Fetch account profile information."""
        self.ensure_session()
        try:
            return self.obj.getProfile(self.refresh_token)
        except Exception as e:
            logger.error(f"Profile fetch error: {e}")
            return {}
