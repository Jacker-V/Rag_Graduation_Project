"""
Scheduled News Fetcher
Automatically fetch news at 12 AM and 12 PM daily
"""
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from datetime import datetime
import logging

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class NewsScheduler:
    """Background scheduler for news fetching"""
    
    def __init__(self, pipeline=None):
        self.pipeline = pipeline
        self.scheduler = BackgroundScheduler()
        self.is_running = False
        
    def start(self, run_immediately: bool = False):
        """Start the scheduled news fetcher - runs at 12:00 AM and 12:00 PM
        
        Args:
            run_immediately: If True, fetch news immediately on startup.
                           Default is False to avoid rate limiting.
        """
        if self.is_running:
            logger.warning("Scheduler already running")
            return
            
        # Schedule for 12:00 AM (midnight)
        self.scheduler.add_job(
            func=self._fetch_all_news,
            trigger=CronTrigger(hour=0, minute=0),  # 00:00
            id='news_fetch_midnight',
            name='Fetch news at midnight',
            replace_existing=True
        )
        
        # Schedule for 12:00 PM (noon)
        self.scheduler.add_job(
            func=self._fetch_all_news,
            trigger=CronTrigger(hour=12, minute=0),  # 12:00
            id='news_fetch_noon',
            name='Fetch news at noon',
            replace_existing=True
        )
        
        # Start scheduler
        self.scheduler.start()
        self.is_running = True
        logger.info("✓ News scheduler started (fetch at 12:00 AM and 12:00 PM)")
        
        # Only run immediately if explicitly requested (to avoid rate limiting)
        if run_immediately:
            logger.info("Running initial news fetch...")
            self._fetch_all_news()
        else:
            logger.info("Skipping initial news fetch - using cached articles (scheduled runs at 12 AM/PM)")
        
    def stop(self):
        """Stop the scheduler"""
        if self.scheduler.running:
            self.scheduler.shutdown()
            self.is_running = False
            logger.info("News scheduler stopped")
            
    def _fetch_all_news(self):
        """Fetch news for all roles"""
        try:
            from rag_chatbot.workers.news_fetcher import NewsFetcher, ROLE_NEWS_SOURCES
            
            logger.info(f"[{datetime.now()}] Starting scheduled news fetch...")
            
            fetcher = NewsFetcher(self.pipeline)
            total_fetched = 0
            
            for role_type in ROLE_NEWS_SOURCES.keys():
                try:
                    count = fetcher.fetch_news_for_role(role_type, fetch_content=False)
                    total_fetched += count
                    logger.info(f"  ✓ {role_type}: {count} articles")
                    
                    # Embed new articles if pipeline available
                    if self.pipeline and count > 0:
                        fetcher.embed_articles(role_type, limit=count)
                        
                except Exception as e:
                    logger.error(f"  ✗ {role_type}: {e}")
                    
            logger.info(f"[{datetime.now()}] Scheduled fetch complete: {total_fetched} total articles")
            
        except Exception as e:
            logger.error(f"Scheduled news fetch failed: {e}")
            import traceback
            traceback.print_exc()


# Global scheduler instance
_scheduler = None


def start_news_scheduler(pipeline=None, run_immediately: bool = False):
    """Start the global news scheduler - runs at 12:00 AM and 12:00 PM
    
    Args:
        pipeline: RAG pipeline instance for embedding articles
        run_immediately: If True, fetch news immediately on startup.
                        Default is False to avoid rate limiting.
    """
    global _scheduler
    
    if _scheduler is None:
        _scheduler = NewsScheduler(pipeline)
        
    _scheduler.start(run_immediately=run_immediately)
    return _scheduler


def stop_news_scheduler():
    """Stop the global news scheduler"""
    global _scheduler
    
    if _scheduler:
        _scheduler.stop()
        _scheduler = None
