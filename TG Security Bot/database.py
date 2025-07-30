import asyncio
import logging
from supabase import acreate_client, create_client, Client, AClient
from redis import asyncio as aioredis 
import json 
from fastapi import FastAPI 
from app.core.config import settings 
from datetime import datetime, timezone

# Configure logging
logging.basicConfig(level=settings.NEOGUARD_LOG_LEVEL)
logger = logging.getLogger(__name__)

supabase: Client = create_client(
    settings.NEOGUARD_SUPABASE_URL, 
    settings.NEOGUARD_SUPABASE_KEY
)

redis_client = aioredis.Redis(
    host=settings.NEOGUARD_REDIS_HOST, 
    port=settings.NEOGUARD_REDIS_PORT, 
    db=settings.NEOGUARD_REDIS_DB
)

async def fetch_paginated_data(table: str, select_query: str, page_size: int = 1000):
    """
    Generic function to fetch paginated data from Supabase
    """
    all_records = []
    current_offset = 0

    while True:
        try:
            result = supabase.table(table)\
                .select(select_query)\
                .range(current_offset, current_offset + page_size - 1)\
                .execute()
            
            if not result.data:
                break
                
            all_records.extend(result.data)
            
            if len(result.data) < page_size:
                break
                
            current_offset += page_size
            
        except Exception as e:
            logger.error(f"Error fetching data from {table}: {str(e)}")
            raise

    return all_records

# on startup, hydrate redis caches
async def fetch_and_cache_verified_tg_groups():
    logger.info("Starting fetch_and_cache_verified_tg_groups")

    try:
        # Check and clear existing cache if needed
        key_type = await redis_client.type('verified_tg_groups')
        if key_type != b'hash':
            await redis_client.delete('verified_tg_groups')

        # Fetch all records with pagination
        all_records = await fetch_paginated_data(
            'neoguard_users',
            'id, telegram_chat_id, address, name, telegram, discord, twitter, project_type, ticker, is_eligible'
        )

        # Process and store the data
        for group in all_records:
            # Only process if is_eligible is True
            if not group.get('is_eligible', False):
                continue
                
            # Store main mapping only if telegram_chat_id exists
            telegram_chat_id = group.get('telegram_chat_id')
            if telegram_chat_id:
                await redis_client.hset('verified_tg_groups', str(group['id']), str(telegram_chat_id))
            
            # Store detailed project info with null handling
            project_details = {
                'address': str(group.get('address', '')) if group.get('address') is not None else '',
                'name': str(group.get('name', '')) if group.get('name') is not None else '',
                'telegram': str(group.get('telegram', '')) if group.get('telegram') is not None else '',
                'discord': str(group.get('discord', '')) if group.get('discord') is not None else '',
                'twitter': str(group.get('twitter', '')) if group.get('twitter') is not None else '',
                'project_type': str(group.get('project_type', '')) if group.get('project_type') is not None else '',
                'ticker': str(group.get('ticker', '')) if group.get('ticker') is not None else '',
                'telegram_chat_id': str(telegram_chat_id) if telegram_chat_id is not None else ''
            }

            # Only store if we have valid data
            if any(project_details.values()):
                await redis_client.hset(f'project_details:{group["id"]}', mapping=project_details)

        logger.info(f"Cached {len(all_records)} verified TG groups in Redis")

    except Exception as e:
        logger.error(f"Error in fetch_and_cache_verified_tg_groups: {str(e)}")
        raise

async def fetch_and_cache_verified_tg_members():
    logger.info("Starting fetch_and_cache_verified_tg_members")

    try:
        # Check and clear existing cache if needed
        key_type = await redis_client.type('verified_tg_members')
        if key_type != b'hash':
            await redis_client.delete('verified_tg_members')

        # Fetch all records with pagination
        all_records = await fetch_paginated_data(
            'team',
            'id, telegram_chat_id, telegram_id, telegram_full_name, telegram_username'
        )

        # Process and store the data
        for member in all_records:
            # Only store if we have the required fields
            if member.get('id') is not None:
                member_data = json.dumps({
                    'telegram_chat_id': str(member.get('telegram_chat_id', '')) if member.get('telegram_chat_id') is not None else '',
                    'telegram_id': str(member.get('telegram_id', '')) if member.get('telegram_id') is not None else '',
                    'telegram_full_name': str(member.get('telegram_full_name', '')) if member.get('telegram_full_name') is not None else '',
                    'telegram_username': str(member.get('telegram_username', '')) if member.get('telegram_username') is not None else ''
                })
                await redis_client.hset('verified_tg_members', str(member['id']), member_data)

        logger.info(f"Cached {len(all_records)} verified TG members in Redis")

    except Exception as e:
        logger.error(f"Error in fetch_and_cache_verified_tg_members: {str(e)}")
        raise

async def fetch_and_cache_blacklisted_tg_users():
    logger.info("Starting fetch_and_cache_blacklisted_tg_users")

    try:
        # Check and clear existing cache if needed
        key_type = await redis_client.type('blacklisted_tg_users')
        if key_type != b'hash':
            await redis_client.delete('blacklisted_tg_users')

        # Fetch all records with pagination
        all_records = await fetch_paginated_data(
            'blacklisted_tg_users',
            'id, user_id'
        )

        # Process and store the data
        blacklisted_users_dict = {}
        for user in all_records:
            if user.get('id') is not None and user.get('user_id') is not None:
                blacklisted_users_dict[str(user['id'])] = str(user['user_id'])

        if blacklisted_users_dict:
            await redis_client.hset('blacklisted_tg_users', mapping=blacklisted_users_dict)

        logger.info(f"Cached {len(blacklisted_users_dict)} blacklisted TG users in Redis")

    except Exception as e:
        logger.error(f"Error in fetch_and_cache_blacklisted_tg_users: {str(e)}")
        raise

async def fetch_and_cache_exceptions():
    logger.info("Starting fetch_and_cache_exceptions")

    try:
        # Clear existing cache
        await redis_client.delete('chat_exceptions')

        # Fetch all records with pagination
        all_records = await fetch_paginated_data(
            'athena_secure_tg_exceptions',
            'id, chat_id, user_id'
        )

        # Process and store the data
        for exception in all_records:
            if exception.get('id') is not None:
                exception_data = json.dumps({
                    'chat_id': str(exception.get('chat_id', '')),
                    'user_id': str(exception.get('user_id', ''))
                })
                await redis_client.hset('chat_exceptions', str(exception['id']), exception_data)

        logger.info(f"Cached {len(all_records)} exceptions in Redis")

    except Exception as e:
        logger.error(f"Error in fetch_and_cache_exceptions: {str(e)}")
        raise

async def fetch_and_cache_settings():
    logger.info("Starting fetch_and_cache_settings")

    try:
        # Clear existing cache
        await redis_client.delete('chat_settings')

        # First, get the mapping of settings_id to telegram_chat_id
        chat_settings_map = await fetch_paginated_data(
            'verified_projects_accounts',
            'settings_id, telegram_chat_id'
        )

        # Create a mapping of settings_id to telegram_chat_id
        settings_to_chat = {
            str(record['settings_id']): str(record['telegram_chat_id'])
            for record in chat_settings_map
            if record.get('settings_id') and record.get('telegram_chat_id')
        }

        # Fetch all settings
        all_settings = await fetch_paginated_data(
            'athena_secure_settings',
            'id, use_global_blacklist, use_spam_detection, use_file_scanner, use_url_scanner, use_member_monitor'
        )

        # Prepare settings for each chat
        for setting in all_settings:
            settings_id = str(setting.get('id'))
            chat_id = settings_to_chat.get(settings_id)
            
            if chat_id:
                settings_data = {
                    'use_global_blacklist': bool(setting.get('use_global_blacklist')),
                    'use_spam_detection': bool(setting.get('use_spam_detection')),
                    'use_file_scanner': bool(setting.get('use_file_scanner')),
                    'use_url_scanner': bool(setting.get('use_url_scanner')),
                    'use_member_monitor': bool(setting.get('use_member_monitor'))
                }
                await redis_client.hset('chat_settings', chat_id, json.dumps(settings_data))

        logger.info(f"Cached settings for {len(settings_to_chat)} chats in Redis")

    except Exception as e:
        logger.error(f"Error in fetch_and_cache_settings: {str(e)}")
        raise

# functions to update redis caches
async def update_verified_tg_groups(data):
    logger.info(f"Updating verified TG groups cache for: {data}")

    record = data.get('record', {})
    event_type = data.get('type')
    old_record = data.get('old_record', {})

    record_id = record.get('id') or old_record.get('id')
    telegram_chat_id = record.get('telegram_chat_id')
    is_eligible = record.get('is_eligible', False)

    if not record_id:
        logger.warning(f"Invalid payload for verified TG groups: {data}")
        return

    try:
        if event_type == 'INSERT' or event_type == 'UPDATE':
            # Only add/update if is_eligible is True
            if is_eligible and telegram_chat_id:
                await redis_client.hset('verified_tg_groups', str(record_id), str(telegram_chat_id))
                logger.info(f"{'Added' if event_type == 'INSERT' else 'Updated'} group {telegram_chat_id} (record {record_id}) to verified TG groups cache")

                # Update project details
                project_details = {
                    'address': str(record.get('address', '')) if record.get('address') is not None else '',
                    'name': str(record.get('name', '')) if record.get('name') is not None else '',
                    'telegram': str(record.get('telegram', '')) if record.get('telegram') is not None else '',
                    'discord': str(record.get('discord', '')) if record.get('discord') is not None else '',
                    'twitter': str(record.get('twitter', '')) if record.get('twitter') is not None else '',
                    'project_type': str(record.get('project_type', '')) if record.get('project_type') is not None else '',
                    'ticker': str(record.get('ticker', '')) if record.get('ticker') is not None else '',
                    'telegram_chat_id': str(telegram_chat_id) if telegram_chat_id is not None else ''
                }
                
                if any(project_details.values()):
                    await redis_client.hset(f'project_details:{record_id}', mapping=project_details)
                    logger.info(f"Updated project details for record {record_id}")
            else:
                # If not eligible or no telegram_chat_id, remove from cache
                await redis_client.hdel('verified_tg_groups', str(record_id))
                await redis_client.delete(f'project_details:{record_id}')
                logger.info(f"Removed record {record_id} from cache (not eligible or no telegram_chat_id)")

        elif event_type == 'DELETE':
            # Remove from both caches
            await redis_client.hdel('verified_tg_groups', str(record_id))
            await redis_client.delete(f'project_details:{record_id}')
            logger.info(f"Removed record {record_id} from verified TG groups cache and project details")

    except Exception as e:
        logger.error(f"Error updating verified TG groups cache: {str(e)}")
        raise

    logger.info("Updated verified TG groups cache")

async def update_verified_tg_members(data):
    logger.info(f"Updating verified TG members cache for: {data}")

    record = data.get('record', {})
    event_type = data.get('type')
    old_record = data.get('old_record', {})

    record_id = record.get('id') or old_record.get('id')
    
    if not record_id:
        logger.warning(f"Invalid payload for verified TG members: {data}")
        return

    if event_type == 'INSERT' or event_type == 'UPDATE':
        member_data = json.dumps({
            'telegram_chat_id': str(record.get('telegram_chat_id', '')) if record.get('telegram_chat_id') is not None else '',
            'telegram_id': str(record.get('telegram_id', '')) if record.get('telegram_id') is not None else '',
            'telegram_full_name': str(record.get('telegram_full_name', '')) if record.get('telegram_full_name') is not None else '',
            'telegram_username': str(record.get('telegram_username', '')) if record.get('telegram_username') is not None else ''
        })
        await redis_client.hset('verified_tg_members', str(record_id), member_data)
        logger.info(f"{'Added' if event_type == 'INSERT' else 'Updated'} member (record {record_id}) in verified TG members cache")

    elif event_type == 'DELETE':
        await redis_client.hdel('verified_tg_members', str(record_id))
        logger.info(f"Removed record {record_id} from verified TG members cache")

async def update_blacklisted_tg_users(data):
    logger.info(f"Updating blacklisted TG users cache for: {data}")
    
    record = data.get('record', {})
    event_type = data.get('type')
    old_record = data.get('old_record', {})

    record_id = record.get('id') or old_record.get('id')
    user_id = record.get('user_id')

    if not record_id:
        logger.warning(f"Invalid payload for blacklisted TG users: {data}")
        return

    try:
        if event_type == 'INSERT':
            if user_id is not None:
                await redis_client.hset('blacklisted_tg_users', str(record_id), str(user_id))
                logger.info(f"Added user {user_id} (record {record_id}) to blacklisted TG users cache")
        elif event_type == 'DELETE':
            await redis_client.hdel('blacklisted_tg_users', str(record_id))
            logger.info(f"Removed record {record_id} from blacklisted TG users cache")
        elif event_type == 'UPDATE':
            if user_id is not None:
                await redis_client.hset('blacklisted_tg_users', str(record_id), str(user_id))
                logger.info(f"Updated user {user_id} (record {record_id}) in blacklisted TG users cache")
    except Exception as e:
        logger.error(f"Error updating blacklisted TG users cache: {str(e)}")
        raise

async def update_chat_exceptions(data):
    logger.info(f"Updating chat exceptions cache for: {data}")

    record = data.get('record', {})
    event_type = data.get('type')
    old_record = data.get('old_record', {})

    record_id = record.get('id') or old_record.get('id')

    if not record_id:
        logger.warning(f"Invalid payload for chat exceptions: {data}")
        return

    try:
        if event_type == 'INSERT' or event_type == 'UPDATE':
            exception_data = json.dumps({
                'chat_id': str(record.get('chat_id', '')),
                'user_id': str(record.get('user_id', ''))
            })
            await redis_client.hset('chat_exceptions', str(record_id), exception_data)
            logger.info(f"{'Added' if event_type == 'INSERT' else 'Updated'} exception (record {record_id})")

        elif event_type == 'DELETE':
            await redis_client.hdel('chat_exceptions', str(record_id))
            logger.info(f"Removed exception record {record_id}")

    except Exception as e:
        logger.error(f"Error updating chat exceptions cache: {str(e)}")
        raise

async def update_chat_settings(data):
    logger.info(f"Updating chat settings cache for: {data}")

    record = data.get('record', {})
    event_type = data.get('type')
    settings_id = str(record.get('id'))

    try:
        # First get the chat_id for this settings_id
        result = supabase.table('verified_projects_accounts')\
            .select('telegram_chat_id')\
            .eq('settings_id', settings_id)\
            .execute()
        
        if not result.data:
            logger.warning(f"No chat_id found for settings_id {settings_id}")
            return

        chat_id = str(result.data[0]['telegram_chat_id'])

        if event_type in ['INSERT', 'UPDATE']:
            settings_data = {
                'use_global_blacklist': bool(record.get('use_global_blacklist')),
                'use_spam_detection': bool(record.get('use_spam_detection')),
                'use_file_scanner': bool(record.get('use_file_scanner')),
                'use_url_scanner': bool(record.get('use_url_scanner')),
                'use_member_monitor': bool(record.get('use_member_monitor'))
            }
            await redis_client.hset('chat_settings', chat_id, json.dumps(settings_data))
            logger.info(f"Updated settings for chat {chat_id}")

        elif event_type == 'DELETE':
            await redis_client.hdel('chat_settings', chat_id)
            logger.info(f"Removed settings for chat {chat_id}")

    except Exception as e:
        logger.error(f"Error updating chat settings cache: {str(e)}")
        raise

async def is_group_verified(group_id: int) -> bool:
    """
    Verify if the telegram group id is in the verified projects table
    """
    verified_tg_groups = await redis_client.hgetall('verified_tg_groups')
    decoded_groups = {k.decode(): v.decode() for k, v in verified_tg_groups.items()}
    logger.info(decoded_groups)

    return str(group_id) in decoded_groups.values()

# TODO - seems a bit inefficient
async def get_verified_members(group_id: int) -> list:
    all_verified_members = await redis_client.hgetall('verified_tg_members')
    group_members = []
    for record_id, member_data in all_verified_members.items():
        member = json.loads(member_data.decode())  # Decode the byte string
        if member['telegram_chat_id'] == str(group_id):
            group_members.append(member)

    return group_members

async def is_user_verified(user_id: int, verified_members: list) -> bool:
    """
    Check if user is verified
    """
    return any(member['telegram_id'] == str(user_id) for member in verified_members)

async def is_user_blacklisted(user_id: int) -> bool:
    """
    Check redis queue to see if user is in the blacklist
    """
    blacklisted_users = await redis_client.hvals('blacklisted_tg_users')
    return str(user_id) in (user.decode() for user in blacklisted_users)

async def add_blacklisted_user(user_id: int, reason: str):
    """
    Add a banned user to the global blacklist.
    """
    logger.info(f"Adding user {user_id} to the global blacklist with reason: {reason}")
    response = supabase.table('blacklisted_tg_users').insert({"user_id": str(user_id), "reason": reason}).execute()

    if response.data:
        record_id = response.data[0]['id']
        # Update Redis cache
        await redis_client.hset('blacklisted_tg_users', record_id, str(user_id))
        logger.info(f"Updated blacklisted users cache. Added user {user_id} with record ID {record_id}")
    else:
        logger.error(f"Failed to add user {user_id} to the blacklist in the database")

async def update_verified_group_id(old_group_id: int, new_group_id: int):
    """
    Update group id when it converts to a supergroup
    """
    logger.info(f"Updating group id {old_group_id} to new supergroup id {new_group_id}")
    response_projects = supabase.table('verified_projects').update({
        'telegram_chat_id': str(new_group_id)
    }).eq('telegram_chat_id', str(old_group_id)).execute()

    if response_projects.status_code == 200:
        logger.info(f"Updated telegram_chat_id in verified_projects from {str(old_group_id)} to {str(new_group_id)}")
    else:
        logger.error(f"Failed to update verified_projects: {response_projects.error_message}")

    # TODO: update the redis cache? Currently the real time listener will update

    # update team table
    response_team = supabase.table('team').update({
        'telegram_chat_id': str(new_group_id)
    }).eq('telegram_chat_id', str(old_group_id)).execute()

    if response_team.status_code == 200:
        logger.info(f"Updated telegram_chat_id in team from {str(old_group_id)} to {str(new_group_id)}")
    else:
        logger.error(f"Failed to update team: {response_team.error_message}")

async def upsert_admin(admin_details):
    """
    Upsert an admin in Supabase. The real-time listener will handle updating Redis.
    """
    chat_id = admin_details['telegram_chat_id']
    user_id = admin_details['telegram_id']

    # Fetch project_id from Supabase
    project_result = supabase.table('verified_projects') \
        .select('id') \
        .eq('telegram_chat_id', chat_id) \
        .execute()
    
    if not project_result.data:
        logger.error(f"No verified project found in Supabase for chat_id {chat_id}")
        return None

    project_id = project_result.data[0]['id']

    # Add project_id to admin_details
    admin_details['project_id'] = project_id
    
    # Upsert in Supabase
    result = supabase.table('team').upsert(
        admin_details, 
        on_conflict='telegram_chat_id,telegram_id'
    ).execute()
    
    if result.data:
        logger.info(f"Upserted admin {user_id} for chat {chat_id}")
    else:
        logger.error(f"Failed to upsert admin {user_id} for chat {chat_id}")

    return result.data[0] if result.data else None

async def remove_outdated_admins(chat_id: str, current_admin_ids: set):
    try:
        # Fetch all admins for this chat from the database
        result = supabase.table('team').select('id', 'telegram_id', 'telegram_full_name').eq('telegram_chat_id', chat_id).execute()
        
        removed_admins = []
        for admin in result.data:
            if admin['telegram_id'] not in current_admin_ids:
                # Remove this admin from the database
                supabase.table('team').delete().eq('id', admin['id']).execute()
                removed_admins.append(admin['telegram_full_name'])
                logger.info(f"Removed outdated admin: {admin['telegram_full_name']} (ID: {admin['telegram_id']}) from chat {chat_id}")

        return removed_admins

    except Exception as e:
        logger.error(f"Error removing outdated admins: {str(e)}")
        return []

async def remove_admin(chat_id: str, user_id: str):
    try:
        result = supabase.table('team').delete().eq('telegram_chat_id', chat_id).eq('telegram_id', user_id).execute()
        if result.data:
            logger.info(f"Removed admin with user ID {user_id} from chat {chat_id}")
        else:
            logger.warning(f"No admin found to remove with user ID {user_id} in chat {chat_id}")
    except Exception as e:
        logger.error(f"Error removing admin: {str(e)}")

async def get_project_details(telegram_chat_id: int) -> dict:
    """
    Get project details from Redis cache using telegram_chat_id.
    This function is separate from get_project_info which is used for specific bot commands.
    """
    try:
        # First get the project_id from verified_tg_groups
        verified_tg_groups = await redis_client.hgetall('verified_tg_groups')
        project_id = None
        
        # Find the project_id that matches the telegram_chat_id
        for pid, chat_id in verified_tg_groups.items():
            if str(telegram_chat_id) == chat_id.decode():
                project_id = pid.decode()
                break
        
        if not project_id:
            logger.debug(f"No project found for telegram_chat_id: {telegram_chat_id}")
            return None
            
        # Get the project details from Redis using project_id
        project_data = await redis_client.hgetall(f'project_details:{project_id}')
        if project_data:
            return {k.decode(): v.decode() for k, v in project_data.items()}
            
        logger.debug(f"No project details found for project_id: {project_id}")
        return None
        
    except Exception as e:
        logger.error(f"Error getting project details for telegram_chat_id {telegram_chat_id}: {str(e)}")
        return None

async def get_project_info(blockchain: str, contract_address: str):
    try:
        result = supabase.table('verified_projects').select(
            'id',
            'name',
            'blockchain',
            'address',
            'twitter',
            'telegram'
        ).eq('blockchain', blockchain).eq('address', contract_address).execute()

        if result.data:
            project = result.data[0]
            
            # Fetch admin information
            admins = supabase.table('team').select(
                'telegram_full_name',
                'telegram_username'
            ).eq('project_id', project['id']).execute()

            project['admins'] = admins.data
            return project
        else:
            return None
    except Exception as e:
        logger.error(f"Error fetching project info: {str(e)}")
        return None

async def get_chat_exceptions(chat_id: str) -> list:
    """
    Get all exceptions for a specific chat
    """
    try:
        all_exceptions = await redis_client.hgetall('chat_exceptions')
        chat_exceptions = []
        
        for _, exception_data in all_exceptions.items():
            exception = json.loads(exception_data.decode())
            if exception['chat_id'] == chat_id:
                chat_exceptions.append({
                    'user_id': exception['user_id']
                })
                
        return chat_exceptions
    except Exception as e:
        logger.error(f"Error getting chat exceptions: {str(e)}")
        return []
    
async def get_chat_settings(chat_id: str) -> dict:
    """
    Get settings for a specific chat. Returns default values if no settings found.
    """
    DEFAULT_SETTINGS = {
        'use_global_blacklist': True,
        'use_spam_detection': True,
        'use_file_scanner': False,
        'use_url_scanner': False,
        'use_member_monitor': True
    }

    try:
        settings_data = await redis_client.hget('chat_settings', str(chat_id))
        if settings_data:
            return json.loads(settings_data.decode())
        return DEFAULT_SETTINGS
    except Exception as e:
        logger.error(f"Error getting chat settings: {str(e)}")
        return DEFAULT_SETTINGS

async def check_twitter_handle(username: str):
    try:
        # Normalize the username (remove @ if present)
        normalized_username = username.lstrip('@')
        
        # Construct the possible Twitter URLs
        twitter_urls = [
            f"https://twitter.com/{normalized_username}",
            f"https://x.com/{normalized_username}"
        ]
        
        # Query the database for an exact match
        result = supabase.table('verified_projects').select(
            'name',
            'twitter',
            'blockchain'
        ).in_('twitter', twitter_urls).execute()

        logger.info(f"Supabase query result: {result}")  # For debugging

        if result.data:
            return result.data[0]
        else:
            return None
    except Exception as e:
        logger.error(f"Error checking Twitter handle: {str(e)}")
        return None

# New logging functions
async def log_to_database(log_type: str, user_id: int, chat_id: int, content: str, additional_data: dict = None):
    log_entry = {
        'log_type': log_type,
        'user_id': str(user_id) if user_id else None,
        'chat_id': str(chat_id) if chat_id else None,
        'content': content
    }
    
    response = supabase.table('athena_secure_tg_logs').insert(log_entry).execute()
    log_id = response.data[0]['id']

    if additional_data:
        if log_type == 'message':
            await _insert_message_log(log_id, additional_data)
        elif log_type in ['moderation', 'ban', 'kick', 'mute']:
            await _insert_moderation_log(log_id, additional_data)
        elif log_type == 'error':
            await _insert_error_log(log_id, additional_data)

    return log_id

async def _insert_message_log(log_id: str, data: dict):
    message_log = {
        'log_id': log_id,
        'message_text': data.get('message_text'),
        'message_type': data.get('message_type')
    }
    supabase.table('athena_secure_tg_message_logs').insert(message_log).execute()

async def _insert_moderation_log(log_id: str, data: dict):
    moderation_log = {
        'log_id': log_id,
        'action_type': data.get('action_type'),
        'reason': data.get('reason')
    }
    supabase.table('athena_secure_tg_moderation_logs').insert(moderation_log).execute()

async def _insert_error_log(log_id: str, data: dict):
    error_log = {
        'log_id': log_id,
        'error_type': data.get('error_type'),
        'stack_trace': data.get('stack_trace')
    }
    supabase.table('athena_secure_tg_error_logs').insert(error_log).execute()

async def setup_realtime_listeners():
    """
    real time listeners for supabase
    """
    logger.info("Setting up real time listeners")
    try:
        supabase_async: AClient = await acreate_client(settings.NEOGUARD_SUPABASE_URL, settings.NEOGUARD_SUPABASE_KEY)
        await supabase_async.realtime.connect()
    except Exception as e:
        logger.error(f"Error creating supabase client: {str(e)}")
        raise
    
    # Existing channels
    neoguard_users_channel = supabase_async.channel('neoguard_users_changes')
    team_channel = supabase_async.channel('team_changes')
    blacklisted_users_channel = supabase_async.channel('blacklisted_users_changes')
    
    # New channels
    exceptions_channel = supabase_async.channel('exceptions_changes')
    settings_channel = supabase_async.channel('settings_changes')

    async def handle_table_changes(payload):
        logger.info(payload)
        try:
            data = payload.get('data', {})
            table = data.get('table')
            
            if not table:
                logger.error(f"Unable to determine table from payload: {payload}")
                return
            
            handlers = {
                'neoguard_users': update_verified_tg_groups,
                'team': update_verified_tg_members,
                'blacklisted_tg_users': update_blacklisted_tg_users,
                'athena_secure_tg_exceptions': update_chat_exceptions,
                'athena_secure_settings': update_chat_settings
            }
            
            handler = handlers.get(table)
            if handler:
                await handler(data)
                
        except Exception as e:
            logger.error(f"Error processing payload: {e}")
            logger.error(f"Payload: {payload}")

    def callback_wrapper(payload):
        asyncio.create_task(handle_table_changes(payload))

    # Set up listeners for all channels
    neoguard_users_channel.on_postgres_changes(
        event='*',
        schema='public',
        table='neoguard_users',
        callback=callback_wrapper
    )
    team_channel.on_postgres_changes(
        event='*',
        schema='public',
        table='team',
        callback=callback_wrapper
    )
    blacklisted_users_channel.on_postgres_changes(
        event='*',
        schema='public',
        table='blacklisted_tg_users',
        callback=callback_wrapper
    )
    exceptions_channel.on_postgres_changes(
        event='*',
        schema='public',
        table='athena_secure_tg_exceptions',
        callback=callback_wrapper
    )
    settings_channel.on_postgres_changes(
        event='*',
        schema='public',
        table='athena_secure_settings',
        callback=callback_wrapper
    )

    await neoguard_users_channel.subscribe()
    await team_channel.subscribe()
    await blacklisted_users_channel.subscribe()
    await exceptions_channel.subscribe()
    await settings_channel.subscribe()

    logger.info("Realtime listeners set up and subscribed")

    return supabase_async.realtime

async def run_realtime_listeners():
    realtime = None
    
    while True:
        try:
            # Close previous connection if it exists
            if realtime:
                try:
                    await realtime.remove_all_channels()
                    logger.info("Removed all channels from previous realtime connection")
                except AttributeError as ae:
                    logger.warning(f"AttributeError during cleanup (likely auth timer issue): {ae}")
                except Exception as e:
                    logger.warning(f"Error cleaning up previous realtime connection: {e}")
                finally:
                    realtime = None
                    
            realtime = await setup_realtime_listeners()
            listen_task = asyncio.create_task(realtime.listen())

            # Keep the connection alive
            while True:
                if listen_task.done():
                    if listen_task.exception():
                        raise listen_task.exception()
                    break
                await asyncio.sleep(1)

        except Exception as e:
            logger.error(f"Error in real-time listeners: {str(e)}")
            
            # Clean up on error
            if realtime:
                try:
                    await realtime.remove_all_channels()
                except AttributeError as ae:
                    logger.warning(f"AttributeError during error cleanup (likely auth timer issue): {ae}")
                except Exception as cleanup_error:
                    logger.warning(f"Error during error cleanup: {cleanup_error}")
                finally:
                    realtime = None
            
            await asyncio.sleep(5)