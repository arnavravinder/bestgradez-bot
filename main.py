import os
import logging
from dotenv import load_dotenv
import discord
from discord.ext import commands
import firebase_admin
from firebase_admin import credentials

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('rep_bot')

# Initialize Firebase
try:
    cred = credentials.Certificate({
        "type": "service_account",
        "project_id": os.getenv('FIREBASE_PROJECT_ID'),
        "private_key_id": os.getenv('FIREBASE_PRIVATE_KEY_ID'),
        "private_key": os.getenv('FIREBASE_PRIVATE_KEY').replace("\\n", "\n"),
        "client_email": os.getenv('FIREBASE_CLIENT_EMAIL'),
        "client_id": os.getenv('FIREBASE_CLIENT_ID'),
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
        "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
        "client_x509_cert_url": os.getenv('FIREBASE_CLIENT_CERT_URL')
    })
    firebase_admin.initialize_app(cred)
    logger.info("Firebase initialized successfully")
except Exception as e:
    logger.error(f"Failed to initialize Firebase: {e}")
    raise

# Define intents
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

# Create bot instance
bot = commands.Bot(command_prefix='!', intents=intents)

# Load cogs
@bot.event
async def on_ready():
    logger.info(f"Bot is online as {bot.user.name}")
    
    # Set bot status
    await bot.change_presence(
        activity=discord.Activity(type=discord.ActivityType.watching, name="reputation points"),
        status=discord.Status.online
    )
    
    # Load cogs
    await bot.load_extension("cogs.reputation")
    logger.info("Reputation cog loaded")
    
    # Sync commands if SYNC_COMMANDS env var is set to true
    if os.getenv('SYNC_COMMANDS', 'false').lower() == 'true':
        logger.info("Auto-syncing commands...")
        
        # Sync to specific guild if GUILD_ID is set
        if os.getenv('GUILD_ID'):
            guild = discord.Object(id=int(os.getenv('GUILD_ID')))
            await bot.tree.sync(guild=guild)
            logger.info(f"Commands synced to guild ID: {os.getenv('GUILD_ID')}")
        else:
            await bot.tree.sync()
            logger.info("Commands synced globally")
    else:
        logger.info("Skipping command sync. Run register_commands.py to sync commands manually.")

# Manual command sync command (owner only)
@bot.command(name="sync", hidden=True)
@commands.is_owner()
async def sync_commands(ctx, guild_id: str = None):
    """Sync slash commands (Bot owner only)"""
    if guild_id:
        guild = discord.Object(id=int(guild_id))
        bot.tree.copy_global_to(guild=guild)
        await bot.tree.sync(guild=guild)
        await ctx.send(f"Commands synced to guild ID: {guild_id}")
    else:
        await bot.tree.sync()
        await ctx.send("Commands synced globally (may take up to an hour to propagate)")

# Run the bot
if __name__ == "__main__":
    bot.run(os.getenv('DISCORD_TOKEN'))