import os
import logging
import asyncio
import discord

logging.basicConfig(level=logging.INFO)
SERVICE_MODE = os.getenv("SERVICE_MODE", "bot")  # 'bot' or 'selfbot'

if SERVICE_MODE == "selfbot":
    from src.discord_selfbot import client as selfbot_client
    client = selfbot_client
else:
    from src.discord_bot import bot as discord_bot
    client = discord_bot

async def main():
    token_env = "BOT_TOKEN" if SERVICE_MODE == "bot" else "STREAMING_BOT_TOKEN"
    token = os.getenv(token_env)
    if not token:
        logging.error(f"{token_env} not set")
        return
    try:
        await client.start(token)
    except Exception as e:
        logging.exception("Error running client:")
    finally:
        await client.close()

if __name__ == "__main__":
    asyncio.run(main())
