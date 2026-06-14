#!/bin/bash
echo "🚀 Installing Bot Dependencies..."

# Update and Upgrade
pkg update -y && pkg upgrade -y

# Install Python and git
pkg install python git -y

# Install Python packages
pip install aiohttp websockets python-telegram-bot

# Run the bot
echo "✅ Installation Complete. Starting Bot..."
python pump_monitor.py
