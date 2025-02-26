import logging
import asyncio
import discord
from discord import app_commands
from discord.ext import commands
from discord.ui import Button, View
from typing import Dict, List, Optional, Union, Literal
import datetime

from utils.firebase_manager import FirebaseManager

logger = logging.getLogger('rep_bot.reputation')

# Admin users who can remove reputation
ADMIN_USERS = [
    # Add your user IDs here
    123456789012345678,  # Example user ID
]

# Cooldown dictionary to track users' last rep time (user_id -> timestamp)
rep_cooldowns = {}
COOLDOWN_SECONDS = 60  # 1 min

class LeaderboardView(View):
    """Interactive view for leaderboard navigation."""
    
    def __init__(self, cog, guild_id: str, channel_id: Optional[str] = None):
        super().__init__(timeout=60)
        self.cog = cog
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
        leaderboard = await self.cog.firebase.get_leaderboard(
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
        embed = await self.cog.create_leaderboard_embed(
            self.guild_id, 
            self.page, 
            self.entries_per_page,
            self.channel_id
        )
        await interaction.edit_original_response(embed=embed, view=self)
    
    async def show_channel_leaderboard(self, interaction: discord.Interaction):
        """Show the channel leaderboard."""
        channel_lb = await self.cog.firebase.get_channel_leaderboard(self.guild_id, limit=10)
        
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
    
    def __init__(self, cog, guild_id: str, channels: List[Dict]):
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
        self.cog = cog
        self.guild_id = guild_id
    
    async def callback(self, interaction: discord.Interaction):
        """Handle channel selection."""
        channel_id = self.values[0]
        
        # Create a new leaderboard view for the selected channel
        view = LeaderboardView(self.cog, self.guild_id, channel_id)
        
        # Create the leaderboard embed
        embed = await self.cog.create_leaderboard_embed(
            self.guild_id, 
            page=1, 
            entries_per_page=10,
            channel_id=channel_id
        )
        
        await interaction.response.edit_message(embed=embed, view=view)

class ChannelSelectView(View):
    """View for selecting a channel leaderboard."""
    
    def __init__(self, cog, guild_id: str, channels: List[Dict]):
        super().__init__(timeout=60)
        self.add_item(ChannelLeaderboardSelect(cog, guild_id, channels))
    
    async def on_timeout(self):
        """Disable all components when the view times out."""
        for item in self.children:
            item.disabled = True

class ReputationCog(commands.Cog):
    """Cog for managing reputation commands and events."""
    
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.firebase = FirebaseManager()
        
        # Rep trigger words
        self.rep_triggers = ['thanks', 'ty', 'tysm', 'thank you', 'appreciated']
        
        logger.info("Reputation cog initialized")
    
    # Helper methods
    def is_on_cooldown(self, user_id: int) -> bool:
        """Check if a user is on cooldown for giving rep."""
        if user_id not in rep_cooldowns:
            return False
            
        last_time = rep_cooldowns[user_id]
        now = datetime.datetime.now().timestamp()
        
        return (now - last_time) < COOLDOWN_SECONDS
    
    def get_cooldown_remaining(self, user_id: int) -> int:
        """Get remaining cooldown time in seconds."""
        if user_id not in rep_cooldowns:
            return 0
            
        last_time = rep_cooldowns[user_id]
        now = datetime.datetime.now().timestamp()
        elapsed = now - last_time
        
        return max(0, COOLDOWN_SECONDS - int(elapsed))
    
    def update_cooldown(self, user_id: int):
        """Update a user's cooldown timestamp."""
        rep_cooldowns[user_id] = datetime.datetime.now().timestamp()
    
    def format_cooldown(self, seconds: int) -> str:
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
    
    async def create_leaderboard_embed(
        self, 
        guild_id: str, 
        page: int = 1, 
        entries_per_page: int = 10,
        channel_id: Optional[str] = None
    ) -> discord.Embed:
        """Create a leaderboard embed."""
        guild = self.bot.get_guild(int(guild_id))
        
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
        leaderboard = await self.firebase.get_leaderboard(
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
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """Listen for messages containing reputation trigger words."""
        # Skip if message is from a bot
        if message.author.bot:
            return
            
        # Skip if not in a guild
        if not message.guild:
            return
            
        # Skip if no mentions
        if not message.mentions:
            return
            
        # Check if message contains a trigger word
        content_lower = message.content.lower()
        if not any(trigger in content_lower for trigger in self.rep_triggers):
            return
            
        # Check for cooldown
        if self.is_on_cooldown(message.author.id):
            remaining = self.get_cooldown_remaining(message.author.id)
            remaining_str = self.format_cooldown(remaining)
            
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
            
        # Give rep to each valid mentioned user
        successful_mentions = []
        
        for user in valid_mentions:
            result = await self.firebase.give_rep(
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
            self.update_cooldown(message.author.id)
    
    # Slash Commands
    @app_commands.command(
        name="give_rep",
        description="Give reputation points to a user"
    )
    @app_commands.describe(
        user="The user to give reputation to"
    )
    async def give_rep(
        self, 
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
        if self.is_on_cooldown(interaction.user.id):
            remaining = self.get_cooldown_remaining(interaction.user.id)
            remaining_str = self.format_cooldown(remaining)
            
            await interaction.response.send_message(
                f"⏱️ **Cooldown Active**: You must wait {remaining_str} before giving "
                f"more reputation points.",
                ephemeral=True
            )
            return
            
        # Defer response
        await interaction.response.defer(ephemeral=False)
        
        # Give rep
        result = await self.firebase.give_rep(
            str(interaction.guild_id),
            str(user.id),
            str(interaction.channel_id),
            interaction.channel.name,
            str(interaction.user.id)
        )
        
        if result:
            # Apply cooldown
            self.update_cooldown(interaction.user.id)
            
            await interaction.followup.send(
                f"🌟 {interaction.user.mention} has given a reputation point to {user.mention}!"
            )
        else:
            await interaction.followup.send(
                "⚠️ **Error**: Failed to give reputation. Please try again later.",
                ephemeral=True
            )
    
    @app_commands.command(
        name="profile",
        description="View a user's reputation profile"
    )
    @app_commands.describe(
        user="The user to view the profile of (default: yourself)"
    )
    async def profile(
        self, 
        interaction: discord.Interaction, 
        user: Optional[discord.Member] = None
    ):
        """View a user's reputation profile."""
        # Use the caller if no user is specified
        target_user = user or interaction.user
        
        # Defer response
        await interaction.response.defer(ephemeral=False)
        
        # Get user profile
        profile = await self.firebase.get_user_profile(
            str(interaction.guild_id),
            str(target_user.id)
        )
        
        # Get top channels
        top_channels = await self.firebase.get_top_channels(
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
    
    @app_commands.command(
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
    async def leaderboard(
        self, 
        interaction: discord.Interaction, 
        channel: Optional[discord.TextChannel] = None,
        scope: Optional[str] = "global"
    ):
        """View the reputation leaderboard."""
        await interaction.response.defer(ephemeral=False)
        
        guild_id = str(interaction.guild_id)
        
        if scope == "channels":
            # Show channel leaderboard
            channel_lb = await self.firebase.get_channel_leaderboard(guild_id, limit=10)
            
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
            view = ChannelSelectView(self, guild_id, channel_lb)
            
            await interaction.followup.send(embed=embed, view=view)
            return
        
        # For global or specific channel
        channel_id = str(channel.id) if channel and scope == "channel" else None
        
        # Create leaderboard view
        view = LeaderboardView(self, guild_id, channel_id)
        
        # Create embed
        embed = await self.create_leaderboard_embed(
            guild_id,
            page=1,
            entries_per_page=10,
            channel_id=channel_id
        )
        
        await interaction.followup.send(embed=embed, view=view)
    
    @app_commands.command(
        name="remove_rep",
        description="Remove reputation points from a user (Admin only)"
    )
    @app_commands.describe(
        user="The user to remove reputation from",
        channel="Remove rep from a specific channel (optional)",
        amount="Amount of reputation to remove (default: 1)"
    )
    async def remove_rep(
        self, 
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
            result = await self.firebase.remove_rep(
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

async def setup(bot: commands.Bot):
    await bot.add_cog(ReputationCog(bot))