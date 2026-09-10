#!/usr/bin/env python3
import argparse
import asyncio
import contextlib
import os
import subprocess

AUDIO_SOURCE = "stream-mix.monitor"
BOT_VOLUME_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), ".discord_bot_volume.txt")

try:
    import discord
    from discord.ext import commands
except ImportError:
    raise SystemExit("Install the discord.py package: pip install discord.py")


class AudioBot(commands.Bot):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.guild_commands_synced = False
        self.transmissions = {}
        self.volume_task = None

    async def on_ready(self):
        print(f"Bot connected as {self.user} ({self.user.id})", flush=True)
        if self.guild_commands_synced:
            return

        try:
            synced_total = 0
            for guild in self.guilds:
                self.tree.copy_global_to(guild=guild)
                synced = await self.tree.sync(guild=guild)
                synced_total += len(synced)
            self.guild_commands_synced = True
            print(
                f"Commands synced across servers: {synced_total}",
                flush=True,
            )
        except Exception as exc:
            print(f"Error syncing commands: {exc}", flush=True)

    def _source_available(self):
        try:
            result = subprocess.run(
                ["pactl", "list", "short", "sources"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            return result.returncode == 0 and any(
                line.split()[1] == AUDIO_SOURCE
                for line in result.stdout.splitlines()
                if len(line.split()) > 1
            )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False

    def _stop_transmission(self, guild_id):
        transmission = self.transmissions.pop(guild_id, None)
        if transmission:
            voice_client, _ = transmission
            if voice_client.is_playing():
                voice_client.stop()
            return voice_client
        return None

    @staticmethod
    def _read_volume():
        try:
            with open(BOT_VOLUME_FILE, "r", encoding="ascii") as f:
                return max(0.0, min(2.0, float(f.read().strip())))
        except (FileNotFoundError, ValueError):
            return 1.0

    async def _watch_volume(self):
        while True:
            volume = self._read_volume()
            for _, source in self.transmissions.values():
                source.volume = volume
            await asyncio.sleep(0.1)

    async def _start_transmission(self, voice_client):
        if not voice_client:
            return False, "Voice client is not connected."
        if not self._source_available():
            return False, f"The source {AUDIO_SOURCE} is not available. Start the mixer first."

        if voice_client.is_playing():
            return True, "The transmission is already active."

        try:
            ffmpeg_source = discord.FFmpegPCMAudio(
                AUDIO_SOURCE,
                executable="ffmpeg",
                before_options="-nostdin -f pulse",
                options="-vn -ac 2 -ar 48000 -loglevel warning",
            )
            audio_source = discord.PCMVolumeTransformer(
                ffmpeg_source,
                volume=self._read_volume(),
            )

            def on_audio_end(error):
                if error:
                    print(f"FFmpeg error: {error}", flush=True)
                self.transmissions.pop(voice_client.guild.id, None)

            voice_client.play(audio_source, after=on_audio_end)
            self.transmissions[voice_client.guild.id] = (
                voice_client, audio_source)
            print(f"Streaming {AUDIO_SOURCE}.", flush=True)
            return True, "Transmission started."
        except Exception as exc:
            print(f"Error starting transmission: {exc}", flush=True)
            return False, f"Error starting FFmpeg: {exc}"

    async def on_message(self, message):
        if message.author == self.user:
            return
        if message.content.lower() == "!ping":
            await message.channel.send("pong")
        await self.process_commands(message)


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--token")
    args = parser.parse_args()
    token = args.token or os.environ.get("DISCORD_BOT_TOKEN")
    if not token:
        parser.error("provide --token or set DISCORD_BOT_TOKEN")

    intents = discord.Intents.default()
    intents.message_content = True
    intents.voice_states = True

    bot = AudioBot(command_prefix="!", intents=intents)

    @bot.tree.command(
        name="play",
        description="Joins your voice channel and streams system audio",
    )
    async def play(interaction: discord.Interaction):
        if not interaction.guild:
            await interaction.response.send_message(
                "This command can only be used in a server.", ephemeral=True)
            return

        voice_state = interaction.user.voice
        if voice_state is None or voice_state.channel is None:
            await interaction.response.send_message(
                "Join a voice channel before using /play.", ephemeral=True)
            return

        channel = voice_state.channel
        voice_client = interaction.guild.voice_client
        try:
            if voice_client is None:
                voice_client = await channel.connect()
            elif voice_client.channel != channel:
                await voice_client.move_to(channel)

            _, message = await bot._start_transmission(voice_client)
            await interaction.response.send_message(
                f"{message} Channel: **{channel.name}**.", ephemeral=True)
        except Exception as exc:
            await interaction.response.send_message(
                f"Could not join the channel: {exc}", ephemeral=True)

    @bot.tree.command(
        name="stop",
        description="Stops the system audio transmission",
    )
    async def stop(interaction: discord.Interaction):
        if not interaction.guild:
            await interaction.response.send_message(
                "This command can only be used in a server.", ephemeral=True)
            return

        bot._stop_transmission(interaction.guild.id)
        await interaction.response.send_message(
            "Transmission stopped.", ephemeral=True)

    bot.volume_task = asyncio.create_task(bot._watch_volume())
    try:
        await bot.start(token)
    finally:
        for guild_id in list(bot.transmissions):
            bot._stop_transmission(guild_id)
        bot.volume_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await bot.volume_task


if __name__ == "__main__":
    asyncio.run(main())
