import time
import asyncio

class APIRateLimiter:
    def __init__(self, calls_limit, time_period):
        self.calls_limit = calls_limit
        self.time_period = time_period
        self.calls_made = []
        self.lock = asyncio.Lock()

    async def wait_if_needed(self):
        async with self.lock:
            current_time = time.time()
            
            # Remove old calls
            self.calls_made = [call_time for call_time in self.calls_made if current_time - call_time <= self.time_period]
            
            if len(self.calls_made) >= self.calls_limit:
                sleep_time = self.calls_made[0] + self.time_period - current_time
                if sleep_time > 0:
                    await asyncio.sleep(sleep_time)
            
            self.calls_made.append(time.time())

# Create a single instance of the rate limiter
rate_limiter = APIRateLimiter(calls_limit=30, time_period=1)  # 30 calls per second

async def api_call(bot, method, *args, **kwargs):
    await rate_limiter.wait_if_needed()
    return await getattr(bot, method)(*args, **kwargs)