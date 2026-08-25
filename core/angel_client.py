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
import os
import sys
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




class AngelClient:
    """
    Manages Angel One SmartAPI session - LIVE MODE ONLY.

    Parameters
    ----------
    api_key     : str  – Your Angel One API key
    client_id   : str  – Your Angel One login ID
    password    : str  – Your login password
    totp_secret : str  – TOTP secret (from developer settings)
    """
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
        self.demo_mode = demo_mode

        self.obj: Optional[SmartConnect] = None
        self.auth_token: str = ""
        self.refresh_token: str = ""
        self.feed_token: str = ""
        self.session_valid: bool = False
        self.last_error: str = ""

    # ─────────────────────────────────────────────
    # Login / Session
    # ─────────────────────────────────────────────
    def login(self) -> bool:
        """
        Authenticate with Angel One API. Returns True on success.
        
        If demo_mode=True: Uses mock client with mock data.
        If demo_mode=False: Uses real authentication with TOTP and live API.
        """
        try:
            # ★ DEMO MODE: Full mock (no real API calls) ★
            if self.demo_mode:
                if not SMARTAPI_AVAILABLE:
                    self.obj = MockSmartConnect(self.api_key)
                else:
                    self.obj = MockSmartConnect(self.api_key)
                    logger.info("🎮 DEMO MODE: Using mock data (no real API calls)")
                
                # Set mock tokens
                self.auth_token = "demo_jwt_token"
                self.refresh_token = "demo_refresh_token"
                self.feed_token = "demo_feed_token"
                self.session_valid = True
                self.last_error = ""
                
                logger.success(f"✅ Demo login successful [MOCK DATA MODE]")
                return True
            
            # ★ LIVE MODE: Full authentication with TOTP and real API ★
            if not SMARTAPI_AVAILABLE:
                logger.error("SmartAPI library not available. Install with: pip install smartapi-python")
                return False
            
            self.obj = SmartConnect(api_key=self.api_key)
            
            # Generate TOTP if secret is provided
            if self.totp_secret and self.totp_secret.strip() and "YOUR_TOTP_SECRET" not in self.totp_secret:
                totp = pyotp.TOTP(self.totp_secret).now()
                logger.info(f"🔐 Generated TOTP from secret: {totp}")
            else:
                # In cloud/non-interactive deployments, never block on input()
                is_interactive = sys.stdin.isatty() and not os.environ.get("PORT")
                if is_interactive:
                    logger.warning("🔑 TOTP secret not configured. Requesting manual TOTP entry...")
                    print("\n" + "=" * 60)
                    print(f"👉 Enter the 6-digit TOTP code for account {self.client_id}")
                    print("   (Check Google Authenticator or your AngelOne app)")
                    print("=" * 60)
                    totp = input("Enter 6-digit TOTP: ").strip()
                    while not (totp.isdigit() and len(totp) == 6):
                        logger.error("Invalid TOTP format. It must be exactly 6 digits.")
                        totp = input("Enter 6-digit TOTP: ").strip()
                else:
                    logger.error(
                        "⚠️  TOTP secret not set and running in non-interactive (cloud) mode. "
                        "Cannot proceed with authentication. Use --demo flag or set TOTP secret."
                    )
                    return False

            # Attempt login
            logger.info(f"🔐 Attempting login for {self.client_id}...")
            data = self.obj.generateSession(self.client_id, self.password, totp)

            if data["status"]:
                self.auth_token = data["data"]["jwtToken"]
                self.refresh_token = data["data"]["refreshToken"]
                self.feed_token = data["data"]["feedToken"]
                self.session_valid = True
                self.last_error = ""
                logger.success(f"✅ Logged in as {self.client_id} [LIVE MODE - AUTHENTICATED]")
                return True
            else:
                self.last_error = f"{data.get('message', 'Login failed')} (Code: {data.get('errorcode', '')})"
                logger.error(f"❌ Login failed: {data}")
                return False

        except Exception as e:
            self.last_error = str(e)
            logger.error(f"❌ Login exception: {e}")
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
        if self.demo_mode:
            # Return mock profile for demo mode
            return {
                "status": True,
                "data": {
                    "name": f"Mock User ({self.client_id})",
                    "clientcode": self.client_id,
                    "email": "mock@example.com"
                }
            }
        
        self.ensure_session()
        try:
            return self.obj.getProfile(self.refresh_token)
        except Exception as e:
            logger.error(f"Profile fetch error: {e}")
            return {}
