from fastapi import APIRouter, HTTPException
from web3 import Web3
from typing import List, Dict
import logging
from pydantic import BaseModel

logger = logging.getLogger(__name__)

class TokenActivation(BaseModel):
    address: str
    blockchain: str = "Ethereum"  # Default to Ethereum

def initialize_router(token_activity_service, market_data_service):
    router = APIRouter(prefix="/tokens")
    w3 = Web3()

    async def filter_tradeable_tokens(tokens: List[TokenActivation]) -> List[TokenActivation]:
        """Check which tokens have valid DEX pairs in Supabase"""
        try:
            # Group tokens by blockchain
            ethereum_tokens = [
                token.address for token in tokens 
                if token.blockchain == "Ethereum"
            ]
            
            # TODO: remove this once we have other blockchains
            logger.info(f"Filtering Ethereum tokens: {ethereum_tokens}")
            
            if not ethereum_tokens:
                logger.info("No Ethereum tokens found")
                return []

            BATCH_SIZE = 100
            tradeable_addresses = set()
            
            # Process in batches
            for i in range(0, len(ethereum_tokens), BATCH_SIZE):
                batch = ethereum_tokens[i:i + BATCH_SIZE]
                result = market_data_service.supabase.table("tokens")\
                    .select("address, dex_pair")\
                    .in_("address", batch)\
                    .eq("blockchain", "Ethereum")\
                    .neq("dex_pair", None)\
                    .execute()
                
                tradeable_addresses.update(record.get("address") for record in result.data)
            
            # Return only tokens that are tradeable
            tradeable_tokens = [
                token for token in tokens
                if token.address in tradeable_addresses
            ]
            
            if len(tradeable_tokens) < len(tokens):
                skipped = set(t.address for t in tokens) - set(t.address for t in tradeable_tokens)
                logger.info(f"Skipping non-tradeable tokens: {skipped}")
            
            logger.info(f"Final tradeable tokens: {tradeable_tokens}")
            return tradeable_tokens
            
        except Exception as e:
            logger.error(f"Error checking tradeable tokens: {str(e)}", exc_info=True)
            raise

    @router.post("/activate")
    async def mark_tokens_active(tokens: List[TokenActivation]):
        """
        1. Filters out non-tradeable tokens
        2. Ensures market data exists for tradeable tokens
        3. Marks them as active in Redis
        4. Returns success status with list of processed tokens
        """
        try:
            # Checksum all Ethereum addresses
            # TODO: may need to force this on frontend instead of backend processing
            # alternatively, see if there's more optimal way to do this
            for token in tokens:
                token.address = w3.to_checksum_address(token.address)
            
            # Filter for tradeable tokens
            tradeable_tokens = await filter_tradeable_tokens(tokens)
            
            if not tradeable_tokens:
                return {
                    "status": "success",
                    "message": "No tradeable tokens found",
                    "processed_tokens": []
                }
            
            # 3. Get currently active tokens
            active_tokens = await token_activity_service.get_active_tokens()
            
            # 4. Get active addresses
            active_addresses = {token.get("address") for token in active_tokens}
            
            # 5. Ensure market data only for new tokens
            new_tokens = [token for token in tradeable_tokens if token.address not in active_addresses]
            if new_tokens:
                success = await market_data_service.ensure_market_data(new_tokens)
                if not success:
                    raise HTTPException(status_code=500, detail="Failed to fetch market data")
            
            # 6. Activate all tradeable tokens
            for token in tradeable_tokens:
                logger.info(f"Activating token: {token.address} on blockchain: {token.blockchain}")
                await token_activity_service.activate_token(token.address, token.blockchain)
            
            return {
                "status": "success",
                "processed_tokens": [
                    {"address": token.address, "blockchain": token.blockchain}
                    for token in tradeable_tokens
                ]
            }
            
        except ValueError as e:
            raise HTTPException(status_code=400, detail=f"Invalid Ethereum address: {str(e)}")
        except Exception as e:
            logger.error(f"Error activating tokens: {str(e)}", exc_info=True)
            raise HTTPException(status_code=500, detail="Internal server error")

    return router