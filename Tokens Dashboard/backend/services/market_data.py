from typing import List, Optional, Dict
from supabase import Client
import moralis
from datetime import datetime
from app.config import settings
from app.api.tokens import TokenActivation
from web3 import Web3
import logging
import asyncio
import time

logger = logging.getLogger(__name__)

# Initialize Moralis with API key
api_key = settings.MORALIS_API_KEY

# This is currently a moralis API only service.
class MarketDataService:
    def __init__(self, supabase: Client, token_activity_service):
        self.supabase = supabase
        self.token_activity = token_activity_service
        self.w3 = Web3()
        self.BATCH_SIZE = 10  # Moralis limit
        self.semaphore = asyncio.Semaphore(10)  # Concurrent requests
        self.priority_lock = asyncio.Lock()
        self.last_request_time = 0
        self.REQUEST_DELAY = 0.1  # 100ms between requests = max 10 per second

    async def _get_or_create_token_information(self, address: str, links: Dict | None = None, logo_url: str = None) -> Optional[int]:
        # First, try to get the token_information_id + check if token exists in tokens table
        token_result = self.supabase.table("tokens")\
            .select("address, blockchain, token_information_id")\
            .eq("address", address)\
            .eq("blockchain", "Ethereum")\
            .execute()

        if token_result.data:
            token_info_id = token_result.data[0].get("token_information_id")
            if token_info_id:
                # Update existing token information
                token_update = {
                    k: v for k, v in {
                        "telegram": links.get("telegram"),
                        "twitter": links.get("twitter"),
                        "website": links.get("website"),
                        "logo_url": logo_url,
                        "updated_at": datetime.utcnow().isoformat()
                    }.items() if v is not None
                }
                self.supabase.table("token_information")\
                    .update(token_update)\
                    .eq("id", token_info_id)\
                    .execute()
                return token_info_id
        
            else:
                # Create new token information record
                
                token_info_result = self.supabase.table("token_information")\
                    .insert({
                        "telegram": links.get("telegram"),
                        "twitter": links.get("twitter"),
                        "website": links.get("website"),
                        "logo_url": logo_url,
                        "created_at": datetime.utcnow().isoformat(),
                        "updated_at": datetime.utcnow().isoformat()
                    })\
                    .execute()

                if token_info_result.data:
                    token_info_id = token_info_result.data[0].get("id")
                    
                    # Update tokens table with new token_information_id
                    self.supabase.table("tokens")\
                        .update({"token_information_id": token_info_id})\
                        .eq("address", address)\
                        .eq("blockchain", "Ethereum")\
                        .execute()
            
                return token_info_id
        
        return None

    async def _fetch_moralis_metadata_batch(self, batch: List[str], high_priority: bool = False):
        """Fetch metadata for a single batch of tokens"""
        if high_priority:
            # For high priority requests, acquire priority lock first
            async with self.priority_lock:
                async with self.semaphore:
                    return await self._do_fetch_metadata(batch)
        else:
            # Normal priority just uses semaphore
            async with self.semaphore:
                return await self._do_fetch_metadata(batch)

    async def _do_fetch_metadata(self, batch: List[str]):
        try:
            # Add delay if needed
            current_time = time.time()
            time_since_last = current_time - self.last_request_time
            if time_since_last < self.REQUEST_DELAY:
                await asyncio.sleep(self.REQUEST_DELAY - time_since_last)
            
            metadata = moralis.evm_api.token.get_token_metadata(
                api_key=api_key,
                params={
                    "chain": "eth",
                    "addresses": batch
                }
            )
            self.last_request_time = time.time()
            return metadata
        except Exception as e:
            logger.error(f"Error fetching metadata for batch: {e}")
            return None

    async def _fetch_moralis_prices_batch(self, batch: List[str], high_priority: bool = False):
        """Fetch prices for a single batch of tokens"""
        if high_priority:
            async with self.priority_lock:
                async with self.semaphore:
                    return await self._do_fetch_prices(batch)
        else:
            async with self.semaphore:
                return await self._do_fetch_prices(batch)

    async def _do_fetch_prices(self, batch: List[str]):
        try:
            # Add delay if needed
            current_time = time.time()
            time_since_last = current_time - self.last_request_time
            if time_since_last < self.REQUEST_DELAY:
                await asyncio.sleep(self.REQUEST_DELAY - time_since_last)
            
            response = moralis.evm_api.token.get_multiple_token_prices(
                api_key=api_key,
                params={"chain": "eth", "include": "percent_change"},
                body={"tokens": [{"token_address": addr} for addr in batch]}
            )
            self.last_request_time = time.time()
            return response
        except Exception as e:
            logger.error(f"Error fetching prices for batch: {e}")
            return None

    async def update_market_data(self):
        active_tokens_data = await self.token_activity.get_active_tokens()
        logger.info(f"Active tokens data: {active_tokens_data}")
        if not active_tokens_data:
            return

        # Filter for Ethereum tokens and get their addresses
        active_tokens = [
            self.w3.to_checksum_address(token.get("address")) 
            for token in active_tokens_data 
            if token.get("blockchain") == "Ethereum"
        ]

        if not active_tokens:
            return

        # Find which tokens need metadata and get supply for existing tokens
        existing_result = await self._batch_query_addresses(
            addresses=active_tokens,
            table="token_market_data",
            select_fields="address,supply"
        )
        
        # Create supply map from existing records
        supply_map = {
            record["address"]: record["supply"]
            for record in existing_result
            if record.get("supply") is not None
        }
        
        new_tokens = [addr for addr in active_tokens if addr not in [r["address"] for r in existing_result]]

        # 2. Fetch metadata for new tokens concurrently in batches
        if new_tokens:
            batches = [
                new_tokens[i:i + self.BATCH_SIZE]
                for i in range(0, len(new_tokens), self.BATCH_SIZE)
            ]
            
            # Gather all metadata concurrently
            metadata_results = await asyncio.gather(
                *[self._fetch_moralis_metadata_batch(batch, high_priority=False) for batch in batches]
            )
            
            # Flatten results and filter out None values from failed batches
            all_metadata = [
                token 
                for batch in metadata_results 
                if batch  # Skip failed batches
                for token in batch  # Flatten the list
            ]
            
            if all_metadata:
                # Process token information in batch
                await self._get_or_create_token_information_batch(all_metadata)
                
                # Process all tokens at once
                market_data = []
                for token in all_metadata:
                    supply = float(token["total_supply_formatted"])
                    address = self.w3.to_checksum_address(token["address"])
                    
                    market_data.append({
                        "address": address,
                        "blockchain": "Ethereum",
                        "decimals": int(token["decimals"]),
                        "supply": supply,
                        "market_cap": float(token["fully_diluted_valuation"]) if token.get("fully_diluted_valuation") else None,
                        "updated_at": datetime.utcnow().isoformat()
                    })
                    
                    # Add to supply map for price updates
                    supply_map[address] = supply
                
                # Single batch insert for all metadata
                if market_data:
                    self.supabase.table("token_market_data")\
                        .upsert(market_data)\
                        .execute()

        # 3. Now fetch latest prices for all active tokens concurrently
        batches = [
            active_tokens[i:i + self.BATCH_SIZE]
            for i in range(0, len(active_tokens), self.BATCH_SIZE)
        ]
        
        price_results = await asyncio.gather(
            *[self._fetch_moralis_prices_batch(batch, high_priority=False) for batch in batches]
        )
        
        # Flatten results and filter out None values from failed batches
        all_prices = [
            token 
            for batch in price_results 
            if batch  # Skip failed batches
            for token in batch  # Flatten the list
        ]

        # Create a map of address to price data
        price_map = {
            self.w3.to_checksum_address(token["tokenAddress"]): token 
            for token in all_prices
        }

        # Process all active tokens, even those without price data
        market_updates = []
        for address in active_tokens:
            price_data = price_map.get(address)
            supply = supply_map.get(address)
            
            # Calculate market cap if we have both price and supply
            market_cap = None
            if price_data and price_data.get("usdPrice") and supply:
                market_cap = float(price_data["usdPrice"]) * supply

            market_updates.append({
                "address": address,
                "blockchain": "Ethereum",
                "price": price_data["usdPrice"] if price_data else None,
                "percentchange_24h": float(price_data["24hrPercentChange"]) if price_data and price_data.get("24hrPercentChange") else None,
                "total_liquidity_usd": float(price_data["pairTotalLiquidityUsd"]) if price_data and price_data.get("pairTotalLiquidityUsd") else None,
                "security_score": price_data.get("securityScore") if price_data else None,
                "market_cap": market_cap,
                "updated_at": datetime.utcnow().isoformat()
            })
        
        # Update market data in one batch
        if market_updates:
            self.supabase.table("token_market_data").upsert(market_updates).execute()
            logger.info(f"Updated market data for {len(market_updates)} tokens")

    async def ensure_market_data(self, tokens: List[TokenActivation]) -> bool:
        """
        Ensures market data and token information exists for the given tokens.
        Currently only handles Ethereum tokens.
        Returns True if all data was found or updated successfully.
        """
        # TODO: remove this once we have other blockchains
        ethereum_tokens = [
            self.w3.to_checksum_address(token.address) 
            for token in tokens 
            if token.blockchain == "Ethereum"
        ]
        
        if not ethereum_tokens:
            return True  # No Ethereum tokens to process
        
        try:
            # Create batches
            batches = [
                ethereum_tokens[i:i + self.BATCH_SIZE]
                for i in range(0, len(ethereum_tokens), self.BATCH_SIZE)
            ]
            
            # Fetch metadata concurrently
            logger.info(f"Fetching metadata for {len(ethereum_tokens)} tokens")
            metadata_results = await asyncio.gather(
                *[self._fetch_moralis_metadata_batch(batch, high_priority=True) for batch in batches]
            )
            
            # Process metadata results
            all_metadata = [
                token 
                for batch in metadata_results 
                if batch
                for token in batch
            ]
            
            if all_metadata:
                # Process token information in batch
                await self._get_or_create_token_information_batch(all_metadata)
                
                market_data = []
                for token in all_metadata:
                    market_data.append({
                        "address": self.w3.to_checksum_address(token["address"]),
                        "blockchain": "Ethereum",
                        "decimals": int(token["decimals"]),
                        "supply": float(token["total_supply_formatted"]),
                        "market_cap": float(token["fully_diluted_valuation"]) if token.get("fully_diluted_valuation") else None,
                        "updated_at": datetime.utcnow().isoformat()
                    })
                
                if market_data:
                    self.supabase.table("token_market_data")\
                        .upsert(market_data)\
                        .execute()
            
            # Fetch prices concurrently
            price_results = await asyncio.gather(
                *[self._fetch_moralis_prices_batch(batch, high_priority=True) for batch in batches]
            )
            
            # Process price results
            all_prices = [
                token 
                for batch in price_results 
                if batch
                for token in batch
            ]
            
            # Create a map of address to price data
            price_map = {
                self.w3.to_checksum_address(token["tokenAddress"]): token 
                for token in all_prices
            }
            
            # Update all tokens, even if they don't have price data
            updates = []
            for address in ethereum_tokens:
                price_data = price_map.get(address)
                updates.append({
                    "address": address,
                    "blockchain": "Ethereum",
                    "price": price_data["usdPrice"] if price_data else None,
                    "percentchange_24h": float(price_data["24hrPercentChange"]) if price_data and price_data.get("24hrPercentChange") else None,
                    "total_liquidity_usd": float(price_data["pairTotalLiquidityUsd"]) if price_data and price_data.get("pairTotalLiquidityUsd") else None,
                    "security_score": price_data.get("securityScore") if price_data else None,
                    "updated_at": datetime.utcnow().isoformat()
                })
            
            if updates:
                self.supabase.table("token_market_data")\
                    .upsert(updates)\
                    .execute()
            
            return True
            
        except Exception as e:
            logger.error(f"Error fetching immediate market data: {str(e)}", exc_info=True)
            return False

    async def _batch_query_addresses(
        self, 
        addresses: List[str], 
        table: str, 
        select_fields: str = "address",
        additional_filters: Dict = None
    ) -> List[Dict]:
        """
        Helper function to batch query addresses from Supabase
        
        Args:
            addresses: List of addresses to query
            table: Supabase table name
            select_fields: Fields to select from table
            additional_filters: Dict of additional filters to apply
        """
        BATCH_SIZE = 100
        results = []
        
        for i in range(0, len(addresses), BATCH_SIZE):
            batch = addresses[i:i + BATCH_SIZE]
            query = self.supabase.table(table)\
                .select(select_fields)\
                .in_("address", batch)\
                .eq("blockchain", "Ethereum")
            
            # Apply any additional filters
            if additional_filters:
                for key, value in additional_filters.items():
                    if value == "not.is.null":
                        query = query.neq(key, None)
                    else:
                        query = query.eq(key, value)
            
            response = query.execute()
            results.extend(response.data)
        
        return results

    async def _get_or_create_token_information_batch(self, tokens: List[Dict]) -> None:
        """
        Batch process token information creation/updates
        
        Args:
            tokens: List of token metadata from Moralis
        """
        if not tokens:
            return

        # Filter tokens that have links or logo
        tokens_with_info = [
            token for token in tokens
            if (token.get("links") and any(token["links"].values())) or token.get("logo")
        ]

        if not tokens_with_info:
            return

        # Get addresses for filtered tokens
        addresses = [self.w3.to_checksum_address(token["address"]) for token in tokens_with_info]

        # Get existing tokens with their token_information_id using batch query
        existing_tokens = await self._batch_query_addresses(
            addresses=addresses,
            table="tokens",
            select_fields="address,blockchain,token_information_id"
        )

        # Create map of existing token info IDs
        existing_map = {
            record["address"]: record.get("token_information_id")
            for record in existing_tokens
        }

        current_time = datetime.utcnow().isoformat()
        
        # Separate updates and inserts
        updates = []
        inserts = []
        
        for token in tokens_with_info:
            address = self.w3.to_checksum_address(token["address"])
            token_info_id = existing_map.get(address)
            
            record = {
                "telegram": token["links"].get("telegram"),
                "twitter": token["links"].get("twitter"),
                "website": token["links"].get("website"),
                "logo_url": token.get("logo"),
                "updated_at": current_time
            }
            
            # Remove None values to preserve existing data
            record = {k: v for k, v in record.items() if v is not None}

            # Only proceed if we have actual data to store (besides timestamps)
            data_fields = {k: v for k, v in record.items() if k not in ["updated_at", "created_at"]}
            if data_fields:
                if token_info_id:
                    record["id"] = token_info_id
                    updates.append(record)
                else:
                    record["created_at"] = current_time
                    inserts.append(record)

        # Handle updates
        if updates:
            self.supabase.table("token_information")\
                .upsert(updates)\
                .execute()

        # Handle inserts and update tokens table with new IDs
        if inserts:
            new_info_result = self.supabase.table("token_information")\
                .insert(inserts)\
                .execute()
            
            if new_info_result.data:
                # Create map of new token info records
                new_info_map = {
                    i: record["id"]
                    for i, record in enumerate(new_info_result.data)
                }
                
                # Update tokens table with new token_information_ids
                token_updates = []
                for i, token in enumerate(tokens_with_info):
                    address = self.w3.to_checksum_address(token["address"])
                    if address not in existing_map and i in new_info_map:
                        token_updates.append({
                            "address": address,
                            "blockchain": "Ethereum",
                            "token_information_id": new_info_map[i]
                        })
                
                if token_updates:
                    self.supabase.table("tokens")\
                        .upsert(token_updates)\
                        .execute()