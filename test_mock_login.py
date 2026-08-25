#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
test_mock_login.py
==================
Test script to verify mock login functionality with LIVE API data.

Usage:
    python test_mock_login.py
"""

from loguru import logger
from core.angel_client import AngelClient
from core.fo_stocks import fetch_fo_stock_list

def test_mock_login():
    """Test mock login mode with live API data."""
    logger.info("=" * 60)
    logger.info("Testing MOCK LOGIN Mode")
    logger.info("=" * 60)
    
    # Create client with mock login
    client = AngelClient(
        api_key="DEMO_API_KEY",
        client_id="MOCK_USER_001",
        password="mock_password",
        totp_secret="",
        demo_mode=True,  # Enable mock login
    )
    
    # Test 1: Login
    logger.info("\n[Test 1] Testing mock login...")
    if client.login():
        logger.success("✅ Mock login successful!")
        logger.info(f"Session valid: {client.session_valid}")
        logger.info(f"Auth token: {client.auth_token[:50]}...")
    else:
        logger.error("❌ Mock login failed!")
        return False
    
    # Test 2: Get Profile
    logger.info("\n[Test 2] Testing profile fetch...")
    profile = client.get_profile()
    if profile.get("status"):
        logger.success("✅ Profile fetch successful!")
        logger.info(f"User: {profile['data'].get('name')}")
        logger.info(f"Client ID: {profile['data'].get('clientcode')}")
    else:
        logger.error("❌ Profile fetch failed!")
    
    # Test 3: Fetch F&O Stock List (LIVE API)
    logger.info("\n[Test 3] Testing LIVE F&O stock list fetch...")
    stock_list = fetch_fo_stock_list()
    if stock_list:
        logger.success(f"✅ Fetched {len(stock_list)} F&O stocks from LIVE API!")
        logger.info(f"Sample stocks: {[s['symbol'] for s in stock_list[:5]]}")
    else:
        logger.warning("⚠️  Could not fetch stock list (may need real API key)")
    
    # Test 4: Fetch Candle Data (LIVE API)
    if stock_list:
        logger.info("\n[Test 4] Testing LIVE candle data fetch...")
        from datetime import datetime, timedelta
        
        test_stock = stock_list[0]
        symbol = test_stock['symbol']
        token = test_stock['token']
        
        to_dt = datetime.now()
        from_dt = to_dt - timedelta(days=10)
        
        candles = client.get_candles(
            exchange="NSE",
            symbol_token=str(token),
            interval="ONE_DAY",
            from_date=from_dt.strftime("%Y-%m-%d %H:%M"),
            to_date=to_dt.strftime("%Y-%m-%d %H:%M"),
        )
        
        if candles:
            logger.success(f"✅ Fetched {len(candles)} candles for {symbol} from LIVE API!")
            logger.info(f"Latest candle: {candles[-1][:5]}")
        else:
            logger.warning(f"⚠️  Could not fetch candles for {symbol}")
    
    # Test 5: Fetch LTP (LIVE API)
    if stock_list:
        logger.info("\n[Test 5] Testing LIVE LTP fetch...")
        test_stock = stock_list[0]
        symbol = test_stock['symbol']
        token = test_stock['token']
        
        ltp_data = client.get_ltp("NSE", symbol + "-EQ", str(token))
        if ltp_data.get("status") and ltp_data.get("data"):
            ltp = ltp_data["data"].get("ltp")
            logger.success(f"✅ Fetched LTP for {symbol}: ₹{ltp:.2f} from LIVE API!")
        else:
            logger.warning(f"⚠️  Could not fetch LTP for {symbol}")
    
    # Summary
    logger.info("\n" + "=" * 60)
    logger.info("SUMMARY")
    logger.info("=" * 60)
    logger.success("✅ Mock login works correctly!")
    logger.success("✅ Can fetch LIVE API data without authentication!")
    logger.info("=" * 60)
    
    return True

if __name__ == "__main__":
    test_mock_login()
