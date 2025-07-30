from fastapi import FastAPI, HTTPException, Header, Request
from fastapi.responses import JSONResponse
from redis import Redis
from web3 import Web3
import json
from datetime import datetime
import logging
import os
from typing import Dict, Any, List

from moralis_helper_functions import get_token_from_pair

from config.settings import (
    REDIS_HOST,
    REDIS_PORT,
    MORALIS_SECRET_KEY,
    OWNERSHIP_TRANSFERRED_SIGNATURE,
    PAIR_CREATED_SIGNATURE,
    LOCK_LP_FUNCTION_SIGNATURE,
    UNICRYPT_LOCKER_ADDRESS,
    RENOUNCED_ADDRESSES
)

# Development mode check
DEV_MODE = os.getenv('DEV_MODE', 'false').lower() == 'true'

# Configure logging
logging.basicConfig(
    level=logging.INFO if DEV_MODE else logging.ERROR,
    format='\n%(asctime)s - %(levelname)s:\n%(message)s\n'
)
logger = logging.getLogger(__name__)

logger.setLevel(logging.INFO if DEV_MODE else logging.ERROR)

app = FastAPI()

# Initialize Redis
redis_client = Redis(
    host=REDIS_HOST,
    port=REDIS_PORT,
    decode_responses=True
)

def extract_addresses_from_logs(logs: List[Dict[str, Any]]) -> List[str]:
    """Extract all unique addresses from event logs"""
    try:
        addresses = [log.get('address') for log in logs if log.get('address')]
        return list(set(addresses))  # Remove any duplicates
    except Exception as e:
        logger.error(f"Error extracting addresses: {e}")
        return []

class WebhookService:
    if DEV_MODE:
            logger.info("DEV MODE enabled")

    @staticmethod
    async def verify_moralis_signature(request: Request, x_signature: str = Header(...)) -> bool:
        """Verify Moralis webhook signature"""
        if DEV_MODE:
            logger.info("DEV MODE: Skipping signature verification")
            return True

        try:
            provided_signature = request.headers.get("x-signature")

            if not provided_signature:
                return False
            
            if provided_signature.startswith('0x'):
                provided_signature = provided_signature[2:]

            secret = MORALIS_SECRET_KEY
            if not secret:
                logger.error("MORALIS_SECRET_KEY not set")
                return False

            body = await request.body()
            if body is None:
                logging.error("Error: Request data is None.")
                return False

            data = body + secret.encode()
            signature = Web3.keccak(text=data.decode()).hex()
            
            if signature.startswith('0x'):
                signature = signature[2:]

            return provided_signature == signature

        except Exception as e:
            logger.error(f"Signature verification failed: {e}")
            return False

    @staticmethod
    def get_event_type(data: Dict[str, Any]) -> str:
        """Determine event type from webhook data"""
        # Check ABI for event name
        if 'abi' in data and data['abi']:
            event_name = data['abi'][0].get('name')
            if event_name == 'LockLPToken':
                # Also verify it's a lock transaction by checking input
                tx = data['txs'][0]
                input_data = tx.get('input', '')
                if input_data.startswith(LOCK_LP_FUNCTION_SIGNATURE):
                    # Decode and check amount
                    try:
                        clean_data = input_data[10:]  # Remove function signature
                        amount = int(clean_data[64:128], 16)  # Get amount from input data
                        if amount > 0:
                            return 'lock_lp'
                        else:
                            logger.info("Skipping LP lock event with zero amount")
                    except Exception as e:
                        logger.error(f"Error decoding LP lock amount: {e}")
            # Add other event names as needed

        # Fallback to existing log checks
        if 'logs' in data and data['logs']:
            log = data['logs'][0]
            event_signature = log.get('topic0')

            if event_signature == OWNERSHIP_TRANSFERRED_SIGNATURE:
                # Extract the new owner address from topic2 (remove padding)
                new_owner = "0x" + log.get('topic2', '')[-40:]
            
            # Check if it's a renounce event (transfer to any burn address)
                if new_owner.lower() in [addr.lower() for addr in RENOUNCED_ADDRESSES]:
                    return 'ownership_renounced'
                else:
                    return 'new_token'
            elif event_signature == PAIR_CREATED_SIGNATURE:
                return 'new_pair'

        return 'unknown'

    @staticmethod
    def is_confirmed(data: Dict[str, Any]) -> bool:
        """Check if block is confirmed"""
        return data.get('confirmed', False)

webhook_service = WebhookService()

@app.post("/test/ingestion" if DEV_MODE else "/process")
async def process_webhook(request: Request):
    """Handle incoming webhooks"""
    try:
        # Verify Moralis signature
        if not await webhook_service.verify_moralis_signature(request):
            return JSONResponse(
                status_code=200,
                content={"status": "success", "message": "Nice try"}
            )

        # Get JSON data
        data = await request.json()
        if not data:
            raise HTTPException(status_code=400, detail="No data received")

        if DEV_MODE:
            logger.info("Received Headers:")
            logger.info(json.dumps(dict(request.headers), indent=2))
            logger.info("Received Webhook Data:")
            logger.info(json.dumps(data, indent=2))

        # Check block confirmation
        if not webhook_service.is_confirmed(data):
            logger.info("Block not confirmed, skipping")
            return JSONResponse(
                status_code=200,
                content={"status": "success", "message": "Block not confirmed"}
            )

        # Determine event type
        event_type = webhook_service.get_event_type(data)
        if DEV_MODE:
            logger.info(f"Event Type: {event_type}")

        if event_type == 'unknown':
            logger.info("Unknown event type, skipping")
            return JSONResponse(
                status_code=200,
                content={"status": "success", "message": "Unknown event type"}
            )
        
        # Handle different event types
        if event_type == 'new_token':
            # Extract addresses from logs
            addresses = extract_addresses_from_logs(data.get('logs', []))
            
            if not addresses:
                return JSONResponse(
                    status_code=200,
                    content={"status": "success", "message": "No addresses found"}
                )
            
            # Queue individual events for each address
            queued_events = []
            for address in addresses:
                event_data = {
                    'event_id': f"{data.get('id', str(datetime.utcnow().timestamp()))}_{address}",
                    'event_type': event_type,
                    'chain_id': data.get('chainId'),
                    'block_number': data.get('block', {}).get('number'),
                    'received_at': datetime.utcnow().isoformat(),
                    'address': address,
                    'raw_data': {
                        'logs': [log for log in data.get('logs', []) if log.get('address') == address],
                        'block': data.get('block'),
                        'chainId': data.get('chainId')
                    },
                    'retry_count': 0
                }
                redis_client.rpush('webhook_queue', json.dumps(event_data))
                queued_events.append(event_data['event_id'])
                if DEV_MODE:
                    logger.info(f"Queued event: {event_data}")
            
            return JSONResponse(
                status_code=202,
                content={
                    "status": "accepted",
                    "event_type": event_type,
                    "queued_events": queued_events
                }
            )
        
        # TODO: implement loop logic if determined needed
        elif event_type == 'new_pair':
            # Extract pair data
            event_data = {
                'event_id': data.get('id', str(datetime.utcnow().timestamp())),
                'event_type': event_type,
                'chain_id': data.get('chainId'),
                'block_number': data.get('block', {}).get('number'),
                'received_at': datetime.utcnow().isoformat(),
                'raw_data': data,
                'retry_count': 0
            }

            # Add pair-specific data
            pair_data = get_token_from_pair(data)  # Your existing function
            if pair_data:
                event_data['token_address'] = pair_data[0]
                event_data['pair_address'] = pair_data[1]
            
            redis_client.rpush('webhook_queue', json.dumps(event_data))
            if DEV_MODE:
                logger.info(f"Queued event: {event_data}")

            return JSONResponse(
                status_code=202,
                content={
                    "status": "accepted",
                    "event_type": event_type,
                    "webhook_id": event_data['event_id']
                }
            )

        elif event_type == 'lock_lp':
            # Transform the data
            block_data = transform_lock_lp_data(data)

            if not block_data:
                return JSONResponse(
                    status_code=200,
                    content={"status": "success", "message": "Failed to transform LP lock data"}
                )
            # Queue single event with transformed data
            event_data = {
                'event_id': data.get('id', str(datetime.utcnow().timestamp())),
                'event_type': event_type,
                'chain_id': data.get('chainId'),
                'block_number': data.get('block', {}).get('number'),
                'received_at': datetime.utcnow().isoformat(),
                'transformed_data': block_data,  # Contains decoded LP token, amount, unlock time
                'raw_data': data,
                'retry_count': 0
            }

            redis_client.rpush('webhook_queue', json.dumps(event_data))
            if DEV_MODE:
                logger.info(f"Queued event: {event_data}")

            return JSONResponse(
                status_code=202,
                content={
                    "status": "accepted",
                    "event_type": event_type,
                    "webhook_id": event_data['event_id']
                }
            )

        elif event_type == 'ownership_renounced':
            # Extract addresses from logs
            addresses = extract_addresses_from_logs(data.get('logs', []))
            
            if not addresses:
                return JSONResponse(
                    status_code=200,
                    content={"status": "success", "message": "No addresses found"}
                )
            
            # Queue individual events for each address
            queued_events = []
            for address in addresses:
                event_data = {
                    'event_id': f"{data.get('id', str(datetime.utcnow().timestamp()))}_{address}",
                    'event_type': event_type,
                    'chain_id': data.get('chainId'),
                    'block_number': data.get('block', {}).get('number'),
                    'received_at': datetime.utcnow().isoformat(),
                    'token_address': address,
                    'retry_count': 0
                }
                redis_client.rpush('webhook_queue', json.dumps(event_data))
                queued_events.append(event_data['event_id'])
                if DEV_MODE:
                    logger.info(f"Queued event: {event_data}")
            
            return JSONResponse(
                status_code=202,
                content={
                    "status": "accepted",
                    "event_type": event_type,
                    "queued_events": queued_events
                }
            )

    except Exception as e:
        logger.error(f"Error processing webhook: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    try:
        redis_client.ping()
        queue_size = redis_client.llen('webhook_queue')
        retry_size = redis_client.zcard('retry_queue')
        failed_size = redis_client.llen('failed_events')
        notification_size = redis_client.llen('notification_queue')
        
        return {
            "status": "healthy",
            "mode": "development" if DEV_MODE else "production",
            "queue_size": queue_size,
            "retry_queue_size": retry_size,
            "failed_events": failed_size,
            "notification_queue_size": notification_size,
            "timestamp": datetime.utcnow().isoformat()
        }
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        raise HTTPException(status_code=503, detail="Service unhealthy")


def decode_lock_lp_input(input_data: str) -> Dict[str, Any]:
    """
    Decode Unicrypt lock LP function input data.
    Function signature: lockLPToken(address lpToken, uint256 amount, uint256 unlock_time, ...)
    """
    try:
        # Remove function signature (first 4 bytes / 10 characters including '0x')
        clean_data = input_data[10:]
        
        # Each parameter is 32 bytes (64 characters)
        lp_token = '0x' + clean_data[:64][-40:]  # Get last 20 bytes for address
        raw_amount = int(clean_data[64:128], 16)
        amount = raw_amount / (10 ** 18)  # Convert from wei to ether (18 decimals for LP tokens)
        unlock_time = int(clean_data[128:192], 16)
        
        return {
            'lp_token': Web3.to_checksum_address(lp_token),
            'amount': amount,
            'raw_amount': raw_amount,  # Keep the raw amount in case needed
            'unlock_time': unlock_time
        }
    except Exception as e:
        logger.error(f"Error decoding lock LP input: {e}")
        return None

def transform_lock_lp_data(data: Dict[str, Any]) -> Dict[str, Any]:
    """Transform webhook data for LP lock events"""
    try:
        tx = data['txs'][0]
        input_data = tx['input']
        
        # Decode input data
        decoded = decode_lock_lp_input(input_data)
        if not decoded:
            return None
            
        return {
            'chain_id': data.get('chainId'),
            'block_number': data.get('block', {}).get('number'),
            'transaction_hash': tx.get('hash'),
            'locker': tx.get('toAddress'),
            'user': tx.get('fromAddress'),
            'lp_token': decoded['lp_token'],
            'amount': decoded['amount'],
            'unlock_time': decoded['unlock_time']
        }
    except Exception as e:
        logger.error(f"Error transforming lock LP data: {e}")
        return None