import os
import logging
import asyncio
import signal
from typing import NoReturn, Optional
import discord
from discord.ext import commands
from dependency_injector.wiring import inject, Provide
from src.core.di_container import Container
from src.core.redis_manager import RedisManager
from src.utils.rate_limiter import RateLimiter
from src.core.config import Settings
from src.metrics import METRICS

logging.basicConfig(level=logging.INFO)
SERVICE_MODE = os.getenv("SERVICE_MODE", "bot")  # 'bot' or 'selfbot'

if SERVICE_MODE == "selfbot":
    from src.discord_selfbot import SelfBot  # Import the class
    ClientClass = SelfBot
else:
    from src.bot.discord_bot import MediaBot as MediaBot  # Import the class
    ClientClass = MediaBot

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

# Enhanced voice playback using robust session management and error handling.
async def initiate_voice_playback(channel: discord.VoiceChannel, media: str):
    vc = None
    try:
        METRICS.increment_active_streams()  # Increment active streams
        vc = await channel.connect()
        process = await asyncio.create_subprocess_exec(
            "ffmpeg", "-i", media, "-f", "s16le", "-ar", "48000", "-ac", "2", "pipe:1",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )

        # Check if ffmpeg started successfully
        if process.returncode is not None:
            logging.error(f"FFmpeg failed to start with return code: {process.returncode}")
            # await channel.send("❌ FFmpeg failed to start.") # Removed because channel is a discord.VoiceChannel
            return

        while True:
            data = await process.stdout.read(4096)
            if not data:
                break  # no more data, exit loop
            try:
                await vc.send_audio_packet(data)
            except Exception as e:
                logger.error(f"Failed to send audio packet: {e}", exc_info=True)
                break
        await process.wait()
        logging.info("Playback finished.")
    except asyncio.CancelledError:
        logger.info("Playback cancelled.")
    except Exception as e:
        logging.exception("Voice playback error")
    finally:
        METRICS.decrement_active_streams()  # Decrement active streams
        if vc and vc.is_connected():
            await vc.disconnect()

@inject
async def run_discord_client(
    client: commands.Bot,  # Use commands.Bot as the base class
    token: str,
    settings: Settings = Provide[Container.settings]
) -> None:
    try:
        await client.start(token)
    except GracefulExit as e:
        logging.info(f"Application exited gracefully on {e.signame}")
        return
    except discord.LoginFailure as e:
        logging.error("Discord login failure: Ensure your token is valid.", exc_info=True)
        return
    except Exception as e:
        logging.exception("Error running client:")
    finally:
        await client.close()

async def main() -> NoReturn:
    token_env = "BOT_TOKEN" if SERVICE_MODE == "bot" else "DISCORD_SELFBOT_TOKEN"
    token = os.getenv(token_env)
    if not token:
        logging.error(f"{token_env} not set")
        return
    loop = asyncio.get_event_loop()
    
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, lambda s=sig: asyncio.create_task(shutdown(s, loop)))
    
    container = Container()
    container.config.from_dict(os.environ)  # Use environment variables directly
    container.wire(modules=[__name__])

    # Resolve the client using the container
    client: commands.Bot = container.client()

    try:
        await run_discord_client(client, token)
    except GracefulExit as e:
        logging.info(f"Application exited gracefully on {e.signame}")
        return
    except Exception as e:
        logging.exception("Error running client:")
    finally:
        await client.close()

if __name__ == "__main__":
    settings = Settings()
    asyncio.run(main())
