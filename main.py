import os
import logging
import asyncio
import datetime
from typing import Dict, List, Optional, Union, Literal

import discord
from discord import app_commands
from discord.ext import commands
from discord.ui import Button, View
from dotenv import load_dotenv

import firebase_admin
from firebase_admin import credentials, firestore

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('rep_bot')

def is_valid_guild_id(guild_id_str):
    """Check if a string is a valid guild ID."""
    if not guild_id_str:
        return False
    try:
        guild_id = int(guild_id_str)
        return 10000000000000000 <= guild_id <= 9999999999999999999
    except ValueError:
        return False

# Admin users who can remove reputation
ADMIN_USERS = [
    1109714845768618044,  # Example user ID
]

# Cooldown settings
rep_cooldowns = {}  # user_id -> timestamp
COOLDOWN_SECONDS = 60  # 1 min

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
    db = firestore.client()
    reps_collection = db.collection('reps')
    channels_collection = db.collection('channels')
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

# Rep trigger words - without spaces for better detection
rep_triggers = ['thanks', 'ty', 'tysm', 'thank you', 'appreciated', 'thx']

def contains_trigger_word(content: str) -> bool:
    """
    Check if content contains any trigger words with proper word boundary detection.
    This avoids false positives like "party" matching "ty".
    """
    content_lower = content.lower()
    
    for trigger in rep_triggers:
        # Find all occurrences of the trigger
        start_pos = 0
        while True:
            # Find the next occurrence
            pos = content_lower.find(trigger, start_pos)
            if pos == -1:  # No more occurrences
                break
                
            # Check if it's a standalone word
            before_pos = pos - 1
            after_pos = pos + len(trigger)
            
            # Check character before (space or start of string)
            before_ok = before_pos < 0 or content_lower[before_pos].isspace() or not content_lower[before_pos].isalnum()
            
            # Check character after (space or end of string)
            after_ok = after_pos >= len(content_lower) or content_lower[after_pos].isspace() or not content_lower[after_pos].isalnum()
            
            # If it's a standalone word, return True
            if before_ok and after_ok:
                return True
                
            # Move to check next occurrence
            start_pos = pos + 1
    
    # No trigger words found
    return False

# Firebase helper functions
async def give_rep(guild_id: str, user_id: str, channel_id: str, 
                   channel_name: str, given_by: str) -> bool:
    """Give a reputation point to a user."""
    try:
        # User document reference
        user_doc_id = f"{guild_id}_{user_id}"
        user_ref = reps_collection.document(user_doc_id)
        
        # Channel document reference
        channel_doc_id = f"{guild_id}_{channel_id}"
        channel_ref = channels_collection.document(channel_doc_id)
        
        # Instead of using a transaction, we'll use get() and set/update directly
        # This avoids the "read after write" transaction error
        
        # Get user document
        user_doc = user_ref.get()
        
        if not user_doc.exists:
            # Initialize user document
            user_ref.set({
                'guild_id': guild_id,
                'user_id': user_id,
                'count': 1,
                'channels': {
                    channel_id: {
                        'name': channel_name,
                        'count': 1
                    }
                },
                'given_by': {given_by: 1}
            })
        else:
            # Update user document
            user_data = user_doc.to_dict()
            
            # Update total count
            new_count = user_data.get('count', 0) + 1
            
            # Update channel counts
            channels = user_data.get('channels', {})
            if channel_id in channels:
                channels[channel_id]['count'] = channels[channel_id].get('count', 0) + 1
                # Update channel name in case it changed
                channels[channel_id]['name'] = channel_name
            else:
                channels[channel_id] = {'name': channel_name, 'count': 1}
            
            # Update given_by counts
            given_by_dict = user_data.get('given_by', {})
            given_by_dict[given_by] = given_by_dict.get(given_by, 0) + 1
            
            user_ref.update({
                'count': new_count,
                'channels': channels,
                'given_by': given_by_dict
            })
        
        # Get channel document
        channel_doc = channel_ref.get()
        
        if not channel_doc.exists:
            # Initialize channel document
            channel_ref.set({
                'guild_id': guild_id,
                'channel_id': channel_id,
                'channel_name': channel_name,
                'users': {user_id: 1},
                'total_reps': 1
            })
        else:
            # Update channel document
            channel_data = channel_doc.to_dict()
            
            # Update total count
            new_total = channel_data.get('total_reps', 0) + 1
            
            # Update user counts
            users = channel_data.get('users', {})
            users[user_id] = users.get(user_id, 0) + 1
            
            channel_ref.update({
                'channel_name': channel_name,
                'total_reps': new_total,
                'users': users
            })
        
        return True
        
    except Exception as e:
        logger.error(f"Error giving rep: {e}")
        return False

async def remove_rep(guild_id: str, user_id: str, 
                    channel_id: Optional[str] = None) -> bool:
    """Remove a reputation point from a user."""
    try:
        # User document reference
        user_doc_id = f"{guild_id}_{user_id}"
        user_ref = reps_collection.document(user_doc_id)
        
        # Get user document
        user_doc = user_ref.get()
        
        if not user_doc.exists:
            return False
            
        user_data = user_doc.to_dict()
        current_count = user_data.get('count', 0)
        
        if current_count <= 0:
            return False
            
        # If a specific channel was specified
        if channel_id:
            channels = user_data.get('channels', {})
            
            if channel_id not in channels or channels[channel_id].get('count', 0) <= 0:
                return False
                
            # Update channel count
            channels[channel_id]['count'] = max(0, channels[channel_id].get('count', 0) - 1)
            
            # Update channel document
            channel_doc_id = f"{guild_id}_{channel_id}"
            channel_ref = channels_collection.document(channel_doc_id)
            channel_doc = channel_ref.get()
            
            if channel_doc.exists:
                channel_data = channel_doc.to_dict()
                users = channel_data.get('users', {})
                
                if user_id in users and users[user_id] > 0:
                    users[user_id] -= 1
                    channel_ref.update({
                        'users': users,
                        'total_reps': max(0, channel_data.get('total_reps', 0) - 1)
                    })
            
            # Update user document
            user_ref.update({
                'count': max(0, current_count - 1),
                'channels': channels
            })
        else:
            # Remove from total count only
            user_ref.update({
                'count': max(0, current_count - 1)
            })
            
        return True
        
    except Exception as e:
        logger.error(f"Error removing rep: {e}")
        return False

async def get_user_profile(guild_id: str, user_id: str) -> Dict:
    """Get a user's reputation profile."""
    try:
        doc_id = f"{guild_id}_{user_id}"
        doc = reps_collection.document(doc_id).get()
        
        if not doc.exists:
            return {
                'user_id': user_id,
                'guild_id': guild_id,
                'count': 0,
                'channels': {},
                'given_by': {}
            }
            
        return doc.to_dict()
        
    except Exception as e:
        logger.error(f"Error getting user profile: {e}")
        return {
            'user_id': user_id,
            'guild_id': guild_id,
            'count': 0,
            'channels': {},
            'given_by': {}
        }

async def get_top_channels(guild_id: str, user_id: str, limit: int = 3) -> List[Dict]:
    """Get the top channels where a user received reputation."""
    try:
        profile = await get_user_profile(guild_id, user_id)
        channels = profile.get('channels', {})
        
        # Convert to list and sort by count
        channel_list = [
            {'id': k, 'name': v.get('name', 'Unknown'), 'count': v.get('count', 0)}
            for k, v in channels.items()
        ]
        
        # Sort by count (descending)
        channel_list.sort(key=lambda x: x['count'], reverse=True)
        
        return channel_list[:limit]
        
    except Exception as e:
        logger.error(f"Error getting top channels: {e}")
        return []

async def get_leaderboard(guild_id: str, limit: int = 10, 
                         channel_id: Optional[str] = None) -> List[Dict]:
    """Get the reputation leaderboard."""
    try:
        if channel_id:
            # Channel-specific leaderboard
            channel_doc_id = f"{guild_id}_{channel_id}"
            channel_doc = channels_collection.document(channel_doc_id).get()
            
            if not channel_doc.exists:
                return []
            
            channel_data = channel_doc.to_dict()
            users = channel_data.get('users', {})
            
            # Convert to list and sort
            user_list = [
                {'user_id': user_id, 'count': count}
                for user_id, count in users.items()
            ]
            
            # Sort by count (descending)
            user_list.sort(key=lambda x: x['count'], reverse=True)
            
            return user_list[:limit]
        else:
            # Global leaderboard
            query = (reps_collection
                    .where('guild_id', '==', guild_id)
                    .order_by('count', direction=firestore.Query.DESCENDING)
                    .limit(limit))
            
            docs = query.stream()
            
            return [doc.to_dict() for doc in docs]
            
    except Exception as e:
        logger.error(f"Error getting leaderboard: {e}")
        return []

async def get_channel_leaderboard(guild_id: str, limit: int = 5) -> List[Dict]:
    """Get the leaderboard of channels with most reputation points."""
    try:
        query = (channels_collection
                .where('guild_id', '==', guild_id)
                .order_by('total_reps', direction=firestore.Query.DESCENDING)
                .limit(limit))
        
        docs = query.stream()
        
        return [doc.to_dict() for doc in docs]
        
    except Exception as e:
        logger.error(f"Error getting channel leaderboard: {e}")
        return []

# Cooldown helper functions
def is_on_cooldown(user_id: int) -> bool:
    """Check if a user is on cooldown for giving rep."""
    if user_id not in rep_cooldowns:
        return False
        
    last_time = rep_cooldowns[user_id]
    now = datetime.datetime.now().timestamp()
    
    return (now - last_time) < COOLDOWN_SECONDS

def get_cooldown_remaining(user_id: int) -> int:
    """Get remaining cooldown time in seconds."""
    if user_id not in rep_cooldowns:
        return 0
        
    last_time = rep_cooldowns[user_id]
    now = datetime.datetime.now().timestamp()
    elapsed = now - last_time
    
    return max(0, COOLDOWN_SECONDS - int(elapsed))

def update_cooldown(user_id: int):
    """Update a user's cooldown timestamp."""
    rep_cooldowns[user_id] = datetime.datetime.now().timestamp()

def format_cooldown(seconds: int) -> str:
    """Format cooldown time into a readable string."""
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    
    parts = []
    if hours > 0:
        parts.append(f"{hours} hour{'s' if hours > 1 else ''}")
    if minutes > 0:
        parts.append(f"{minutes} minute{'s' if minutes > 1 else ''}")
    if seconds > 0 and not hours:
        parts.append(f"{seconds} second{'s' if seconds > 1 else ''}")
        
    return ", ".join(parts)

# UI Components
class LeaderboardView(View):
    """Interactive view for leaderboard navigation."""
    
    def __init__(self, bot, guild_id: str, channel_id: Optional[str] = None):
        super().__init__(timeout=60)
        self.bot = bot
        self.guild_id = guild_id
        self.channel_id = channel_id
        self.page = 1
        self.entries_per_page = 10
        
    @discord.ui.button(label="◀️ Previous", style=discord.ButtonStyle.secondary)
    async def previous_button(self, interaction: discord.Interaction, button: Button):
        if self.page > 1:
            self.page -= 1
            await interaction.response.defer()
            await self.update_leaderboard(interaction)
        else:
            await interaction.response.send_message("You are already on the first page.", ephemeral=True)
    
    @discord.ui.button(label="Next ▶️", style=discord.ButtonStyle.secondary)
    async def next_button(self, interaction: discord.Interaction, button: Button):
        self.page += 1
        await interaction.response.defer()
        
        # Check if there are entries for this page
        leaderboard = await get_leaderboard(
            self.guild_id, 
            limit=self.entries_per_page * self.page,
            channel_id=self.channel_id
        )
        
        if len(leaderboard) < self.entries_per_page * (self.page - 1) + 1:
            # No entries for this page, go back
            self.page -= 1
            await interaction.followup.send("You've reached the end of the leaderboard.", ephemeral=True)
        else:
            await self.update_leaderboard(interaction)
    
    @discord.ui.button(label="🌐 Global", style=discord.ButtonStyle.primary)
    async def global_button(self, interaction: discord.Interaction, button: Button):
        if self.channel_id is not None:
            self.channel_id = None
            self.page = 1
            await interaction.response.defer()
            await self.update_leaderboard(interaction)
        else:
            await interaction.response.send_message("Already showing global leaderboard.", ephemeral=True)
    
    @discord.ui.button(label="📊 Channels", style=discord.ButtonStyle.primary)
    async def channels_button(self, interaction: discord.Interaction, button: Button):
        await interaction.response.defer()
        await self.show_channel_leaderboard(interaction)
    
    async def update_leaderboard(self, interaction: discord.Interaction):
        """Update the leaderboard embed and message."""
        embed = await create_leaderboard_embed(
            self.bot,
            self.guild_id, 
            self.page, 
            self.entries_per_page,
            self.channel_id
        )
        await interaction.edit_original_response(embed=embed, view=self)
    
    async def show_channel_leaderboard(self, interaction: discord.Interaction):
        """Show the channel leaderboard."""
        channel_lb = await get_channel_leaderboard(self.guild_id, limit=10)
        
        if not channel_lb:
            await interaction.followup.send("No channel data available.", ephemeral=True)
            return
        
        embed = discord.Embed(
            title="📊 Channel Reputation Leaderboard",
            description="Channels with the most reputation activity:",
            color=discord.Color.blurple()
        )
        
        for i, channel in enumerate(channel_lb, 1):
            channel_name = channel.get('channel_name', 'Unknown')
            channel_id = channel.get('channel_id', '0')
            total_reps = channel.get('total_reps', 0)
            
            embed.add_field(
                name=f"{i}. {channel_name}",
                value=f"<#{channel_id}>\n**{total_reps}** total reputation points",
                inline=False
            )
        
        await interaction.followup.send(embed=embed, ephemeral=False)

    async def on_timeout(self):
        """Disable all buttons when the view times out."""
        for item in self.children:
            item.disabled = True

class ChannelLeaderboardSelect(discord.ui.Select):
    """Dropdown for selecting a channel leaderboard."""
    
    def __init__(self, bot, guild_id: str, channels: List[Dict]):
        options = [
            discord.SelectOption(
                label=channel.get('channel_name', 'Unknown'),
                description=f"{channel.get('total_reps', 0)} total points",
                value=channel.get('channel_id', '0'),
                emoji="📊"
            )
            for channel in channels[:25]  # Discord limits to 25 options
        ]
        
        super().__init__(
            placeholder="Select a channel leaderboard...",
            min_values=1,
            max_values=1,
            options=options
        )
        self.bot = bot
        self.guild_id = guild_id
    
    async def callback(self, interaction: discord.Interaction):
        """Handle channel selection."""
        channel_id = self.values[0]
        
        # Create a new leaderboard view for the selected channel
        view = LeaderboardView(self.bot, self.guild_id, channel_id)
        
        # Create the leaderboard embed
        embed = await create_leaderboard_embed(
            self.bot,
            self.guild_id, 
            page=1, 
            entries_per_page=10,
            channel_id=channel_id
        )
        
        await interaction.response.edit_message(embed=embed, view=view)

class ChannelSelectView(View):
    """View for selecting a channel leaderboard."""
    
    def __init__(self, bot, guild_id: str, channels: List[Dict]):
        super().__init__(timeout=60)
        self.add_item(ChannelLeaderboardSelect(bot, guild_id, channels))
    
    async def on_timeout(self):
        """Disable all components when the view times out."""
        for item in self.children:
            item.disabled = True

# Helper functions
async def create_leaderboard_embed(
    bot,
    guild_id: str, 
    page: int = 1, 
    entries_per_page: int = 10,
    channel_id: Optional[str] = None
) -> discord.Embed:
    """Create a leaderboard embed."""
    guild = bot.get_guild(int(guild_id))
    
    if channel_id:
        channel = guild.get_channel(int(channel_id))
        channel_name = channel.name if channel else "Unknown Channel"
        title = f"🏆 Reputation Leaderboard - #{channel_name}"
    else:
        title = "🏆 Global Reputation Leaderboard"
    
    embed = discord.Embed(
        title=title,
        description=f"Page {page}",
        color=discord.Color.gold()
    )
    
    # Calculate offset based on page
    offset = (page - 1) * entries_per_page
    
    # Get leaderboard data
    leaderboard = await get_leaderboard(
        guild_id,
        limit=entries_per_page * page,
        channel_id=channel_id
    )
    
    # Slice for current page
    if offset < len(leaderboard):
        page_entries = leaderboard[offset:offset + entries_per_page]
    else:
        page_entries = []
    
    if not page_entries:
        embed.add_field(
            name="No entries found",
            value="Be the first to earn reputation!",
            inline=False
        )
        return embed
    
    # Add entries to embed
    for i, entry in enumerate(page_entries, offset + 1):
        user_id = entry.get('user_id')
        count = entry.get('count', 0)
        
        # Get medal emoji
        medal = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"{i}."
        
        # Try to get user from guild
        member = guild.get_member(int(user_id)) if user_id else None
        name = member.display_name if member else f"User {user_id}"
        
        embed.add_field(
            name=f"{medal} {name}",
            value=f"**{count}** reputation point{'s' if count != 1 else ''}",
            inline=False
        )
    
    # Add footer with timestamp
    embed.set_footer(
        text=f"Updated {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}"
    )
    
    return embed

# Events
@bot.event
async def on_ready():
    logger.info(f"Bot is online as {bot.user.name}")
    
    # Set bot status
    await bot.change_presence(
        activity=discord.Activity(
            type=discord.ActivityType.watching, 
            name="reputation points"
        ),
        status=discord.Status.online
    )
    
    # Log which guilds the bot is in
    guilds = bot.guilds
    logger.info(f"Bot is in {len(guilds)} guilds:")
    for guild in guilds:
        logger.info(f"- {guild.name} (ID: {guild.id})")
    
    # Try to sync commands to all guilds the bot is in
    if os.getenv('SYNC_COMMANDS', 'false').lower() == 'true':
        logger.info("Auto-syncing commands...")
        
        # First, check for specific guild ID in env var
        guild_id = os.getenv('GUILD_ID')
        if is_valid_guild_id(guild_id):
            try:
                # Sync to specific guild first
                guild = discord.Object(id=int(guild_id))
                await bot.tree.sync(guild=guild)
                logger.info(f"Commands synced to specified guild ID: {guild_id}")
            except Exception as e:
                logger.error(f"Error syncing to specified guild: {e}")
        
        # Then try to sync to all current guilds
        for guild in guilds:
            try:
                guild_obj = discord.Object(id=guild.id)
                await bot.tree.sync(guild=guild_obj)
                logger.info(f"Commands synced to guild: {guild.name} (ID: {guild.id})")
            except Exception as e:
                logger.error(f"Error syncing to guild {guild.name}: {e}")
    else:
        logger.info("Automatic command sync is disabled. Use !sync in your server to manually sync commands.")

@bot.event
async def on_message(message: discord.Message):
    """Listen for messages containing reputation trigger words."""
    # Skip if message is from a bot
    if message.author.bot:
        return
        
    # Skip if not in a guild
    if not message.guild:
        return
    
    # Process commands first - VERY IMPORTANT!
    await bot.process_commands(message)
    
    # Skip if no mentions
    if not message.mentions:
        return
    
    # Check if message contains a trigger word using our improved detection
    if not contains_trigger_word(message.content):
        return
    
    # Log that we detected a valid trigger word
    logger.info(f"Detected rep trigger in message: {message.content}")
    
    # Check for cooldown
    if is_on_cooldown(message.author.id):
        remaining = get_cooldown_remaining(message.author.id)
        remaining_str = format_cooldown(remaining)
        
        await message.channel.send(
            f"⏱️ **Cooldown Active**: {message.author.mention}, you must wait "
            f"{remaining_str} before giving more reputation points.",
            delete_after=10
        )
        return
        
    # Process valid mentions (no self-rep)
    valid_mentions = [
        user for user in message.mentions 
        if user.id != message.author.id and not user.bot
    ]
    
    if not valid_mentions:
        return
    
    # Log valid mentions
    logger.info(f"Valid mentions: {[user.name for user in valid_mentions]}")
        
    # Give rep to each valid mentioned user
    successful_mentions = []
    
    for user in valid_mentions:
        logger.info(f"Giving rep to {user.name} from {message.author.name}")
        result = await give_rep(
            str(message.guild.id),
            str(user.id),
            str(message.channel.id),
            message.channel.name,
            str(message.author.id)
        )
        
        if result:
            successful_mentions.append(user)
    
    # Send confirmation and update cooldown
    if successful_mentions:
        mentions_text = ", ".join(user.mention for user in successful_mentions)
        
        await message.channel.send(
            f"🌟 {message.author.mention} has given a reputation point to {mentions_text}!"
        )
        
        # Apply cooldown
        update_cooldown(message.author.id)

# Command Sync
@bot.command(name="sync")
async def sync_commands(ctx):
    """Manually sync slash commands to this server"""
    # Initial response
    message = await ctx.send("🔄 Syncing commands to this server...")
    
    try:
        # Always sync to the current guild for immediate results
        await bot.tree.sync(guild=discord.Object(id=ctx.guild.id))
        await message.edit(content="✅ Commands synced successfully to this server! They should appear momentarily.")
        
        # Log success
        logger.info(f"Commands manually synced to guild ID: {ctx.guild.id}")
    except Exception as e:
        await message.edit(content=f"❌ Failed to sync commands: {str(e)}")
        logger.error(f"Error during manual command sync: {e}")

# Debug command
@bot.command(name="check")
async def check_bot(ctx):
    """Check if the bot is responding to text commands"""
    await ctx.send(f"✅ Bot is online and responding to text commands! To register slash commands, use `!sync`")

# Slash commands
@bot.tree.command(
    name="give_rep",
    description="Give reputation points to a user"
)
@app_commands.describe(
    user="The user to give reputation to"
)
async def give_rep_command(
    interaction: discord.Interaction, 
    user: discord.Member
):
    """Give reputation to a user via slash command."""
    # Check if user is trying to rep themselves
    if user.id == interaction.user.id:
        await interaction.response.send_message(
            "⚠️ **Error**: You cannot give reputation points to yourself.",
            ephemeral=True
        )
        return
        
    # Check if target is a bot
    if user.bot:
        await interaction.response.send_message(
            "⚠️ **Error**: You cannot give reputation points to bots.",
            ephemeral=True
        )
        return
        
    # Check for cooldown
    if is_on_cooldown(interaction.user.id):
        remaining = get_cooldown_remaining(interaction.user.id)
        remaining_str = format_cooldown(remaining)
        
        await interaction.response.send_message(
            f"⏱️ **Cooldown Active**: You must wait {remaining_str} before giving "
            f"more reputation points.",
            ephemeral=True
        )
        return
        
    # Defer response
    await interaction.response.defer(ephemeral=False)
    
    # Give rep
    logger.info(f"Giving rep via slash command: {interaction.user.name} -> {user.name}")
    result = await give_rep(
        str(interaction.guild_id),
        str(user.id),
        str(interaction.channel_id),
        interaction.channel.name,
        str(interaction.user.id)
    )
    
    if result:
        # Apply cooldown
        update_cooldown(interaction.user.id)
        
        await interaction.followup.send(
            f"🌟 {interaction.user.mention} has given a reputation point to {user.mention}!"
        )
    else:
        await interaction.followup.send(
            "⚠️ **Error**: Failed to give reputation. Please try again later.",
            ephemeral=True
        )

@bot.tree.command(
    name="profile",
    description="View a user's reputation profile"
)
@app_commands.describe(
    user="The user to view the profile of (default: yourself)"
)
async def profile_command(
    interaction: discord.Interaction, 
    user: Optional[discord.Member] = None
):
    """View a user's reputation profile."""
    # Use the caller if no user is specified
    target_user = user or interaction.user
    
    # Defer response
    await interaction.response.defer(ephemeral=False)
    
    # Get user profile
    profile = await get_user_profile(
        str(interaction.guild_id),
        str(target_user.id)
    )
    
    # Get top channels
    top_channels = await get_top_channels(
        str(interaction.guild_id),
        str(target_user.id),
        limit=3
    )
    
    # Create embed
    embed = discord.Embed(
        title=f"Reputation Profile: {target_user.display_name}",
        color=target_user.color or discord.Color.blue()
    )
    
    # Add user avatar
    embed.set_thumbnail(url=target_user.display_avatar.url)
    
    # Add reputation count
    rep_count = profile.get('count', 0)
    embed.add_field(
        name="Total Reputation",
        value=f"🌟 **{rep_count}** point{'s' if rep_count != 1 else ''}",
        inline=False
    )
    
    # Add top channels
    if top_channels:
        channels_text = "\n".join(
            f"<#{channel['id']}>: **{channel['count']}** point{'s' if channel['count'] != 1 else ''}"
            for channel in top_channels
        )
        embed.add_field(
            name="Most Active Channels",
            value=channels_text,
            inline=False
        )
    
    # Add footer
    embed.set_footer(
        text=f"User ID: {target_user.id} • Joined: {target_user.joined_at.strftime('%B %d, %Y')}"
    )
    
    await interaction.followup.send(embed=embed)

@bot.tree.command(
    name="leaderboard",
    description="View the reputation leaderboard"
)
@app_commands.describe(
    channel="View leaderboard for a specific channel (default: global)",
    scope="View global or channel-specific leaderboard"
)
@app_commands.choices(
    scope=[
        app_commands.Choice(name="Global", value="global"),
        app_commands.Choice(name="Channel", value="channel"),
        app_commands.Choice(name="All Channels", value="channels")
    ]
)
async def leaderboard_command(
    interaction: discord.Interaction, 
    channel: Optional[discord.TextChannel] = None,
    scope: Optional[str] = "global"
):
    """View the reputation leaderboard."""
    await interaction.response.defer(ephemeral=False)
    
    guild_id = str(interaction.guild_id)
    
    if scope == "channels":
        # Show channel leaderboard
        channel_lb = await get_channel_leaderboard(guild_id, limit=10)
        
        if not channel_lb:
            await interaction.followup.send("No channel data available yet.", ephemeral=True)
            return
        
        embed = discord.Embed(
            title="📊 Channel Reputation Leaderboard",
            description="Channels with the most reputation activity:",
            color=discord.Color.blurple()
        )
        
        for i, channel_data in enumerate(channel_lb, 1):
            channel_name = channel_data.get('channel_name', 'Unknown')
            channel_id = channel_data.get('channel_id', '0')
            total_reps = channel_data.get('total_reps', 0)
            
            embed.add_field(
                name=f"{i}. {channel_name}",
                value=f"<#{channel_id}>\n**{total_reps}** total reputation points",
                inline=False
            )
        
        # Create view with channel selection
        view = ChannelSelectView(bot, guild_id, channel_lb)
        
        await interaction.followup.send(embed=embed, view=view)
        return
    
    # For global or specific channel
    channel_id = str(channel.id) if channel and scope == "channel" else None
    
    # Create leaderboard view
    view = LeaderboardView(bot, guild_id, channel_id)
    
    # Create embed
    embed = await create_leaderboard_embed(
        bot,
        guild_id,
        page=1,
        entries_per_page=10,
        channel_id=channel_id
    )
    
    await interaction.followup.send(embed=embed, view=view)

@bot.tree.command(
    name="remove_rep",
    description="Remove reputation points from a user (Admin only)"
)
@app_commands.describe(
    user="The user to remove reputation from",
    channel="Remove rep from a specific channel (optional)",
    amount="Amount of reputation to remove (default: 1)"
)
async def remove_rep_command(
    interaction: discord.Interaction, 
    user: discord.Member,
    channel: Optional[discord.TextChannel] = None,
    amount: Optional[int] = 1
):
    """Remove reputation from a user (admin only)."""
    # Check if user is an admin
    if interaction.user.id not in ADMIN_USERS and not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message(
            "⚠️ **Access Denied**: You do not have permission to remove reputation points.",
            ephemeral=True
        )
        return
        
    # Validate amount
    if amount < 1:
        await interaction.response.send_message(
            "⚠️ **Error**: Amount must be at least 1.",
            ephemeral=True
        )
        return
        
    # Defer response
    await interaction.response.defer(ephemeral=False)
    
    # Remove rep multiple times if needed
    channel_id = str(channel.id) if channel else None
    success_count = 0
    
    for _ in range(amount):
        result = await remove_rep(
            str(interaction.guild_id),
            str(user.id),
            channel_id
        )
        
        if result:
            success_count += 1
        else:
            break
            
    if success_count > 0:
        channel_text = f" from channel {channel.mention}" if channel else ""
        
        await interaction.followup.send(
            f"⚖️ {interaction.user.mention} has removed {success_count} reputation "
            f"point{'s' if success_count != 1 else ''} from {user.mention}{channel_text}."
        )
    else:
        await interaction.followup.send(
            f"⚠️ **Error**: {user.mention} has no reputation points to remove.",
            ephemeral=True
        )

# Run the bot
if __name__ == "__main__":
    # If there's an issue with the filename, make sure we're using the right one
    script_name = os.path.basename(__file__)
    logger.info(f"Starting bot from script: {script_name}")
    
    bot.run(os.getenv('DISCORD_TOKEN'))