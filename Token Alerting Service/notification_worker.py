import redis
import requests
import json
import os
import time
import threading
import queue
import logging
import asyncio
from supabase import create_client, acreate_client, Client, AClient

import sys
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from config.settings import (
    REDIS_HOST,
    REDIS_PORT,
    SUPABASE_URL,
    SUPABASE_KEY
)

from display_helper_functions import *

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Development mode check
DEV_MODE = os.getenv('DEV_MODE', 'false').lower() == 'true'

# Initialize clients
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
redis_client = redis.StrictRedis(host=REDIS_HOST, port=REDIS_PORT, db=0)

# Environment variables with dev/prod bot tokens
TELEGRAM_BOT_TOKEN = '7201817971:AAHA6vRXEJptxNMe10XghPvxq0Qt2K599sY' if DEV_MODE else os.getenv('TELEGRAM_BOT_TOKEN')

# Queue to hold messages to be sent
message_queue = queue.Queue()

# Lock to synchronize rate limiting
rate_limit_lock = threading.Lock()

# Rate limiting shared variables
messages_sent = 0
rate_limit_start_time = time.time()

chain_id_mapping = {
    "0x1": "Ethereum",
    "0xaa36a7": "Sepolia Testnet"
}

def send_telegram_message(chat_id, message, max_retries=3, base_delay=1):
    """
    Send message to Telegram with retry logic and proper rate limit handling.
    
    Args:
        chat_id: Telegram chat ID to send to
        message: Message to send
        max_retries: Maximum number of retry attempts
        base_delay: Base delay for exponential backoff
    
    Returns:
        bool: True if message was sent successfully, False otherwise
    """
    if DEV_MODE:
                logger.info(f"Attempting to send message to {chat_id}")
                logger.info(f"Message content: {message}")
                logger.info(f"TELEGRAM_BOT_TOKEN: {TELEGRAM_BOT_TOKEN}")

    for attempt in range(max_retries):
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
            payload = {
                'chat_id': chat_id,
                'text': str(message),
                'parse_mode': 'HTML',
                'disable_web_page_preview': True
            }

            if DEV_MODE:
                logger.info(f"Making request to Telegram API (Attempt {attempt + 1}/{max_retries})")
                logger.info(f"Payload: {payload}")
            
            response = requests.post(url, json=payload)
            
            if response.status_code == 429:
                retry_after = response.json().get('parameters', {}).get('retry_after', base_delay)
                logger.warning(f"Rate limited by Telegram. Retrying after {retry_after} seconds. Attempt {attempt + 1}/{max_retries}")
                time.sleep(retry_after)
                continue
                
            if response.status_code != 200:
                error_msg = f"Telegram API error: {response.status_code} - {response.text}"
                return False
            
            if DEV_MODE:
                logger.info(f"Successfully sent message to {chat_id}")
                logger.info(f"Telegram response: {response.json()}")
            return True
            
        except requests.RequestException as e:
            error_msg = f"Request error sending Telegram message: {str(e)}"
            if attempt == max_retries - 1:
                logger.error(error_msg)
                return False
            logger.warning(f"{error_msg}. Attempt {attempt + 1}/{max_retries}")
            time.sleep(base_delay * (2 ** attempt))
            
        except Exception as e:
            logger.error(f"Unexpected error sending Telegram message: {str(e)}")
            return False
    
    return False

def message_producer():
    """
    Fetch messages from Redis and add them to the message queue.
    """
    while True:
        try:
            message_data = redis_client.lpop('notification_queue')
            if message_data:
                message = json.loads(message_data)
                message_queue.put(message)
            else:
                time.sleep(0.1)  # Small sleep to prevent tight loop when queue is empty
        except Exception as e:
            logging.error(f"Error fetching message from Redis: {str(e)}")

def message_consumer():
    """
    Send messages from the queue to all subscribed Telegram chat IDs, 
    adhering to rate limits.
    """
    global messages_sent, rate_limit_start_time
    last_redis_log = time.time()
    LOG_INTERVAL = 300  # Log Redis state every 5 minutes

    while True:
        try:
            # Periodic Redis state logging
            current_time = time.time()
            if current_time - last_redis_log > LOG_INTERVAL:
                log_redis_state()
                last_redis_log = current_time

            message = message_queue.get()

            # Extract data from the message
            message_data = message.get('token_data', {})
            if DEV_MODE:
                logger.info(f"Processing message: {json.dumps(message_data, indent=2)}")

            # Iterate over all user keys
            for user_key in redis_client.scan_iter('user:*'):
                user_data = redis_client.hgetall(user_key)
                if not user_data:
                    continue

                filters = json.loads(user_data.get(b'filters', '{}').decode('utf-8'))
                tg_id = user_data.get(b'telegram_id')
                
                if not tg_id:
                    continue

                if apply_filters(filters, message_data): 
                    with rate_limit_lock:
                        if messages_sent >= 30:
                            elapsed_time = time.time() - rate_limit_start_time
                            if elapsed_time < 1:
                                time.sleep(1 - elapsed_time)
                            messages_sent = 0
                            rate_limit_start_time = time.time()

                    display_preference = filters.get('display_preference', 'standard')
                    display_message = format_message(display_preference, message_data)

                    logging.info(f"Sending message to {tg_id.decode('utf-8')}: {display_message}")

                    send_telegram_message(tg_id.decode('utf-8'), display_message)
                    messages_sent += 1

            message_queue.task_done()

        except Exception as e:
            logging.error(f"Error processing message: {str(e)}")

def initialize_user_cache():
    try:
        page_size = 1000
        start = 0
        total_users = 0
        
        logging.info("Starting to initialize user cache from Supabase...")
        
        while True:
            query = supabase.from_('user_wallets')\
                .select('id, user_information(linked_accounts), user_filters(*), user_subscriptions(subscription_id)')\
                .range(start, start + page_size - 1)\
                .execute()

            if not query.data:
                break

            logging.info(f"Processing batch of {len(query.data)} users starting at index {start}")

            for user in query.data:
                user_id = user.get('id')
                logging.info(f"Processing user: {json.dumps(user, indent=2)}")
                
                # Check subscription status first
                if not user.get('user_subscriptions'):
                    logging.info(f"Skipping user {user_id}: No active subscription found")
                    continue

                # Skip if no user information
                if not user.get('user_information'):
                    logging.info(f"Skipping user {user_id}: No user_information found")
                    continue

                # Extract telegram ID from linked_accounts
                user_info = user['user_information']
                linked_accounts = user_info.get('linked_accounts', [])
                
                if linked_accounts is None:
                    logging.info(f"Skipping user {user_id}: Null linked_accounts")
                    continue

                if not isinstance(linked_accounts, list):
                    linked_accounts = [linked_accounts]

                # Find telegram account if it exists
                telegram_account = next(
                    (acc for acc in linked_accounts if isinstance(acc, dict) and acc.get('provider') == 'telegram'),
                    None
                )

                if not telegram_account:
                    logging.info(f"Skipping user {user_id}: No telegram account found")
                    continue

                # Get filters
                filters = {}
                if user.get('user_filters'):
                    filters = user['user_filters']
                    for field in ['id', 'user_wallet_id', 'created_at', 'updated_at']:
                        filters.pop(field, None)
                    filters = {
                        k: ('' if v is None else v) 
                        for k, v in filters.items() 
                        if k not in ['id', 'user_wallet_id', 'created_at', 'updated_at']
                    }

                # Store user data
                tg_id = telegram_account['provider_id']
                redis_key = f"user:{user_id}"
                user_data = {
                    "filters": json.dumps(filters),
                    "telegram_id": tg_id
                }

                # Store both the user data and the telegram mapping
                redis_client.hmset(redis_key, user_data)
                redis_client.set(f"telegram_map:{tg_id}", user_id)
                
                total_users += 1
                logging.info(f"Stored user {user_id} with telegram ID {tg_id}")

            if len(query.data) < page_size:
                break

            start += page_size
        
        logging.info(f"Cache initialization complete. Total users processed: {total_users}")
        log_redis_state()
        
    except Exception as e:
        logging.error(f"Error initializing user cache: {str(e)}")
        logging.error(f"Traceback:", exc_info=True)
        raise

def check_socials_exist(token_data):
    """
    Check if any of the socials exist, return False is none.
    """
    return any(token_data.get(key) for key in ['twitter', 'telegram', 'discord', 'website'])

def apply_filters(filters, message_data):
    """
    Apply user filters to the message data.
    """
    risk_level_mapping = {
        'Safe': 0,
        'Low': 1,
        'Medium': 2,
        'High': 3
    }

    # Extract filters - Updated to match actual data types
    filter_buy_tax = filters.get('buy_tax')  # Now an integer
    filter_sell_tax = filters.get('sell_tax')  # Now an integer
    filter_risk_level = filters.get('risk_level', '').lower()  # String, lowercase for comparison
    filter_contract_verified = filters.get('contract_verified')  # Now a boolean
    filter_classification = filters.get('classification', '').lower()   
    filter_event_type = filters.get('alert_type', '').lower()
    filter_has_social = filters.get('has_social')  # Now a boolean
    filter_blockchain = filters.get('blockchains', [])  # Now an array
    filter_locked_lp = filters.get('locked_lp')  # integer

    # Extract message data
    message_buy_tax = message_data.get('buy_tax', '')
    message_sell_tax = message_data.get('sell_tax', '')
    message_risk_level = message_data.get('risk_level', '').lower()
    message_contract_verified = message_data.get('contract_verified', False)
    message_classification = message_data.get('classification', '').lower()
    message_event_type = message_data.get('event_type', '').lower()
    message_socials = check_socials_exist(message_data)
    message_blockchain = chain_id_mapping.get(message_data.get('chain_id'))
    message_locked_lp = message_data.get('locked_lp', 0.0)

    # Check blockchain
    if filter_blockchain and message_blockchain and message_blockchain.lower() not in [b.lower() for b in filter_blockchain]:
        return False

    # Check socials - Updated for boolean comparison
    if filter_has_social is True and not message_socials:
        return False

    # Check event type - Updated for 'all' case
    # TODO - make it multi selection
    if filter_event_type != 'all':
        if filter_event_type == 'new tge' and message_event_type != 'new_token':
            return False
        elif filter_event_type == 'new dex listing' and message_event_type != 'new_pair':
            return False

    # Check locked LP if dex alert, filter is set and event type is not new token
    if message_event_type != 'new_token':
        if filter_locked_lp and filter_event_type != 'new tge':
            try:
                min_locked_percentage = float(filter_locked_lp)
                if message_locked_lp < min_locked_percentage:
                    return False
            except Exception as e:
                logging.error(f"Error parsing LP lock filter: {str(e)}")
                return False

    # Check classification - Updated for 'all' case
    if filter_classification != 'all':
        if filter_classification == 'exclude memecoins':
            if message_classification == 'memecoins':
                return False
        elif filter_classification != message_classification:
            return False

    # Check contract verified - Now using boolean comparison
    if filter_contract_verified is True and not message_contract_verified:
        return False

    # Check risk level - Updated for case-insensitive comparison
    if filter_risk_level:
        message_risk_value = risk_level_mapping.get(message_risk_level.capitalize(), -1)
        filter_risk_value = risk_level_mapping.get(filter_risk_level.capitalize(), -1)
        if message_risk_value > filter_risk_value:
            return False
        
    # Check buy tax
    if filter_buy_tax:  # Check if filter is set (not empty string)
        try:
            filter_buy_tax_value = float(filter_buy_tax)  # Convert integer to float
            if message_buy_tax:
                message_buy_tax_value = float(str(message_buy_tax).replace('%', '').strip())
                if message_buy_tax_value > filter_buy_tax_value:
                    return False
        except Exception as e:
            logging.error(f"Error parsing buy tax filter: {str(e)}")
            return False
        
    # Check sell tax
    if filter_sell_tax:  # Check if filter is set (not empty string)
        try:
            filter_sell_tax_value = float(filter_sell_tax)  # Convert integer to float
            if message_sell_tax:
                message_sell_tax_value = float(str(message_sell_tax).replace('%', '').strip())
                if message_sell_tax_value > filter_sell_tax_value:
                    return False
        except Exception as e:
            logging.error(f"Error parsing sell tax filter: {str(e)}")
            return False

    # If all checks pass
    return True

def log_redis_state():
    """
    Log the current state of the Redis cache
    """
    try:
        logging.info("Current Redis Cache State:")
        
        # Log all user keys
        user_keys = redis_client.keys("user:*")
        telegram_maps = redis_client.keys("telegram_map:*")
        
        logging.info(f"Found {len(user_keys)} users and {len(telegram_maps)} telegram mappings in Redis")
        
        for key in user_keys:
            try:
                # Decode the key from bytes
                decoded_key = key.decode('utf-8')
                user_data = redis_client.hgetall(key)
                if user_data:
                    tg_id = user_data.get(b'telegram_id', b'None').decode('utf-8')
                    filters = json.loads(user_data.get(b'filters', b'{}').decode('utf-8'))
                    logging.info(f"User {decoded_key}:")
                    logging.info(f"  Telegram ID: {tg_id}")
                    logging.info(f"  Filters: {json.dumps(filters, indent=2)}")
            except Exception as e:
                logging.error(f"Error decoding data for key {key}: {str(e)}")

    except Exception as e:
        logging.error(f"Error inspecting Redis cache: {str(e)}")

# Add the new async realtime setup functions
async def setup_realtime_listeners():
    """
    Set up realtime listeners for user_filters and user_information tables
    """
    logger.info("Setting up Supabase realtime listeners...")
    
    try:
        supabase_async: AClient = await acreate_client(
            os.environ.get("SUPABASE_URL"), 
            os.environ.get("SUPABASE_KEY")
        )
        await supabase_async.realtime.connect()
        logger.info("Successfully connected to Supabase realtime")
        
        # Create channels
        user_filters_channel = supabase_async.channel('user_filters_changes')
        user_info_channel = supabase_async.channel('user_info_changes')

        async def handle_user_changes(payload):
            try:
                # Log the incoming change
                data = payload.get('data', {})
                table_name = data.get('table')
                change_type = data.get('type')
                record = data.get('record', {})
                
                if DEV_MODE:
                    logger.info(f"Processing {change_type} event from {table_name} table")
                    logger.info(f"Record data: {json.dumps(record, indent=2)}")
                
                # Get user_id
                user_id = record.get('user_wallet_id') or record.get('id')
                if not user_id:
                    logging.warning("No user_id found in payload")
                    return

                redis_key = f"user:{user_id}"
                
                # Fetch complete user data
                query = supabase.from_('user_wallets')\
                    .select('id, user_information(linked_accounts), user_filters(*), user_subscriptions(subscription_id)')\
                    .eq('id', user_id)\
                    .execute()

                if not query.data:
                    # User was deleted, clean up Redis
                    current_data = redis_client.hgetall(redis_key)
                    if current_data:
                        tg_id = current_data.get(b'telegram_id')
                        if tg_id:
                            redis_client.delete(f"telegram_map:{tg_id.decode('utf-8')}")
                    redis_client.delete(redis_key)
                    logging.info(f"Removed user {user_id} from Redis - User deleted")
                    return

                user = query.data[0]

                # Check subscription status
                if not user.get('user_subscriptions'):
                    current_data = redis_client.hgetall(redis_key)
                    if current_data:
                        tg_id = current_data.get(b'telegram_id')
                        if tg_id:
                            redis_client.delete(f"telegram_map:{tg_id.decode('utf-8')}")
                    redis_client.delete(redis_key)
                    logging.info(f"Removed user {user_id} from Redis - No active subscription")
                    return

                # Check if user has telegram in linked_accounts
                user_info = user.get('user_information')
                if not user_info:
                    logging.info(f"No user_information for user {user_id}")
                    current_data = redis_client.hgetall(redis_key)
                    if current_data:
                        tg_id = current_data.get(b'telegram_id')
                        if tg_id:
                            redis_client.delete(f"telegram_map:{tg_id.decode('utf-8')}")
                    redis_client.delete(redis_key)
                    log_redis_state()
                    return

                # Handle linked_accounts validation
                linked_accounts = user_info.get('linked_accounts', [])
                if linked_accounts is None:
                    logging.info(f"Linked accounts is None for user {user_id}")
                    current_data = redis_client.hgetall(redis_key)
                    if current_data:
                        tg_id = current_data.get(b'telegram_id')
                        if tg_id:
                            redis_client.delete(f"telegram_map:{tg_id.decode('utf-8')}")
                    redis_client.delete(redis_key)
                    log_redis_state()
                    return

                if not isinstance(linked_accounts, list):
                    linked_accounts = [linked_accounts]

                # Find telegram account if it exists
                telegram_account = next(
                    (acc for acc in linked_accounts if isinstance(acc, dict) and acc.get('provider') == 'telegram'),
                    None
                )

                # If no telegram account found, remove from Redis
                if not telegram_account:
                    logging.info(f"No telegram account found for user {user_id}")
                    current_data = redis_client.hgetall(redis_key)
                    if current_data:
                        tg_id = current_data.get(b'telegram_id')
                        if tg_id:
                            redis_client.delete(f"telegram_map:{tg_id.decode('utf-8')}")
                    redis_client.delete(redis_key)
                    log_redis_state()
                    return

                # Get filters
                filters = {}
                if user.get('user_filters'):
                    filters = user['user_filters']
                    for field in ['id', 'user_wallet_id', 'created_at', 'updated_at']:
                        filters.pop(field, None)
                    filters = {
                        k: ('' if v is None else v) 
                        for k, v in filters.items() 
                        if k not in ['id', 'user_wallet_id', 'created_at', 'updated_at']
                    }

                # Update Redis with new data
                tg_id = telegram_account['provider_id']
                user_data = {
                    "filters": json.dumps(filters),
                    "telegram_id": tg_id
                }

                # Store/update the mappings
                redis_client.hmset(redis_key, user_data)
                redis_client.set(f"telegram_map:{tg_id}", user_id)
                
                logging.info(f"Updated user {user_id} with telegram ID {tg_id}")
                log_redis_state()

            except Exception as e:
                logging.error(f"Error handling user changes: {str(e)}")
                logging.error(f"Traceback:", exc_info=True)
                raise

        def callback_wrapper(payload):
            logger.info(f"Received realtime event: {json.dumps(payload, indent=2)}")
            asyncio.create_task(handle_user_changes(payload))

        # Set up listeners for both channels
        user_filters_channel.on_postgres_changes(
            event='*',
            schema='public',
            table='user_filters',
            callback=callback_wrapper
        )
        user_info_channel.on_postgres_changes(
            event='*',
            schema='public',
            table='user_information',
            callback=callback_wrapper
        )

        await user_filters_channel.subscribe()
        await user_info_channel.subscribe()

        logger.info("Successfully subscribed to all channels")

        return supabase_async.realtime

    except Exception as e:
        logger.error(f"Error setting up realtime listeners: {str(e)}")
        logger.error(f"Traceback:", exc_info=True)
        raise

async def run_realtime_listeners():
    while True:
        try:
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
            await asyncio.sleep(5)

def clear_service_redis_cache():
    try:
        user_keys = redis_client.keys("user:*")
        telegram_maps = redis_client.keys("telegram_map:*")
        
        if user_keys:
            redis_client.delete(*user_keys)
        if telegram_maps:
            redis_client.delete(*telegram_maps)
        
        logging.info(f"Cleared {len(user_keys)} user keys and {len(telegram_maps)} telegram mappings from Redis cache")
        
        remaining_keys = redis_client.keys("user:*") + redis_client.keys("telegram_map:*")
        if not remaining_keys:
            logging.info("Redis cache successfully cleared for this service")
        else:
            logging.warning(f"Some keys remain in cache: {remaining_keys}")
            
    except Exception as e:
        logging.error(f"Error clearing Redis cache: {str(e)}")
        logging.error("Traceback:", exc_info=True)

if __name__ == '__main__':
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == '--clear-cache':
        clear_service_redis_cache()
        sys.exit(0)
    
    try:
        # Initialize the user cache
        initialize_user_cache()
        
        # Start the producer thread
        producer_thread = threading.Thread(target=message_producer)
        producer_thread.daemon = True
        producer_thread.start()

        # Start consumer threads
        consumer_threads = []
        for _ in range(3):
            consumer_thread = threading.Thread(target=message_consumer)
            consumer_thread.daemon = True
            consumer_thread.start()
            consumer_threads.append(consumer_thread)

        # Run the async listener in the event loop
        logging.info("Starting realtime listeners...")
        asyncio.run(run_realtime_listeners())

        # These joins will only be reached if the async code exits
        producer_thread.join()
        for consumer_thread in consumer_threads:
            consumer_thread.join()

    except KeyboardInterrupt:
        logging.info("Shutting down gracefully...")
    except Exception as e:
        logging.error(f"Error in main execution: {str(e)}")
        logging.error("Traceback:", exc_info=True)
        raise
