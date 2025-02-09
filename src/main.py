import os
import logging
import asyncio
import signal
from typing import NoReturn
import discord

logging.basicConfig(level=logging.INFO)
SERVICE_MODE = os.getenv("SERVICE_MODE", "bot")  # 'bot' or 'selfbot'

if SERVICE_MODE == "selfbot":
    from src.discord_selfbot import client as selfbot_client
    client = selfbot_client
else:
    from src.discord_bot import bot as discord_bot
    client = discord_bot

class GracefulExit(SystemExit):
    """Exception raised for graceful application shutdown."""
    def __init__(self, signame: str) -> None:
        super().__init__()
        self.signame = signame

async def shutdown(signal: signal.Signals, loop: asyncio.AbstractEventLoop) -> None:
    """Handle application shutdown gracefully."""
    logging.info(f"Received exit signal {signal.name}...")
    tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
    
    for task in tasks:
        task.cancel()
    
    logging.info(f"Cancelling {len(tasks)} tasks")
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    for result in results:
        if isinstance(result, Exception) and not isinstance(result, asyncio.CancelledError):
            logging.exception("Unhandled exception during shutdown:", exc_info=result)
    
    loop.stop()
    raise GracefulExit(signal.name)

async def main() -> NoReturn:
    token_env = "BOT_TOKEN" if SERVICE_MODE == "bot" else "STREAMING_BOT_TOKEN"
    token = os.getenv(token_env)
    if not token:
        logging.error(f"{token_env} not set")
        return
    loop = asyncio.get_event_loop()
    
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, lambda s=sig: asyncio.create_task(shutdown(s, loop)))
    
    try:
        await client.start(token)
    except GracefulExit as e:
        logging.info(f"Application exited gracefully on {e.signame}")
        return
    except Exception as e:
        logging.exception("Error running client:")
    finally:
        await client.close()

if __name__ == "__main__":
    asyncio.run(main())
