import os
import sys
import asyncio
import logging
from dotenv import load_dotenv
import discord
from discord import app_commands
from discord.ext import commands

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('command_registration')

# Load environment variables
load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')
GUILD_ID = os.getenv('GUILD_ID')  # Optional: for guild-specific commands

# Command definitions
# These should match the commands in your cogs
reputation_commands = [
    app_commands.Command(
        name="give_rep",
        description="Give reputation points to a user",
        callback=lambda: None,  # Placeholder function
        parameters=[
            app_commands.AppCommandOption(
                name="user",
                description="The user to give reputation to",
                type=discord.AppCommandOptionType.user,
                required=True
            )
        ]
    ),
    app_commands.Command(
        name="profile",
        description="View a user's reputation profile",
        callback=lambda: None,  # Placeholder function
        parameters=[
            app_commands.AppCommandOption(
                name="user",
                description="The user to view the profile of (default: yourself)",
                type=discord.AppCommandOptionType.user,
                required=False
            )
        ]
    ),
    app_commands.Command(
        name="leaderboard",
        description="View the reputation leaderboard",
        callback=lambda: None,  # Placeholder function
        parameters=[
            app_commands.AppCommandOption(
                name="channel",
                description="View leaderboard for a specific channel (default: global)",
                type=discord.AppCommandOptionType.channel,
                required=False
            ),
            app_commands.AppCommandOption(
                name="scope",
                description="View global or channel-specific leaderboard",
                type=discord.AppCommandOptionType.string,
                required=False,
                choices=[
                    app_commands.Choice(name="Global", value="global"),
                    app_commands.Choice(name="Channel", value="channel"),
                    app_commands.Choice(name="All Channels", value="channels")
                ]
            )
        ]
    ),
    app_commands.Command(
        name="remove_rep",
        description="Remove reputation points from a user (Admin only)",
        callback=lambda: None,  # Placeholder function
        parameters=[
            app_commands.AppCommandOption(
                name="user",
                description="The user to remove reputation from",
                type=discord.AppCommandOptionType.user,
                required=True
            ),
            app_commands.AppCommandOption(
                name="channel",
                description="Remove rep from a specific channel (optional)",
                type=discord.AppCommandOptionType.channel,
                required=False
            ),
            app_commands.AppCommandOption(
                name="amount",
                description="Amount of reputation to remove (default: 1)",
                type=discord.AppCommandOptionType.integer,
                required=False
            )
        ]
    )
]

class CommandRegistrationBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        super().__init__(command_prefix="!", intents=intents)
    
    async def setup_hook(self):
        # This executes before on_ready
        await self.register_commands()
        await self.close()  # Close the bot after registering commands
    
    async def register_commands(self):
        # Register commands
        try:
            # Add reputation commands to the command tree
            for cmd in reputation_commands:
                self.tree.add_command(cmd)
            
            # If GUILD_ID is provided, sync to a specific guild
            if GUILD_ID:
                guild = discord.Object(id=int(GUILD_ID))
                self.tree.copy_global_to(guild=guild)
                await self.tree.sync(guild=guild)
                logger.info(f"✅ Commands registered successfully to guild ID: {GUILD_ID}")
            else:
                # Otherwise sync globally (this takes up to an hour to propagate)
                await self.tree.sync()
                logger.info("✅ Commands registered globally! (May take up to an hour to appear)")
            
            logger.info("Command registration complete!")
        except Exception as e:
            logger.error(f"Error registering commands: {e}")
            raise

async def main():
    if not TOKEN:
        logger.error("No Discord token found. Please add DISCORD_TOKEN to .env file.")
        return
    
    logger.info("Starting command registration...")
    
    # Create and start the bot
    bot = CommandRegistrationBot()
    try:
        await bot.start(TOKEN)
    except Exception as e:
        logger.error(f"Error during bot startup: {e}")
    
    logger.info("Command registration process finished.")

if __name__ == "__main__":
    # Run the async function
    asyncio.run(main())