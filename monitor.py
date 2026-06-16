#!/usr/bin/env python3
"""
Pump.fun Real-Time Token Monitor via WebSocket + 5-Minute Profit Check
- Detects new tokens in real-time via PumpPortal WebSocket
- Checks every 5 minutes if ₹100 investment has grown to ₹1000+
- ₹100 investment breakdown (tokens, 2x/5x/10x profit)
- Pump.fun buy link
"""

import asyncio
import aiohttp
import json
import logging
import time
from datetime import datetime
from typing import Dict, Optional, List
import websockets
from telegram import Bot

# ========== CONFIGURATION ==========
TELEGRAM_BOT_TOKEN = "8870427358:AAFeiXpIQ8JnYs8ZVZ_6Vbzvcj1GTjVwMKg"
TELEGRAM_CHAT_ID = "5964851833"

# Shift configuration - CHANGE THIS PER REPOSITORY
SHIFT_NAME = "Shift 1"
SHIFT_TIMING = "12 AM - 6 AM"

INVEST_AMOUNT_INR = 100
INR_PER_USD = 83.0
MIN_PROFIT_FOR_ALERT = 1000  # ₹1000+ profit wale tokens dikhao
CHECK_INTERVAL = 300  # 5 minutes
WS_URL = "wss://pumpportal.fun/api/data"

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Store token data
tracked_tokens = {}  # mint -> {'first_price': float, 'name': str, 'symbol': str, 'detected_at': float, 'alerted_5min': bool}

# ========== HELPER FUNCTIONS ==========
def usd_to_inr(usd: float) -> float:
    return usd * INR_PER_USD

def format_number(num: float) -> str:
    if num >= 1_000_000_000:
        return f"{num/1_000_000_000:.1f}B"
    if num >= 1_000_000:
        return f"{num/1_000_000:.1f}M"
    if num >= 1_000:
        return f"{num/1_000:.1f}K"
    return f"{num:.2f}"

def calculate_tokens(price_usd: float) -> float:
    if price_usd <= 0:
        return 0
    return (INVEST_AMOUNT_INR / INR_PER_USD) / price_usd

def calculate_profit(price_usd: float, multiplier: int) -> float:
    usd_amount = INVEST_AMOUNT_INR / INR_PER_USD
    return (usd_amount * multiplier) * INR_PER_USD

# ========== FETCH TOKEN PRICE ==========
async def fetch_token_price(mint: str) -> Optional[Dict]:
    """Fetch current price and details from DexScreener"""
    async with aiohttp.ClientSession() as session:
        url = f"https://api.dexscreener.com/latest/dex/tokens/{mint}"
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        try:
            async with session.get(url, timeout=10) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if data.get('pairs') and len(data['pairs']) > 0:
                        p = data['pairs'][0]
                        return {
                            'price_usd': float(p.get('priceUsd', 0)),
                            'liquidity_usd': float(p.get('liquidity', {}).get('usd', 0)),
                            'price_change_5m': float(p.get('priceChange', {}).get('m5', 0)),
                            'market_cap_usd': float(p.get('marketCap', 0)),
                            'volume_24h_usd': float(p.get('volume', {}).get('h24', 0)),
                        }
        except Exception as e:
            logger.error(f"Price fetch error for {mint}: {e}")
        return None

# ========== TELEGRAM ==========
async def send_telegram_message(text: str):
    bot = Bot(token=TELEGRAM_BOT_TOKEN)
    try:
        await bot.send_message(
            chat_id=TELEGRAM_CHAT_ID,
            text=text,
            parse_mode='Markdown',
            disable_web_page_preview=True
        )
        logger.info("Telegram message sent")
    except Exception as e:
        logger.error(f"Telegram error: {e}")

async def send_startup_message():
    await send_telegram_message(f"✅ {SHIFT_NAME} ({SHIFT_TIMING}): Bot started. Monitoring Pump.fun real-time...")

async def send_token_alert(mint: str, token_data: Dict, price_info: Dict, is_5min: bool = False):
    """Send detailed token alert with ₹100 breakdown"""
    current_price = price_info.get('price_usd', 0)
    if current_price <= 0:
        current_price = token_data.get('price', 0) or 0.000001

    name = token_data.get('name', 'Unknown')
    symbol = token_data.get('symbol', 'Unknown')
    market_cap = price_info.get('market_cap_usd', 0) or token_data.get('marketCap', 0)
    liquidity = price_info.get('liquidity_usd', 0) or token_data.get('liquidity', 0)
    price_change = price_info.get('price_change_5m', 0)
    
    tokens = calculate_tokens(current_price)
    profit_2x = calculate_profit(current_price, 2)
    profit_5x = calculate_profit(current_price, 5)
    profit_10x = calculate_profit(current_price, 10)
    
    # Calculate profit for ₹100 investment
    usd_amount = INVEST_AMOUNT_INR / INR_PER_USD
    current_value = (usd_amount / current_price) * current_price * INR_PER_USD if current_price > 0 else 0
    profit_inr = current_value - INVEST_AMOUNT_INR

    alert_type = "🔄 5-MINUTE UPDATE" if is_5min else "🚨 NEW TOKEN DETECTED!"

    msg = f"""
{alert_type}

*Token:* {name} (${symbol})
*Mint:* `{mint}`

📊 *Current Stats*
💰 Price: ₹{usd_to_inr(current_price):.8f} (${current_price:.8f})
📈 5m Change: {price_change:.1f}%
🏦 Market Cap: ₹{format_number(usd_to_inr(market_cap))}
💧 Liquidity: ₹{format_number(usd_to_inr(liquidity))}

💰 *₹{INVEST_AMOUNT_INR} INVESTMENT:*
• Tokens received: {tokens:,.0f}
• Value now: ₹{current_value:.2f}
• Profit: ₹{profit_inr:.2f}

🎯 *Targets (if price reaches):*
• 2x → ₹{profit_2x:.2f}
• 5x → ₹{profit_5x:.2f}
• 10x → ₹{profit_10x:.2f}

🔗 *Buy:* [Pump.fun](https://pump.fun/{mint})
📊 *Chart:* [DexScreener](https://dexscreener.com/solana/{mint})
"""
    await send_telegram_message(msg)
    logger.info(f"Alert sent for {symbol}")

# ========== 5-MINUTE CHECK ==========
async def check_5min_updates():
    """Every 5 minutes, check all tracked tokens for profit >= ₹1000"""
    while True:
        await asyncio.sleep(CHECK_INTERVAL)
        
        if not tracked_tokens:
            continue
            
        logger.info(f"[5-MIN CHECK] Checking {len(tracked_tokens)} tokens...")
        
        for mint, data in list(tracked_tokens.items()):
            try:
                price_info = await fetch_token_price(mint)
                if not price_info:
                    continue
                    
                current_price = price_info.get('price_usd', 0)
                if current_price <= 0:
                    continue
                    
                first_price = data.get('first_price', 0.000001)
                usd_amount = INVEST_AMOUNT_INR / INR_PER_USD
                current_value = (usd_amount / first_price) * current_price * INR_PER_USD if first_price > 0 else 0
                profit_inr = current_value - INVEST_AMOUNT_INR
                
                # If profit >= ₹1000, send alert
                if profit_inr >= MIN_PROFIT_FOR_ALERT:
                    token_data = {
                        'name': data.get('name', 'Unknown'),
                        'symbol': data.get('symbol', 'Unknown'),
                        'price': current_price,
                        'marketCap': price_info.get('market_cap_usd', 0),
                        'liquidity': price_info.get('liquidity_usd', 0)
                    }
                    await send_token_alert(mint, token_data, price_info, is_5min=True)
                    logger.info(f"[5-MIN] Profit alert sent for {data.get('symbol')}: ₹{profit_inr:.2f}")
                    
            except Exception as e:
                logger.error(f"5-min check error for {mint}: {e}")

# ========== WEBSOCKET LISTENER ==========
async def listen():
    """Main WebSocket connection with auto-reconnect"""
    await send_startup_message()
    
    while True:
        try:
            async with websockets.connect(WS_URL) as ws:
                logger.info("Connected to Pump Portal WebSocket")
                await ws.send(json.dumps({"method": "subscribeNewToken"}))
                logger.info("Subscribed to new token events")
                
                async for message in ws:
                    try:
                        data = json.loads(message)
                        if data.get('type') == 'newToken':
                            mint = data.get('mint')
                            if mint and mint not in tracked_tokens:
                                logger.info(f"New token detected: {data.get('symbol', 'Unknown')}")
                                
                                # Fetch initial price
                                price_info = await fetch_token_price(mint)
                                first_price = price_info.get('price_usd', 0) if price_info else 0.000001
                                
                                # Store token
                                tracked_tokens[mint] = {
                                    'first_price': first_price,
                                    'name': data.get('name', 'Unknown'),
                                    'symbol': data.get('symbol', 'Unknown'),
                                    'detected_at': time.time()
                                }
                                
                                # Send initial alert
                                if price_info:
                                    await send_token_alert(mint, data, price_info, is_5min=False)
                                else:
                                    await send_token_alert(mint, data, {}, is_5min=False)
                                
                    except json.JSONDecodeError:
                        logger.warning("Invalid JSON received")
                    except Exception as e:
                        logger.error(f"Message processing error: {e}")
                        
        except websockets.exceptions.ConnectionClosed:
            logger.warning("WebSocket closed. Reconnecting in 5s...")
            await asyncio.sleep(5)
        except Exception as e:
            logger.error(f"WebSocket error: {e}. Reconnecting in 10s...")
            await asyncio.sleep(10)

# ========== CLEANUP ==========
async def cleanup_old_tokens():
    """Remove tokens older than 2 hours to prevent memory bloat"""
    while True:
        await asyncio.sleep(3600)  # 1 hour
        now = time.time()
        to_remove = []
        for mint, data in tracked_tokens.items():
            if now - data.get('detected_at', 0) > 7200:  # 2 hours
                to_remove.append(mint)
        for mint in to_remove:
            del tracked_tokens[mint]
        if to_remove:
            logger.info(f"Cleaned up {len(to_remove)} old tokens")

# ========== MAIN ==========
async def main():
    logger.info(f"Starting {SHIFT_NAME} ({SHIFT_TIMING}) Bot...")
    
    # Start background tasks
    asyncio.create_task(check_5min_updates())
    asyncio.create_task(cleanup_old_tokens())
    
    await listen()

if __name__ == "__main__":
    asyncio.run(main())
