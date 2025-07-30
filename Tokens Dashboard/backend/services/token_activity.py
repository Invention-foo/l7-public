from redis import Redis
from typing import List, Dict
from app.config import settings
import json

class TokenActivityService:
    def __init__(self, redis_client: Redis):
        self.redis = redis_client
        self.expiry = settings.ACTIVE_TOKEN_EXPIRY
        self.key_prefix = "webapp:active_token:"

    async def activate_token(self, token_address: str, blockchain: str = "Ethereum"):
        """Activate a token with its blockchain"""
        key = f"{self.key_prefix}{blockchain}:{token_address}"
        
        try:
            self.redis.setex(key, self.expiry, 1)     
        except Exception as e:
            print(f"  Redis error: {str(e)}")
            raise

    async def get_active_tokens(self) -> List[Dict[str, str]]:
        """Get list of active tokens with their blockchains"""
        keys = self.redis.keys(f"{self.key_prefix}*")
        
        active_tokens = []
        for key in keys:
            if self.redis.exists(key):  # Verify key still exists
                _, _, blockchain, address = key.split(":")
                active_tokens.append({
                    "blockchain": blockchain,
                    "address": address
                })
        return active_tokens