from redis import Redis
import json
import logging
import os
from datetime import datetime
import time
import asyncio
from typing import Dict, Any, Optional
import aiohttp
from web3 import Web3
from supabase import create_client, Client
from postgrest import APIError
from google.cloud import firestore
import pytz

import sys
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from config.settings import (
    REDIS_HOST,
    REDIS_PORT,
    MAX_RETRIES,
    RETRY_DELAY,
    SUPABASE_URL,
    SUPABASE_KEY
)

# Import your existing helper functions
from moralis_helper_functions import *
from data_transform_helper_functions import *
from infura_helper_functions import *
from etherscan_helper_functions import *
from gopluslabs_helper_functions import *
from contract_scraper_functions import *
from ai_classification_functions import *

# Development mode check
DEV_MODE = os.getenv('DEV_MODE', 'false').lower() == 'true'

# Configure logging
logging.basicConfig(
    level=logging.INFO if DEV_MODE else logging.ERROR,
    format='\n%(asctime)s - %(levelname)s:\n%(message)s\n'
)
logger = logging.getLogger(__name__)

logger.setLevel(logging.INFO if DEV_MODE else logging.ERROR)

# Initialize global clients
db = firestore.Client()
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

class TokenProcessor:
    def __init__(self):
        self.redis = Redis(
            host=REDIS_HOST,
            port=REDIS_PORT,
            decode_responses=True
        )

        # Create aiohttp session for concurrent API calls
        self.session = aiohttp.ClientSession()

    async def close(self):
        await self.session.close()

    async def fetch_with_retry(self, api_call, *args, max_retries=3, base_delay=1):
        """Generic retry wrapper for API calls that might hit rate limits"""
        for attempt in range(max_retries):
            try:
                # If the function is not async, run it in a thread
                if not asyncio.iscoroutinefunction(api_call):
                    result = await asyncio.to_thread(api_call, *args)
                else:
                    result = await api_call(*args)
                return result
            except Exception as e:
                if "429" in str(e) and attempt < max_retries - 1:
                    delay = base_delay * (2 ** attempt)
                    logging.warning(f"Rate limit hit, retrying in {delay} seconds...")
                    await asyncio.sleep(delay)
                    continue
                raise

    def handle_failed_event(self, event_data: Dict[str, Any], error: str):
        """Handle failed events by adding to retry queue"""
        retry_count = event_data.get('retry_count', 0) + 1
        event_data['retry_count'] = retry_count
        event_data['last_error'] = str(error)
        event_data['last_retry'] = datetime.utcnow().isoformat()

        if retry_count <= MAX_RETRIES:
            delay = RETRY_DELAY * (2 ** (retry_count - 1))
            retry_at = time.time() + delay
            self.redis.zadd('retry_queue', {json.dumps(event_data): retry_at})
            logger.info(f"Event {event_data.get('event_id')} added to retry queue. Attempt {retry_count}")
        else:
            self.redis.rpush('failed_events', json.dumps(event_data))
            logger.error(f"Event {event_data.get('event_id')} failed after {MAX_RETRIES} retries")

    async def process_new_token(self, event_data: Dict[str, Any]) -> bool:
        """Process new token events"""
        try:
            if DEV_MODE:
                logger.info("Processing New Token Event:")
                logger.info(json.dumps(event_data, indent=2))

            # Initialize token data with basic info
            token_data = {
                'chain_id': event_data['chain_id'],
                'block_number': event_data['block_number'],
                'event_type': 'new_token',
                'event_id': event_data['event_id']
            }
            token_data['blockchain'] = convert_chain_id_to_blockchain(event_data['chain_id'])

            # Initialize Web3
            web3 = initialize_infura_web3_object(token_data['blockchain'])
            address = web3.to_checksum_address(event_data['address'])
            token_data['address'] = address

            # Step 1: Check if it's an ERC-20 and get basic info
            basic_info = await self.fetch_with_retry(get_eth_contract_info, web3, address)
            if not basic_info:
                logger.info(f"Not an ERC-20 token: {address}")
                return True  # Successfully determined it's not a token we want to process
            
            token_data.update(basic_info)

            # Step 2: Get source code first
            try:
                source_code_info = await self.fetch_with_retry(get_contract_source_code, address)
                token_data.update(source_code_info or {})
                
                # If contract is verified, get socials
                if token_data.get('contract_verified') and token_data.get('source_code'):
                    social_results = get_token_socials(token_data['source_code'])
                    token_data.update(social_results)
            except Exception as e:
                logger.error(f"Error getting source code: {e}")
                token_data['contract_verified'] = False

            # Step 3: Now get security info with verified status
            try:
                security_info = await self.fetch_with_retry(
                    get_eth_token_security_info,
                    address,
                    token_data.get('contract_verified', False),
                    'new_token'
                )
                token_data.update(security_info)
            except Exception as e:
                logger.error(f"Error getting security info: {e}")

            # Step 4: Get classification based on name/symbol
            try:
                classification, certainty = get_token_classification(
                    token_data['name'],
                    token_data['symbol']
                )
                token_data['classification'] = classification
                token_data['classification_certainty'] = certainty
            except Exception as e:
                logger.error(f"Error getting classification: {e}")

            # Step 5: Store data concurrently
            firestore_task = asyncio.create_task(
                asyncio.to_thread(increment_firestore_counter, token_data)
            )
            supabase_task = asyncio.create_task(
                asyncio.to_thread(store_new_token_in_supabase, token_data)
            )

            # Wait for storage operations to complete
            firestore_result, supabase_result = await asyncio.gather(
                firestore_task,
                supabase_task,
                return_exceptions=True
            )

            # Check for storage errors
            if isinstance(supabase_result, Exception):
                logger.error(f"Error storing in Supabase: {supabase_result}")
                self.handle_failed_event(event_data, str(supabase_result))
                return False

            if isinstance(firestore_result, Exception):
                logger.error(f"Error incrementing counter: {firestore_result}")
                # Don't fail the whole process for counter error
            
            # Step 6: Queue for notification if not a scam
            if not token_data.get('is_scam'):
                self.redis.rpush('notification_queue', json.dumps({
                    'event_type': 'new_token',
                    'token_data': token_data
                }))

            return True

        except Exception as e:
            logger.error(f"Error processing new token: {str(e)}")
            self.handle_failed_event(event_data, str(e))
            return False

    async def process_new_pair(self, event_data: Dict[str, Any]) -> bool:
        """Process new pair events"""
        try:
            if DEV_MODE:
                logger.info("Processing New Pair Event:")
                logger.info(json.dumps(event_data, indent=2))

            # Initialize token data with basic info
            token_data = {
                'chain_id': event_data['chain_id'],
                'block_number': event_data['block_number'],
                'event_type': 'new_pair',
                'event_id': event_data['event_id'],
                'dex_pair': event_data['pair_address']
            }
            token_data['blockchain'] = convert_chain_id_to_blockchain(event_data['chain_id'])

            # Initialize Web3
            web3 = initialize_infura_web3_object(token_data['blockchain'])
            token_data['address'] = web3.to_checksum_address(event_data['token_address'])

            # Check if token exists in Supabase
            existing_token = supabase.table('tokens')\
                .select('name, symbol, contract_verified, classification, classification_certainty, is_scam, source_code_id, gpl_audit_id, token_information_id')\
                .eq('address', token_data['address'])\
                .eq('blockchain', token_data['blockchain'])\
                .execute()

            if existing_token.data:
                # Token exists, update with new pair info
                existing_data = existing_token.data[0]
                
                # If token is marked as scam, don't process
                if existing_data.get('is_scam'):
                    if DEV_MODE:
                        logger.info(f"Token {token_data['address']} is marked as scam, skipping")
                    return True
                
                # Hydrate token_data with existing info
                token_data.update({
                    'name': existing_data.get('name'),
                    'symbol': existing_data.get('symbol'),
                    'classification': existing_data.get('classification'),
                    'classification_certainty': existing_data.get('classification_certainty'),
                    'contract_verified': existing_data.get('contract_verified')
                })

                # If contract wasn't verified before, check again
                if not existing_data.get('source_code_id'):
                    try:
                        source_code_info = await self.fetch_with_retry(get_contract_source_code, token_data['address'])
                        token_data.update(source_code_info or {})

                        if token_data.get('contract_verified') and token_data.get('source_code'):
                            social_results = get_token_socials(token_data['source_code'])
                            token_data.update(social_results)
                    except Exception as e:
                        logger.error(f"Error getting source code: {e}")
                        token_data['contract_verified'] = False

                # Get fresh security audit
                try:
                    security_info = await self.fetch_with_retry(
                        get_eth_token_security_info,
                        token_data['address'],
                        token_data.get('contract_verified', False),
                        'new_pair'
                    )
                    token_data.update(security_info or {})

                    # Check for ownership renounced
                    if is_ownership_renounced(token_data['raw_results'].get('owner_address')):
                        token_data['is_renounced'] = True
                    else:
                        token_data['is_renounced'] = False

                    # Check for liquidity locked
                    token_data['locked_lp'] = sum_locked_lp_percent(
                        token_data.get('raw_results')
                    )
                except Exception as e:
                    logger.error(f"Error getting security info: {e}")

                # Store data
                try:
                    supabase_result = await asyncio.to_thread(
                        update_pair_data_in_supabase, 
                        token_data,
                        existing_data.get('source_code_id'),
                        existing_data.get('gpl_audit_id'),
                        existing_data.get('token_information_id')
                    )
                    
                    if not supabase_result:
                        logger.error("Failed to update pair data in Supabase")
                        self.handle_failed_event(event_data, "Failed to update pair data")
                        return False

                except Exception as e:
                    logger.error(f"Error storing in Supabase: {e}")
                    self.handle_failed_event(event_data, str(e))
                    return False

            else:
                # Process as new token
                # Get basic token info
                basic_info = await self.fetch_with_retry(get_eth_contract_info, web3, token_data['address'])
                if not basic_info:
                    logger.info(f"Not an ERC-20 token: {token_data['address']}")
                    return True
                
                token_data.update(basic_info)

                # Get source code
                try:
                    source_code_info = await self.fetch_with_retry(get_contract_source_code, token_data['address'])
                    token_data.update(source_code_info or {})
                    
                    if token_data.get('contract_verified') and token_data.get('source_code'):
                        social_results = get_token_socials(token_data['source_code'])
                        token_data.update(social_results)
                except Exception as e:
                    logger.error(f"Error getting source code: {e}")
                    token_data['contract_verified'] = False

                # Get security info and classification
                try:
                    security_info = await self.fetch_with_retry(
                        get_eth_token_security_info,
                        token_data['address'],
                        token_data.get('contract_verified', False),
                        'new_pair'
                    )
                    token_data.update(security_info)

                    # Get classification
                    classification, certainty = get_token_classification(
                        token_data['name'],
                        token_data['symbol']
                    )
                    token_data['classification'] = classification
                    token_data['classification_certainty'] = certainty

                    # Check for ownership renounced and liquidity locked
                    if security_info and security_info.get('raw_results'):
                        owner_address = security_info['raw_results'].get('owner_address')
                        token_data['is_renounced'] = is_ownership_renounced(owner_address) if owner_address else False

                        token_data['locked_lp'] = sum_locked_lp_percent(
                            security_info.get('raw_results')
                        )

                except Exception as e:
                    logger.error(f"Error getting security info: {e}")

                # Store data concurrently for new token
                try:
                    # Store and increment counter
                    firestore_task = asyncio.create_task(
                        asyncio.to_thread(increment_firestore_counter, token_data)
                    )
                    supabase_task = asyncio.create_task(
                        asyncio.to_thread(store_new_pair_data_in_supabase, token_data)
                    )

                    # Wait for storage operations
                    firestore_result, supabase_result = await asyncio.gather(
                        firestore_task,
                        supabase_task,
                        return_exceptions=True
                    )

                    if isinstance(supabase_result, Exception):
                        raise supabase_result
                    if not supabase_result:
                        raise Exception("Failed to store new pair data")

                except Exception as e:
                    logger.error(f"Error in storage operations: {e}")
                    self.handle_failed_event(event_data, str(e))
                    return False

            # Queue for notification if not a scam (for both new and existing tokens)
            if not token_data.get('is_scam'):
                self.redis.rpush('notification_queue', json.dumps({
                    'event_type': 'new_pair',
                    'token_data': token_data
                }))            

            return True
        except Exception as e:
            logger.error(f"Error processing new pair: {str(e)}")
            self.handle_failed_event(event_data, str(e))  # Add this line
            return False

    async def process_lock_lp(self, event_data: Dict[str, Any]) -> bool:
        """Process LP lock events"""
        try:
            if DEV_MODE:
                logger.info("Processing Lock LP Event:")
                logger.info(json.dumps(event_data, indent=2))

            # Get LP token from transformed data
            transformed_data = event_data.get('transformed_data', {})
            lp_token = transformed_data.get('lp_token')
            if not lp_token:
                logger.error("No LP token address in event data")
                return False

            # Check if token exists in Supabase
            blockchain = convert_chain_id_to_blockchain(event_data['chain_id'])
            existing_token = supabase.table('tokens')\
                .select('address, name, symbol, contract_verified, classification, classification_certainty, is_scam, source_code_id, gpl_audit_id, token_information_id')\
                .eq('dex_pair', lp_token)\
                .eq('blockchain', blockchain)\
                .execute()

            if not existing_token.data:
                if DEV_MODE:
                    logger.info(f"LP token {lp_token} not found in database, ignoring")
                return True

            # If token is marked as scam, don't process
            existing_data = existing_token.data[0]
            if existing_data.get('is_scam'):
                if DEV_MODE:
                    logger.info(f"Token {lp_token} is marked as scam, skipping")
                return True

            # Process like a dex pair update for existing token
            token_data = {
                'chain_id': event_data['chain_id'],
                'block_number': event_data['block_number'],
                'event_type': 'lock_lp',
                'event_id': event_data['event_id'],
                'dex_pair': lp_token,
                'blockchain': blockchain,
                # Hydrate with existing info
                'address': existing_data.get('address'),
                'name': existing_data.get('name'),
                'symbol': existing_data.get('symbol'),
                'classification': existing_data.get('classification'),
                'classification_certainty': existing_data.get('classification_certainty'),
                'contract_verified': existing_data.get('contract_verified')
            }

            # If contract wasn't verified before, check again
            if not existing_data.get('source_code_id'):
                try:
                    source_code_info = await self.fetch_with_retry(get_contract_source_code, token_data['address'])
                    token_data.update(source_code_info or {})

                    if token_data.get('contract_verified') and token_data.get('source_code'):
                        social_results = get_token_socials(token_data['source_code'])
                        token_data.update(social_results)
                except Exception as e:
                    logger.error(f"Error getting source code: {e}")
                    token_data['contract_verified'] = False

            # Get fresh security audit
            try:
                security_info = await self.fetch_with_retry(
                    get_eth_token_security_info,
                    token_data['address'],
                    token_data.get('contract_verified', False),
                    'lock_lp'
                )
                token_data.update(security_info or {})

                # Check for ownership renounced
                if is_ownership_renounced(token_data['raw_results'].get('owner_address')):
                    token_data['is_renounced'] = True
                else:
                    token_data['is_renounced'] = False

                # Calculate locked LP using both methods and take the larger value
                token_data['locked_lp'] = sum_locked_lp_percent(
                    token_data.get('raw_results'),
                    event_data.get('transformed_data')
                )

            except Exception as e:
                logger.error(f"Error getting security info: {e}")

            # Update in Supabase
            try:
                supabase_result = await asyncio.to_thread(
                    update_pair_data_in_supabase, 
                    token_data,
                    existing_data.get('source_code_id'),
                    existing_data.get('gpl_audit_id'),
                    existing_data.get('token_information_id')
                )
                
                if not supabase_result:
                    logger.error("Failed to update pair data in Supabase")
                    self.handle_failed_event(event_data, "Failed to update pair data")
                    return False

            except Exception as e:
                logger.error(f"Error storing in Supabase: {e}")
                self.handle_failed_event(event_data, str(e))
                return False

            # Queue for notification
            if not token_data.get('is_scam'):
                self.redis.rpush('notification_queue', json.dumps({
                    'event_type': 'lock_lp',
                    'token_data': token_data
                }))

            return True

        except Exception as e:
            logger.error(f"Error processing LP lock: {str(e)}")
            self.handle_failed_event(event_data, str(e))
            return False

    async def process_webhook(self, event_data: Dict[str, Any]) -> bool:
        """Process webhook based on event type"""
        try:
            event_type = event_data.get('event_type')
            
            if event_type == 'new_token':
                return await self.process_new_token(event_data)
            elif event_type == 'new_pair':
                return await self.process_new_pair(event_data)
            elif event_type == 'lock_lp':
                return await self.process_lock_lp(event_data)
            elif event_type == 'ownership_renounced':
                return await self.process_ownership_renounced(event_data)
            else:
                logger.error(f"Unknown event type: {event_type}")
                return False

        except Exception as e:
            logger.error(f"Error processing webhook: {str(e)}")
            self.handle_failed_event(event_data, str(e))
            return False

    async def process_retry_queue(self):
        """Process events in the retry queue that are ready"""
        now = time.time()
        # Get all events that are ready to be retried
        ready_events = self.redis.zrangebyscore('retry_queue', 0, now)
        
        if ready_events:
            self.redis.zremrangebyscore('retry_queue', 0, now)
            for event_json in ready_events:
                event_data = json.loads(event_json)
                logger.info(f"Retrying event {event_data.get('event_id')}")
                await self.process_webhook(event_data)

    async def process_ownership_renounced(self, event_data: Dict[str, Any]) -> bool:
        """Process ownership renounced events"""
        try:
            token_address = event_data['token_address']
            chain_id = event_data['chain_id']
            
            if DEV_MODE:
                logger.info(f"Processing ownership renounced for token: {token_address}")

            # Update token in database using asyncio.to_thread
            try:
                result = await asyncio.to_thread(
                    update_renounced_status_in_supabase,
                    token_address,
                    chain_id
                )
                
                if not result:
                    logger.info(f"No token found to update for address: {token_address}")
                    return True  # Return true since we successfully determined token isn't tracked

                if DEV_MODE:
                    logger.info(f"Successfully updated renounced status for token: {token_address}")
                return True

            except Exception as e:
                logger.error(f"Error updating in Supabase: {e}")
                self.handle_failed_event(event_data, str(e))
                return False

        except Exception as e:
            logger.error(f"Error processing ownership renounced: {str(e)}")
            self.handle_failed_event(event_data, str(e))
            return False

async def start_worker():
    """Start the processing worker"""
    logger.info(f"Starting worker in {'development' if DEV_MODE else 'production'} mode")
    processor = TokenProcessor()

    try:
        while True:
            try:
                # Process any ready retries first
                await processor.process_retry_queue()

                # Wait for new events
                _, data = processor.redis.blpop('webhook_queue')
                event_data = json.loads(data)
                
                if DEV_MODE:
                    logger.info(f"Received event: {event_data.get('event_id')}")
                
                await processor.process_webhook(event_data)

            except Exception as e:
                logger.error(f"Error in worker loop: {str(e)}")
                # Sleep briefly to avoid tight loop on persistent errors
                await asyncio.sleep(1)

    except KeyboardInterrupt:
        logger.info("Worker shutting down...")
        await processor.close()

def increment_firestore_counter(token_data):
    """
    Increment counter in Firestore.
    """
    try:
        # Increment counter field
        db.collection('new_token_ingestion').document('new_token_counter').update({
            'total_counter': firestore.Increment(1),
        })

        if token_data.get('risk_level') == 'High':
            db.collection('new_token_ingestion').document('new_token_counter').update({
                'scams_counter': firestore.Increment(1),
            })
        elif token_data.get('risk_level') == 'Medium':
            db.collection('new_token_ingestion').document('new_token_counter').update({
                'risky_counter': firestore.Increment(1),
            })
    
    except Exception as e:
        logging.error(f"Error storing data in Firestore: {e}")
        return None

def store_new_token_in_supabase(token_data):
    """
    Store new token in Supabase.
    """
    supabase_token_data = {
        'address': token_data.get('address'),
        'blockchain': token_data.get('blockchain'),
        'block_number': token_data.get('block_number'),
        'name': token_data.get('name'),
        'symbol': token_data.get('symbol'),
        'classification': token_data.get('classification'),
        'classification_certainty': token_data.get('classification_certainty'),
        'contract_verified': token_data.get('contract_verified'),
        'creator_address': token_data.get('creator_address'),
        'creator_percent': token_data.get('creator_percent'),
        'risk_level': token_data.get('risk_level'),
        'is_scam': token_data.get('is_scam', None),
        'buy_tax': token_data.get('buy_tax'),
        'sell_tax': token_data.get('sell_tax'),
        'creator_security': token_data.get('creator_security'),
    }

    try:
        address = supabase_token_data.get('address')
        blockchain = supabase_token_data.get('blockchain')

        if not address or not blockchain:
            logging.error("Token data does not contain 'address' or 'chain_id' field.")
            return None
        
        # Fetch existing token data if it exists
        existing_token_result = supabase.table('tokens').select('gpl_audit_id', 'source_code_id', 'token_information_id').eq('address', address).eq('blockchain', blockchain).execute()

        if existing_token_result.data:
            # token already exists, update UUIDs for gpl_audit_id and source_id
            existing_token_data = existing_token_result.data[0]
            if existing_token_data.get('source_code_id'):
                supabase_token_data['source_code_id'] = existing_token_data.get('source_code_id')
            if existing_token_data.get('gpl_audit_id'):
                supabase_token_data['gpl_audit_id'] = existing_token_data.get('gpl_audit_id')
            if existing_token_data.get('token_information_id'):
                supabase_token_data['token_information_id'] = existing_token_data.get('token_information_id')

        # if source code verified and not already existing in supabase, insert into source code table and get uuid
        if supabase_token_data.get('contract_verified') and supabase_token_data.get('source_code_id') is None:
            supabase_source_code_data = {
                'code': token_data.get('source_code')
            }
            source_code_result = supabase.table('source_code').upsert(supabase_source_code_data).execute()
            if source_code_result.data:
                supabase_token_data['source_code_id'] = source_code_result.data[0]['id']
            else:
                logging.error(f'Failed to upsert source code data')

        # if socials exist
        if check_socials_exist(token_data):
            supabase_token_information_data = {
                'website': token_data.get('website', None),
                'twitter': token_data.get('twitter', None),
                'telegram': token_data.get('telegram', None),
                'discord': token_data.get('discord', None),
            }
            # if socials already exist, update existing record
            if supabase_token_data.get('token_information_id'):
                supabase_token_information_data['updated_at'] = datetime.now(pytz.utc).isoformat()
                info_result = supabase.table('token_information').update(supabase_token_information_data).eq('id', supabase_token_data['token_information_id']).execute()

                if not info_result.data:
                    logging.error(f"Failed to update info data: {info_result}")

            else:
                # upsert token info
                info_result = supabase.table('token_information').upsert(supabase_token_information_data).execute()
                if info_result.data:
                    supabase_token_data['token_information_id'] = info_result.data[0]['id']
                else:
                    logging.error('Failed to upsert info data')
            
        # if audit, insert into audit table and get uuid
        if token_data.get('raw_results'):
            supabase_gpl_audit_data = {
                'detailed_audit_results': token_data.get('detailed_audit'),
                'raw_results': token_data.get('raw_results')
            }
            # if audit already exists, update existing record
            if supabase_token_data.get('gpl_audit_id'):
                supabase_gpl_audit_data['updated_at'] = datetime.now(pytz.utc).isoformat()
                audit_result = supabase.table('gpl_audit').update(supabase_gpl_audit_data).eq('id', supabase_token_data['gpl_audit_id']).execute()

                if not audit_result.data:
                    logging.error(f"Failed to update audit data: {audit_result}")
                
            else:
                # upsert GPL audit
                audit_result = supabase.table('gpl_audit').upsert(supabase_gpl_audit_data).execute()
                if audit_result.data:
                    supabase_token_data['gpl_audit_id'] = audit_result.data[0]['id']
                else:
                    logging.error('Failed to upsert audit data')

        # Upsert token data
        try:
            token_result = supabase.table('tokens').insert(supabase_token_data).execute()
            if not token_result.data:
                logging.error("Failed to upsert token data")
                return None
        except APIError as e:
            if e.code == '23505':
                supabase_token_data['updated_at'] = datetime.now(pytz.utc).isoformat()
                token_result = supabase.table('tokens').update(supabase_token_data).eq('address', address).eq('blockchain', blockchain).execute()
                if not token_result.data:
                    logging.warning("No data returned when updating token data")
                    return None
            else:
                raise
        
        return token_result.data[0]['address']
    
    except Exception as e:
        logging.error(f"Error storing data in Supabase: {e}")
        return None

def check_socials_exist(token_data):
    """
    Check if any of the socials exist, return False is none.
    """
    return any(token_data.get(key) for key in ['twitter', 'telegram', 'discord', 'website'])

def is_ownership_renounced(owner_address: str) -> bool:
    """Check if ownership has been renounced"""
    try:
        null_address = '0x0000000000000000000000000000000000000000'
        return owner_address.lower() == null_address
    except Exception as e:
        logger.error(f"Error checking ownership renounced: {e}")
        return False
    
def sum_locked_lp_percent(raw_results: dict = None, transformed_data: dict = None) -> float:
    """
    Calculate total locked LP percentage using multiple methods and return the larger value:
    1. Sum up locked LP from holder data
    2. Calculate from recent lock transaction amount against total supply
    Returns 0 if neither method produces a valid result.
    """
    try:
        method_1_percent = 0.0
        method_2_percent = 0.0

        # Method 1: Check LP holders data
        lp_holders = raw_results.get('lp_holders', []) if raw_results else []
        if lp_holders:
            for holder in lp_holders:
                if holder.get('is_locked') == 1:
                    percent = float(holder.get('percent', 0))
                    method_1_percent += percent
            method_1_percent *= 100  # Convert to percentage

        # Method 2: Check recent lock transaction against total supply
        if transformed_data and raw_results:
            lock_amount = transformed_data.get('amount')
            total_supply = raw_results.get('lp_total_supply')
            
            if lock_amount and total_supply:
                try:
                    # Convert both to float for calculation
                    lock_amount = float(lock_amount)  # Amount is already converted in ingestion service
                    total_supply = float(total_supply)
                    
                    if total_supply > 0:
                        method_2_percent = (lock_amount / total_supply) * 100
                except (ValueError, TypeError) as e:
                    logger.error(f"Error calculating lock percentage from amounts: {e}")

        # Return the larger of the two percentages
        return max(method_1_percent, method_2_percent)

    except Exception as e:
        logger.error(f"Error calculating locked LP: {e}")
        return 0.0
    
def store_new_pair_data_in_supabase(token_data):
    """
    Store data in Supabase. For scenario where the token for the pair was not already being tracked in the DB.
    """
    if is_token_renounced(token_data['address'], token_data['chain_id']):
        token_data['is_renounced'] = True
        
    supabase_token_data = {
        'address': token_data.get('address'),
        'blockchain': token_data.get('blockchain'),
        'block_number': token_data.get('block_number'),
        'name': token_data.get('name'),
        'symbol': token_data.get('symbol'),
        'classification': token_data.get('classification'),
        'classification_certainty': token_data.get('classification_certainty'),
        'contract_verified': token_data.get('contract_verified'),
        'creator_address': token_data.get('creator_address'),
        'creator_percent': token_data.get('creator_percent'),
        'risk_level': token_data.get('risk_level'),
        'buy_tax': token_data.get('buy_tax'),
        'sell_tax': token_data.get('sell_tax'),
        'dex_pair': token_data.get('dex_pair'),
        'is_renounced': token_data.get('is_renounced'),
        'liquidity_locked': token_data.get('locked_lp'),
        'creator_security': token_data.get('creator_security'),
    }

    try:
        address = supabase_token_data.get('address')
        blockchain = supabase_token_data.get('blockchain')

        if token_data.get('is_scam'):
            supabase_token_data['is_scam'] = token_data.get('is_scam')

        if not address or not blockchain:
            logging.error("Token data does not contain 'address' or 'chain_id' field.")
            return None
        
        # Fetch existing token data if it exists
        existing_token_result = supabase.table('tokens').select('gpl_audit_id', 'source_code_id', 'token_information_id').eq('address', address).eq('blockchain', blockchain).execute()

        if existing_token_result.data:
            # token already exists, update UUIDs for gpl_audit_id and source_id
            existing_token_data = existing_token_result.data[0]
            
            for field in ['source_code_id', 'gpl_audit_id', 'token_information_id']:
                if existing_token_data.get(field):
                    supabase_token_data[field] = existing_token_data[field]

        # if source code verified and not already existing in supabase, insert into source code table and get uuid
        if supabase_token_data.get('contract_verified') and supabase_token_data.get('source_code_id') is None:
            supabase_source_code_data = {
                'code': token_data.get('source_code')
            }
            source_code_result = supabase.table('source_code').upsert(supabase_source_code_data).execute()
            if source_code_result.data:
                supabase_token_data['source_code_id'] = source_code_result.data[0]['id']
            else:
                logging.error(f'Failed to upsert source code data')
            
        # if socials exist
        if check_socials_exist(token_data):
            supabase_token_information_data = {
                'website': token_data.get('website', None),
                'twitter': token_data.get('twitter', None),
                'telegram': token_data.get('telegram', None),
                'discord': token_data.get('discord', None),
            }
            # if socials already exist, update existing record
            if supabase_token_data.get('token_information_id'):
                supabase_token_information_data['updated_at'] = datetime.now(pytz.utc).isoformat()
                info_result = supabase.table('token_information').update(supabase_token_information_data).eq('id', supabase_token_data['token_information_id']).execute()

                if not info_result.data:
                    logging.error(f"Failed to update info data: {info_result}")

            else:
                # upsert token info
                info_result = supabase.table('token_information').upsert(supabase_token_information_data).execute()
                if info_result.data:
                    supabase_token_data['token_information_id'] = info_result.data[0]['id']
                else:
                    logging.error('Failed to upsert info data')

        # if audit, insert into audit table and get uuid
        if token_data.get('raw_results'):
            supabase_gpl_audit_data = {
                'detailed_audit_results': token_data.get('detailed_audit'),
                'raw_results': token_data.get('raw_results')
            }
            # if audit already exists, update existing record
            if supabase_token_data.get('gpl_audit_id'):
                supabase_gpl_audit_data['updated_at'] = datetime.now(pytz.utc).isoformat()
                audit_result = supabase.table('gpl_audit').update(supabase_gpl_audit_data).eq('id', supabase_token_data['gpl_audit_id']).execute()

                if not audit_result.data:
                    logging.error(f"Failed to update audit data: {audit_result}")
                
            else:
                # upsert GPL audit
                audit_result = supabase.table('gpl_audit').upsert(supabase_gpl_audit_data).execute()
                if audit_result.data:
                    supabase_token_data['gpl_audit_id'] = audit_result.data[0]['id']
                else:
                    logging.error('Failed to upsert audit data')

        # Upsert token data
        try:
            token_result = supabase.table('tokens').insert(supabase_token_data).execute()
            if not token_result.data:
                logging.error("Failed to upsert token data")
                return None
        except APIError as e:
            if e.code == '23505':
                supabase_token_data['updated_at'] = datetime.now(pytz.utc).isoformat()
                token_result = supabase.table('tokens').update(supabase_token_data).eq('address', address).eq('blockchain', blockchain).execute()
                if not token_result.data:
                    logging.warning("No data returned when updating token data")
                    return None
            else:
                raise
        
        return token_result.data[0]['address']
    
    except Exception as e:
        logging.error(f"Error storing data in Supabase: {e}")
        return None

def update_pair_data_in_supabase(token_data, source_code_id, gpl_audit_id, token_information_id):
    """Updates records in supabase if token already exists."""
    # Check if already renounced - if so, force is_renounced to stay True
    if is_token_renounced(token_data['address'], token_data['chain_id']):
        token_data['is_renounced'] = True

    supabase_token_data = {
        'block_number': token_data.get('block_number'),
        'contract_verified': token_data.get('contract_verified'),
        'creator_percent': token_data.get('creator_percent'),
        'risk_level': token_data.get('risk_level'),
        'is_scam': token_data.get('is_scam', None),
        'buy_tax': token_data.get('buy_tax'),
        'sell_tax': token_data.get('sell_tax'),
        'dex_pair': token_data.get('dex_pair'),
        'is_renounced': token_data.get('is_renounced'),
        'liquidity_locked': token_data.get('locked_lp'),
        'updated_at': datetime.now(pytz.utc).isoformat()
    }

    if source_code_id:
        supabase_token_data['source_code_id'] = source_code_id
    if gpl_audit_id:
        supabase_token_data['gpl_audit_id'] = gpl_audit_id
    if token_information_id:
        supabase_token_data['token_information_id'] = token_information_id

    address = token_data.get('address')
    blockchain = convert_chain_id_to_blockchain(token_data.get('chain_id'))

    if not address or not blockchain:
        logging.error("Token data does not contain 'address' or 'chain_id' field.")
        return None

    # create record for source code if non-existent and verified
    if not source_code_id and token_data.get('contract_verified'):
        supabase_source_code_data = {
            'code': token_data.get('source_code')
        }
        source_code_result = supabase.table('source_code').upsert(supabase_source_code_data).execute()
        if source_code_result.data:
            supabase_token_data['source_code_id'] = source_code_result.data[0]['id']
        else:
            logging.error(f'Failed to upsert source code data')

    # create record for token info if non-existent and socials exist
    if not token_information_id and check_socials_exist(token_data):
        supabase_token_information_data = {
            'website': token_data.get('website', None),
            'twitter': token_data.get('twitter', None),
            'telegram': token_data.get('telegram', None),
            'discord': token_data.get('discord', None),
        }
        info_result = supabase.table('token_information').upsert(supabase_token_information_data).execute()
        if info_result.data:
            supabase_token_data['token_information_id'] = info_result.data[0]['id']
        else:
            logging.error('Failed to upsert info data')

    # if audit
    if token_data.get('raw_results'):
        supabase_gpl_audit_data = {
            'detailed_audit_results': token_data.get('detailed_audit'),
            'raw_results': token_data.get('raw_results')
        }

        # if audit already exists, update existing record
        if supabase_token_data.get('gpl_audit_results'):
            supabase_gpl_audit_data['updated_at'] = datetime.now(pytz.utc).isoformat()
            audit_result = supabase.table('gpl_audit').update(supabase_gpl_audit_data).eq('id', supabase_token_data['gpl_audit_id']).execute()

            if not audit_result.data:
                logging.error(f"Failed to update audit data: {audit_result}")
            
        else:
            # upsert GPL audit
            audit_result = supabase.table('gpl_audit').upsert(supabase_gpl_audit_data).execute()
            if audit_result.data:
                supabase_token_data['gpl_audit_id'] = audit_result.data[0]['id']
            else:
                logging.error('Failed to upsert audit data')

    supabase_token_data['updated_at'] = datetime.now(pytz.utc).isoformat()
    token_result = supabase.table('tokens').update(supabase_token_data).eq('address', address).eq('blockchain', blockchain).execute()

    return token_result.data[0]['address']

def update_renounced_status_in_supabase(token_address: str, chain_id: str) -> Optional[str]:
    """Updates the renounced status of a token in Supabase"""
    try:
        blockchain = convert_chain_id_to_blockchain(chain_id)
        address = Web3.to_checksum_address(token_address)

        result = supabase.table('tokens')\
            .update({
                'is_renounced': True,
                'updated_at': datetime.now(pytz.utc).isoformat()
            })\
            .eq('address', address)\
            .eq('blockchain', blockchain)\
            .execute()

        if result.data:
            return result.data[0]['address']
        return None

    except Exception as e:
        logger.error(f"Error updating renounced status in Supabase: {e}")
        raise

def is_token_renounced(address: str, chain_id: str) -> bool:
    """
    Check if a token is already marked as renounced in the database.
    
    Args:
        address: Token contract address
        chain_id: Chain ID of the token
        
    Returns:
        bool: True if token is marked as renounced, False otherwise
    """
    try:
        blockchain = convert_chain_id_to_blockchain(chain_id)
        checksummed_address = Web3.to_checksum_address(address)
        
        result = supabase.table('tokens')\
            .select('is_renounced')\
            .eq('address', checksummed_address)\
            .eq('blockchain', blockchain)\
            .execute()
        
        return bool(result.data and result.data[0].get('is_renounced'))
    except Exception as e:
        logger.error(f"Error checking renounced status: {e}")
        return False

if __name__ == "__main__":
    asyncio.run(start_worker())