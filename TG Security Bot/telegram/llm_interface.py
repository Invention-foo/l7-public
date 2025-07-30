import asyncio
from functools import partial
from concurrent.futures import ThreadPoolExecutor
from aiolimiter import AsyncLimiter
from cachetools import TTLCache
from cachetools.func import ttl_cache
from app.services.llm_setup import is_impersonation, is_spam

thread_pool = ThreadPoolExecutor(max_workers=10)
gemini_limiter = AsyncLimiter(2000, 60)

@ttl_cache(maxsize=1000, ttl=3600)
def cached_impersonation_check(sender_name, verified_name):
    return is_impersonation(verified_name, sender_name)

def hashable_project_info(project_info):
    return tuple(sorted(project_info.items()))

@ttl_cache(maxsize=1000, ttl=3600)
def cached_spam_check(message, hashable_info):
    project_info = dict(hashable_info)
    return is_spam(message, project_info)

async def llm_check_impersonation(verified_name, sender_name):
    try:
        async with gemini_limiter:
            loop = asyncio.get_running_loop()
            reason, impersonation, confidence = await loop.run_in_executor(
                thread_pool,
                cached_impersonation_check,
                verified_name,
                sender_name
            )
            return reason, impersonation, float(confidence) / 100, confidence
    except Exception as e:
        return 'Error', False, 0.0, '0'
    
async def llm_check_spam(message, project_info):
    try:
        async with gemini_limiter:
            loop = asyncio.get_running_loop()
            hashable_info = hashable_project_info(project_info)
            reason, is_spam, score = await loop.run_in_executor(
                thread_pool,
                cached_spam_check,
                message,
                hashable_info
            )
            return reason, is_spam, score
    except Exception as e:
        return f'Error: {e}', False, 0