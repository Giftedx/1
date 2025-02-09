import os
import asyncio
import logging
import discord
from discord.ext import commands

logging.basicConfig(level=logging.INFO)

class SelfBot(commands.Bot):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    async def on_ready(self):
        logging.info(f"Selfbot logged in as {self.user}")

# Enhanced voice playback using robust session management and error handling.
async def initiate_voice_playback(channel: discord.VoiceChannel, media: str):
    vc = None
    try:
        vc = await channel.connect()
        
        # Create FFmpeg process
        process = await asyncio.create_subprocess_exec(
            "ffmpeg",
            "-i", media,
            "-f", "s16le",
            "-ar", "48000",
            "-ac", "2",
            "pipe:1",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )

        # Log FFmpeg stderr output
        async def log_stderr(process):
            while True:
                line = await process.stderr.readline()
                if not line:
                    break
                logging.info(f"FFmpeg: {line.decode().strip()}")

        asyncio.create_task(log_stderr(process))

        # Check if FFmpeg started successfully
        if process.returncode is not None:
            logging.error(f"FFmpeg failed to start with return code: {process.returncode}")
            await channel.send("❌ FFmpeg failed to start.")
            return

        # Stream audio data
        while True:
            data = await process.stdout.read(4096)
            if not data:
                break  # no more data, exit loop
            
            try:
                if vc.is_connected():
                    await vc.send_audio_packet(data)
                else:
                    logging.warning("Voice channel disconnected, stopping playback.")
                    break
            except Exception as e:
                logging.error(f"Failed to send audio packet: {e}", exc_info=True)
                break

        # Wait for FFmpeg to finish
        await process.wait()
        logging.info("Playback finished.")

    except asyncio.CancelledError:
        logging.info("Playback cancelled.")
        if process:
            process.terminate()
            await process.wait()
    except discord.ClientException as e:
        logging.error(f"Discord client exception: {e}", exc_info=True)
    except Exception as e:
        logging.exception("Voice playback error")
    finally:
        if vc and vc.is_connected():
            await vc.disconnect()

class MyCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command()
    async def play(self, ctx, channel: discord.VoiceChannel=None, *, media: str):
        """Plays media in a voice channel.

        Args:
            ctx: The command context.
            channel: The voice channel to play in (optional).
            media: The URL or path to the media file.
        """
        if channel is None:
            if ctx.author.voice and ctx.author.voice.channel:
                channel = ctx.author.voice.channel
            else:
                await ctx.send("You must be in a voice channel or specify one to use this command.")
                return

        await initiate_voice_playback(channel, media)

async def main():
    intents = discord.Intents.default()
    intents.message_content = True  # Specify intents
    intents.voice_states = True
    bot = SelfBot(command_prefix='!', self_bot=True, intents=intents)
    await bot.add_cog(MyCog(bot))  # Add the cog to the bot

    @bot.event
    async def on_message(message):
        # Only respond to DM commands to ensure selfbot safety
        if message.guild is not None:
            return

        await bot.process_commands(message)  # Process commands

    try:
        await bot.start(os.getenv("DISCORD_SELFBOT_TOKEN"))
    except discord.LoginFailure:
        logging.error("Improper token has been passed.")
    except Exception as e:
        logging.exception("Exception raised during bot.start")

if __name__ == "__main__":
    asyncio.run(main())
