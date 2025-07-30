from fastapi import FastAPI, BackgroundTasks
from redis import Redis
from supabase import create_client
from app.config import settings
from app.services.token_activity import TokenActivityService
from app.services.market_data import MarketDataService
from app.api.tokens import initialize_router
import asyncio
from contextlib import asynccontextmanager
import logging
from datetime import datetime

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def update_market_data_periodically(market_data_service: MarketDataService):
    while True:
        start_time = datetime.utcnow()
        try:
            logger.info("Starting periodic market data update")
            await market_data_service.update_market_data()
            duration = (datetime.utcnow() - start_time).total_seconds()
            logger.info(f"Market data update completed in {duration:.2f} seconds")
        except Exception as e:
            logger.error(f"Error updating market data: {str(e)}", exc_info=True)

        await asyncio.sleep(300) # Wait 5 minutes between updates

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Start background task
    task = asyncio.create_task(update_market_data_periodically(market_data))
    yield
    # Cleanup
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        logger.info("Market data update task cancelled")

app = FastAPI(lifespan=lifespan)

# Initialize clients
redis_client = Redis(
    host=settings.REDIS_HOST,
    port=settings.REDIS_PORT,
    decode_responses=True
)

supabase_client = create_client(
    settings.SUPABASE_URL,
    settings.SUPABASE_KEY
)

# Initialize services
token_activity = TokenActivityService(redis_client)
market_data = MarketDataService(supabase_client, token_activity)

# Initialize and include routers
tokens_router = initialize_router(token_activity, market_data)
app.include_router(tokens_router)