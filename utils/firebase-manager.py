import logging
from typing import Dict, List, Optional, Tuple, Union
from firebase_admin import firestore
from discord import User, Member, TextChannel

logger = logging.getLogger('rep_bot.firebase')

class FirebaseManager:
    """Manages all interactions with Firebase Firestore database."""
    
    def __init__(self):
        """Initialize the Firestore client."""
        self.db = firestore.client()
        self.reps_collection = self.db.collection('reps')
        self.channels_collection = self.db.collection('channels')
        logger.info("Firebase manager initialized")
        
    async def give_rep(self, guild_id: str, user_id: str, channel_id: str, 
                       channel_name: str, given_by: str) -> bool:
        """
        Give a reputation point to a user.
        
        Args:
            guild_id: The ID of the guild
            user_id: The ID of the user receiving the rep
            channel_id: The ID of the channel where rep was given
            channel_name: The name of the channel where rep was given
            given_by: The ID of the user giving the rep
            
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            # User document reference
            user_doc_id = f"{guild_id}_{user_id}"
            user_ref = self.reps_collection.document(user_doc_id)
            
            # Channel document reference
            channel_doc_id = f"{guild_id}_{channel_id}"
            channel_ref = self.channels_collection.document(channel_doc_id)
            
            # Transaction to ensure data consistency
            @firestore.transactional
            def transaction_update(transaction, user_ref, channel_ref):
                user_doc = user_ref.get(transaction=transaction)
                
                if not user_doc.exists:
                    # Initialize user document
                    transaction.set(user_ref, {
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
                    
                    transaction.update(user_ref, {
                        'count': new_count,
                        'channels': channels,
                        'given_by': given_by_dict
                    })
                
                # Update channel document
                channel_doc = channel_ref.get(transaction=transaction)
                
                if not channel_doc.exists:
                    # Initialize channel document
                    transaction.set(channel_ref, {
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
                    
                    # Update channel name in case it changed
                    transaction.update(channel_ref, {
                        'channel_name': channel_name,
                        'total_reps': new_total,
                        'users': users
                    })
                
                return True
            
            # Execute transaction
            result = transaction_update(self.db.transaction(), user_ref, channel_ref)
            return result
            
        except Exception as e:
            logger.error(f"Error giving rep: {e}")
            return False
            
    async def remove_rep(self, guild_id: str, user_id: str, 
                         channel_id: Optional[str] = None) -> bool:
        """
        Remove a reputation point from a user.
        
        Args:
            guild_id: The ID of the guild
            user_id: The ID of the user to remove rep from
            channel_id: Optional channel to remove rep from specifically
            
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            # User document reference
            user_doc_id = f"{guild_id}_{user_id}"
            user_ref = self.reps_collection.document(user_doc_id)
            
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
                channel_ref = self.channels_collection.document(channel_doc_id)
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
    
    async def get_user_profile(self, guild_id: str, user_id: str) -> Dict:
        """
        Get a user's reputation profile.
        
        Args:
            guild_id: The ID of the guild
            user_id: The ID of the user
            
        Returns:
            Dict: User profile data
        """
        try:
            doc_id = f"{guild_id}_{user_id}"
            doc = self.reps_collection.document(doc_id).get()
            
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
    
    async def get_top_channels(self, guild_id: str, user_id: str, limit: int = 3) -> List[Dict]:
        """
        Get the top channels where a user received reputation.
        
        Args:
            guild_id: The ID of the guild
            user_id: The ID of the user
            limit: Maximum number of channels to return
            
        Returns:
            List[Dict]: List of top channels
        """
        try:
            profile = await self.get_user_profile(guild_id, user_id)
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
    
    async def get_leaderboard(self, guild_id: str, limit: int = 10, 
                              channel_id: Optional[str] = None) -> List[Dict]:
        """
        Get the reputation leaderboard.
        
        Args:
            guild_id: The ID of the guild
            limit: Maximum number of entries to return
            channel_id: Optional channel ID for channel-specific leaderboard
            
        Returns:
            List[Dict]: Leaderboard entries
        """
        try:
            if channel_id:
                # Channel-specific leaderboard
                channel_doc_id = f"{guild_id}_{channel_id}"
                channel_doc = self.channels_collection.document(channel_doc_id).get()
                
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
                query = (self.reps_collection
                         .where('guild_id', '==', guild_id)
                         .order_by('count', direction=firestore.Query.DESCENDING)
                         .limit(limit))
                
                docs = query.stream()
                
                return [doc.to_dict() for doc in docs]
                
        except Exception as e:
            logger.error(f"Error getting leaderboard: {e}")
            return []
    
    async def get_channel_leaderboard(self, guild_id: str, limit: int = 5) -> List[Dict]:
        """
        Get the leaderboard of channels with most reputation points.
        
        Args:
            guild_id: The ID of the guild
            limit: Maximum number of entries to return
            
        Returns:
            List[Dict]: Channel leaderboard entries
        """
        try:
            query = (self.channels_collection
                     .where('guild_id', '==', guild_id)
                     .order_by('total_reps', direction=firestore.Query.DESCENDING)
                     .limit(limit))
            
            docs = query.stream()
            
            return [doc.to_dict() for doc in docs]
            
        except Exception as e:
            logger.error(f"Error getting channel leaderboard: {e}")
            return []