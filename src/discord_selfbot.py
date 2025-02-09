import os
import asyncio
import logging
import discord
from discord.ext import commands
from src.main import initiate_voice_playback

logging.basicConfig(level=logging.INFO)

class SelfBot(commands.Bot):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    async def on_ready(self):
        logging.info(f"Selfbot logged in as {self.user}")

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
