import asyncio
import json
import time
from datetime import datetime, timedelta
from telegram import Bot, Chat, ChatPermissions, ChatMember, ChatMemberAdministrator, ChatMemberRestricted
from telegram.error import TelegramError, RetryAfter
from app.telegram.utils import ban_user, check_impersonation
from app.services.database import redis_client, get_verified_members, is_user_verified, log_to_database
from datetime import datetime, timedelta, timezone
import logging

# Configure logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

class BackgroundRateLimit:
    def __init__(self, max_calls_per_second=12):
        self.max_calls = max_calls_per_second
        self.calls = 0
        self.last_reset = time.time()

    async def check_rate_limit(self):
        current_time = time.time()
        
        # Reset counter if a second has passed
        if current_time - self.last_reset >= 1:
            self.calls = 0
            self.last_reset = current_time
            
        # If we've hit our limit, wait until next second
        if self.calls >= self.max_calls:
            sleep_time = 1 - (current_time - self.last_reset)
            if sleep_time > 0:
                await asyncio.sleep(sleep_time)
                self.calls = 0
                self.last_reset = time.time()
                
        self.calls += 1

# Create single instance for background tasks
background_limiter = BackgroundRateLimit(12)

async def continuous_member_check(bot: Bot, clear_on_start=False):
    logger.info("Starting continuous member check")

    if clear_on_start:
        logger.info("Clearing all member data on startup")
        await clear_member_data()

    while True:
        chat_keys = await redis_client.keys('new_members:*')
        logger.info(f"Found {len(chat_keys)} chats with members in queue")
        for chat_key in chat_keys:
            chat_id = chat_key.decode('utf-8').split(':')[1]
            logger.info(f"Processing members for chat: {chat_id}")
            try:
                await background_limiter.check_rate_limit()
                chat = await bot.get_chat(chat_id)
                await process_chat_members(bot, chat)
            except TelegramError as e:
                logger.error(f"Unable to fetch chat {chat_id}: {e}")
                await redis_client.delete(chat_key)
                unique_keys = await redis_client.keys(f'{chat_id}:*')
                if unique_keys:
                    await redis_client.delete(*unique_keys)
                logger.info(f"Cleared all data for chat {chat_id}")
        
        logger.info("Finished processing all chats, sleeping for 30 second")
        await asyncio.sleep(30)

async def process_chat_members(bot: Bot, chat: Chat):
    chat_id = str(chat.id)
    current_time = datetime.now().timestamp()
    check_threshold = current_time - 180  # 3 minutes in seconds
    
    key = f'new_members:{chat_id}'

    # Remove members older than 1 day based on added_at
    try:
        members = await redis_client.zrange(key, 0, -1)
        to_remove = []
        
        for member_json in members:
            try:
                member_data = json.loads(member_json)
                if current_time - member_data['added_at'] > (60 * 60 * 24 * 1):  # 1 day
                    to_remove.append(member_json)
                    unique_key = f"{chat_id}:{member_data['user_id']}"
                    await redis_client.delete(unique_key)
                    logger.info(f"Member {member_data['user_id']} removed after 1 day")
            except json.JSONDecodeError:
                to_remove.append(member_json)
                logger.error(f"Invalid JSON: {member_json}")

        if to_remove:
            for item in to_remove:
                await redis_client.zrem(key, item)
            logger.info(f"Removed {len(to_remove)} members from chat {chat_id}")
    except Exception as e:
        logger.error(f"Error removing members from {chat_id}: {e}")

    # Get remaining members
    try:
        members = await redis_client.zrange(key, 0, -1, withscores=True)
        logger.info(f"Found {len(members)} members in queue for chat {chat_id}")
    except Exception as e:
        logger.error(f"Error fetching members from {chat_id}: {e}")
        return

    processed_count = 0
    skipped_count = 0
    failed_count = 0

    for member_json, score in members:
        member_data = json.loads(member_json)
        user_id = member_data.get('user_id')
        last_checked = member_data.get('last_checked', 0)
        
        #logger.info(f"Checking member {member_data['user_id']}. Last checked: {datetime.fromtimestamp(last_checked)}, Current time: {datetime.fromtimestamp(current_time)}")
        
        if last_checked >= check_threshold:
            skipped_count += 1
            # logger.debug(f"Skipping recently checked member {user_id} in {chat_id}")
            continue

        try:
            await process_single_member(bot, chat, member_data)
            processed_count += 1
        except RetryAfter as e:
            logger.warning(f"Rate limited. Waiting for {e.retry_after} seconds.")
            await asyncio.sleep(e.retry_after)
        except TelegramError as e:
            failed_count += 1
            logger.error(f"Failed to process member {user_id} in {chat_id}: {e}")
            
        await asyncio.sleep(0.05)  # Rate limiting

    logger.info(f"Processed {processed_count} members and skipped {skipped_count} members in chat {chat_id}")

    # Clean up duplicates
    try:
        await cleanup_duplicates(chat_id)
    except Exception as e:
        logger.error(f"Error cleaning up duplicates for {chat_id}: {e}")

    # Final count verification
    try:
        final_members = await redis_client.zrange(key, 0, -1)
        logger.info(
            f"Chat {chat_id} summary: "
            f"Processed {processed_count}, "
            f"Skipped {skipped_count}, "
            f"Failed {failed_count}, "
            f"Final queue size {len(final_members)}"
        )
    except Exception as e:
        logger.error(f"Error getting final count for {chat_id}: {e}")

async def process_single_member(bot: Bot, chat: Chat, member_data: dict):
    chat_id = str(chat.id)
    user_id = member_data['user_id']
    logger.info(f"Starting to process member {user_id} in chat {chat_id}")
    key = f'new_members:{chat_id}'
    unique_key = f'{chat_id}:{member_data["user_id"]}'

    async def remove_member():
        # Remove both the sorted set entry and unique key
        member_json = json.dumps(member_data)
        removed = await redis_client.zrem(key, member_json)
        await redis_client.delete(unique_key)
        logger.info(f"Removed member {user_id} from queue: {removed}")
        
        # Verify removal
        if await redis_client.zscore(key, member_json) is not None:
            logger.error(f"Failed to remove member {user_id} from queue!")

    # Check if tracking key exists (7-day expiry key)
    if not await redis_client.exists(unique_key):
        logger.info(f"Member {user_id} tracking key not found, removing from queue")
        await remove_member()
        return
        
    # Check 2-minute expiry based on added_at
    current_time = datetime.now().timestamp()
    if current_time - member_data['added_at'] > (60 * 60 * 24 * 1):
        logger.info(f"Member {user_id} beyond 2-minute window, removing from queue")
        await remove_member()
        return
    
    try:
        # Create new permissions object with toggled can_manage_topics
        new_permissions = ChatPermissions(
            can_send_messages=True,
            can_send_polls=False,
            can_send_other_messages=False,
            can_add_web_page_previews=False,
            can_change_info=False,
            can_invite_users=False,
            can_pin_messages=False,
            can_manage_topics=False
        )

        # Calculate restriction end time (35 seconds from now)
        until_date = datetime.now() + timedelta(seconds=35)

        await background_limiter.check_rate_limit()
        await bot.restrict_chat_member(
            chat_id, 
            member_data['user_id'], 
            permissions=new_permissions,
            until_date=until_date
        )
        #logger.info(f"Toggled off all permissions for member {member_data['user_id']} until {until_date}")

        # Step 2: Fetch updated member info
        try:
            await background_limiter.check_rate_limit()
            member = await chat.get_member(member_data['user_id'])
            
            # Add validation check for member object
            if not isinstance(member, (ChatMember, ChatMemberRestricted, ChatMemberAdministrator)):
                logger.error(f"Unexpected member type received: {type(member)} for user {user_id}")
                await remove_member()
                return

            if member.status in ['left', 'kicked']:
                logger.info(f"Member {user_id} no longer in chat")
                await remove_member()
                return
                
            # logger.info(f"stored name: {member_data['full_name']}")
            # logger.info(f"current name: {member.user.full_name}")

        except TelegramError as e:
            logger.error(f"Failed to fetch member info for {user_id}: {e}")
            await remove_member()
            return
        
        if member.user.full_name != member_data['full_name'] or member.user.username != member_data['username']:
            logger.info(f"Member {member_data['user_id']} info changed, checking for impersonation")
            verified_members = await get_verified_members(chat_id)

            if await is_user_verified(member_data['user_id'], verified_members):
                # TODO: isolate this into its own function since its repeated
                await redis_client.zrem(key, json.dumps(member_data))
                await redis_client.delete(unique_key)
                return

            is_impersonator, is_blacklist = await check_impersonation(member.user.full_name, member.user.username, verified_members, chat.title)
            if is_impersonator:
                logger.warning(f"Member {member_data['user_id']} identified as impersonator, banning")
                await background_limiter.check_rate_limit()
                await ban_user(chat, member.user.id, member.user.full_name, "impersonation of a team member", is_blacklist)
                await log_to_database('moderation', user_id, chat.id, 
                              f"Banned new member {member.user.full_name} for impersonation - Member Monitor", 
                              {'action_type': 'ban', 'reason': 'impersonation_mm'})
                await remove_member()
                return
            else:
                logger.info(f"Updating info for member {member_data['user_id']}")
                member_data['full_name'] = member.user.full_name
                member_data['username'] = member.user.username
        else:
            logger.info(f"No changes detected for member {member_data['user_id']}")

        # Step 3: Always update last_checked
        member_data['last_checked'] = datetime.now().timestamp()
        member_data['permissions'] = get_member_permissions(member).to_dict()
        
        # Update the entry in Redis
        new_json = json.dumps(member_data)
        await redis_client.zadd(key, {new_json: member_data['last_checked']})
        
        logger.info(f"Updated Redis entry for member {member_data['user_id']}")
        
    except TelegramError as e:
        if 'user not found' in str(e).lower():
            logger.info(f"Member {member_data['user_id']} not found in chat, removing from queue")
            await remove_member()
        elif 'member not found' in str(e).lower():
            logger.info(f"Member {member_data['user_id']} not found in chat, removing from queue")
            await remove_member()
        elif 'user is an administrator' in str(e).lower():
            logger.info(f"Member {member_data['user_id']} is an admin, removing from queue")
            await remove_member()
        else:
            logger.error(f"Telegram error processing member {member_data['user_id']}: {e}")
            raise

async def add_member_to_queue(chat_id, user_id, full_name, username):
    key = f'new_members:{chat_id}'
    current_time = datetime.now().timestamp()
    
    member_data = {
        'user_id': user_id,
        'full_name': full_name,
        'username': username,
        'added_at': current_time,
        'last_checked': current_time,
        'permissions': None
    }
    
    # Use user_id as a unique identifier
    unique_key = f'{chat_id}:{user_id}'
    
    # Check if member already exists
    if await redis_client.exists(unique_key):
        logger.info(f"Member {user_id} already in queue for chat {chat_id}")
        return

    # Add to sorted set
    await redis_client.zadd(key, {json.dumps(member_data): current_time})
    # Set a separate key to ensure uniqueness
    await redis_client.set(unique_key, '', ex=7*24*60*60)  # Expires in 7 days
    
    logger.info(f"Added new member to queue: {member_data}")

async def cleanup_duplicates(chat_id: str):
    key = f'new_members:{chat_id}'
    members = await redis_client.zrange(key, 0, -1, withscores=True)
    seen = {}
    duplicates = []
    
    for member_json, score in members:
        member_data = json.loads(member_json)
        user_id = member_data['user_id']
        if user_id in seen:
            # Compare last_checked timestamps, keep the most recent
            if member_data['last_checked'] > seen[user_id]['last_checked']:
                duplicates.append(json.dumps(seen[user_id]))
                seen[user_id] = member_data
            else:
                duplicates.append(member_json)
        else:
            seen[user_id] = member_data
    
    if duplicates:
        logger.warning(f"Found {len(duplicates)} duplicate entries in chat {chat_id}. Removing...")
        for duplicate in duplicates:
            await redis_client.zrem(key, duplicate)
    else:
        logger.info(f"No duplicates found in chat {chat_id}")

def get_member_permissions(member):
    if isinstance(member, ChatMemberRestricted):
        return ChatPermissions(
            can_send_messages=member.can_send_messages,
            can_send_polls=member.can_send_polls,
            can_send_other_messages=member.can_send_other_messages,
            can_add_web_page_previews=member.can_add_web_page_previews,
            can_change_info=member.can_change_info,
            can_invite_users=member.can_invite_users,
            can_pin_messages=member.can_pin_messages,
            can_manage_topics=getattr(member, 'can_manage_topics', False)
        )
    elif isinstance(member, ChatMemberAdministrator):
        # Admins typically have all permissions
        return ChatPermissions(
            can_send_messages=True,
            can_send_polls=True,
            can_send_other_messages=True,
            can_add_web_page_previews=True,
            can_change_info=True,
            can_invite_users=True,
            can_pin_messages=True,
            can_manage_topics=True
        )
    else:
        # Default permissions for other member types
        return ChatPermissions()

async def clear_member_data(chat_id=None):
    if chat_id:
        # Clear specific chat
        sorted_set = f'new_members:{chat_id}'
        unique_keys = await redis_client.keys(f'{chat_id}:*')
        
        if await redis_client.exists(sorted_set):
            await redis_client.delete(sorted_set)
            logger.info(f"Cleared sorted set for chat {chat_id}")
            
        if unique_keys:
            await redis_client.delete(*unique_keys)
            logger.info(f"Cleared {len(unique_keys)} unique keys for chat {chat_id}")
    else:
        # Clear all member-related data
        member_keys = await redis_client.keys('new_members:*')
        unique_keys = await redis_client.keys('*:*')
        
        if member_keys:
            await redis_client.delete(*member_keys)
            logger.info(f"Cleared {len(member_keys)} member queues")
            
        if unique_keys:
            await redis_client.delete(*unique_keys)
            logger.info(f"Cleared {len(unique_keys)} unique keys")