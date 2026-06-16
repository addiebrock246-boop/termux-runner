#!/usr/bin/env python3
"""
Pump.fun Real-Time Token Monitor via WebSocket
- Detects new tokens in real-time via PumpPortal WebSocket
- ₹100 investment breakdown (tokens, 2x/5x/10x profit)
- Pump.fun buy link
- Shift-wise startup message
"""

import asyncio
import aiohttp
import json
import logging
import time
from datetime import datetime
from typing import Dict, Optional
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
WS_URL = "wss://pumpportal.fun/api/data"

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Track tokens we've already alerted about
alerted_tokens = set()

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

# ========== FETCH TOKEN PRICE FROM DEXSCREENER ==========
async def fetch_token_price(mint: str) -> Optional[Dict]:
    """Fetch current price and details for a token from DexScreener"""
    async with aiohttp.ClientSession() as session:
        url = f"https://api.dexscreener.com/latest/dex/tokens/{mint}"
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
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
    """Send startup message for this shift"""
    await send_telegram_message(f"✅ {SHIFT_NAME} ({SHIFT_TIMING}): Bot started. Monitoring Pump.fun real-time...")

async def send_token_alert(mint: str, token_data: Dict, price_info: Dict):
    """Send detailed token alert with ₹100 breakdown"""
    current_price = price_info.get('price_usd', 0)
    if current_price <= 0:
        current_price = token_data.get('price', 0) or 0.000001

    tokens = calculate_tokens(current_price)
    profit_2x = calculate_profit(current_price, 2)
    profit_5x = calculate_profit(current_price, 5)
    profit_10x = calculate_profit(current_price, 10)

    name = token_data.get('name', 'Unknown')
    symbol = token_data.get('symbol', 'Unknown')
    market_cap = price_info.get('market_cap_usd', 0) or token_data.get('marketCap', 0)
    liquidity = price_info.get('liquidity_usd', 0) or token_data.get('liquidity', 0)
    price_change = price_info.get('price_change_5m', 0)

    msg = f"""
🚨 *NEW PUMP.FUN TOKEN DETECTED!*

*Token:* {name} (${symbol})
*Mint:* `{mint}`

📊 *Current Stats*
💰 Price: ₹{usd_to_inr(current_price):.8f} (${current_price:.8f})
📈 5m Change: {price_change:.1f}%
🏦 Market Cap: ₹{format_number(usd_to_inr(market_cap))}
💧 Liquidity: ₹{format_number(usd_to_inr(liquidity))}

💰 *₹{INVEST_AMOUNT_INR} INVESTMENT BREAKDOWN*
• Tokens received: {tokens:,.0f}

🎯 *Targets (if price reaches):*
• 2x → ₹{profit_2x:.2f}
• 5x → ₹{profit_5x:.2f}
• 10x → ₹{profit_10x:.2f}

🔗 *Buy:* [Pump.fun](https://pump.fun/{mint})
📊 *Chart:* [DexScreener](https://dexscreener.com/solana/{mint})
"""
    await send_telegram_message(msg)
    logger.info(f"Alert sent for {symbol}")

# ========== WEBSOCKET LISTENER ==========
async def listen():
    """Main WebSocket connection with auto-reconnect"""
    await send_startup_message()
    
    while True:
        try:
            async with websockets.connect(WS_URL) as ws:
                logger.info("Connected to Pump Portal WebSocket")
                
                # Subscribe to new token creation events
                await ws.send(json.dumps({"method": "subscribeNewToken"}))
                logger.info("Subscribed to new token events")
                
                async for message in ws:
                    try:
                        data = json.loads(message)
                        msg_type = data.get('type')
                        
                        if msg_type == 'newToken':
                            mint = data.get('mint')
                            if mint and mint not in alerted_tokens:
                                logger.info(f"New token detected: {data.get('symbol', 'Unknown')} ({mint})")
                                
                                # Fetch price info from DexScreener
                                price_info = await fetch_token_price(mint)
                                if price_info:
                                    await send_token_alert(mint, data, price_info)
                                else:
                                    # If DexScreener fails, send alert with basic info
                                    await send_token_alert(mint, data, {})
                                
                                alerted_tokens.add(mint)
                        
                        elif msg_type == 'trade':
                            # Optional: Track trades for price updates
                            pass
                            
                    except json.JSONDecodeError:
                        logger.warning("Invalid JSON received")
                    except Exception as e:
                        logger.error(f"Message processing error: {e}")
                        
        except websockets.exceptions.ConnectionClosed:
            logger.warning("WebSocket connection closed. Reconnecting in 5 seconds...")
            await asyncio.sleep(5)
        except Exception as e:
            logger.error(f"WebSocket error: {e}. Reconnecting in 10 seconds...")
            await asyncio.sleep(10)

# ========== MAIN ==========
async def main():
    logger.info(f"Starting {SHIFT_NAME} ({SHIFT_TIMING}) Bot...")
    await listen()

if __name__ == "__main__":
    asyncio.run(main())
