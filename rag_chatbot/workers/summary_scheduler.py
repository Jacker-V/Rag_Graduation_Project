"""
Summary Scheduler - Generates welcome summaries for all roles periodically
Runs at 12 AM and 12 PM daily
"""

import json
import re
import html
import logging
from datetime import datetime
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

logger = logging.getLogger(__name__)


def _strip_html(value: str) -> str:
    if not value:
        return ''
    text = re.sub(r'<\s*br\s*/?>', '\n', value, flags=re.IGNORECASE)
    text = re.sub(r'</p\s*>', '\n', text, flags=re.IGNORECASE)
    text = re.sub(r'<[^>]+>', ' ', text)
    text = html.unescape(text)
    text = re.sub(r'[\t\r\f\v]+', ' ', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    text = re.sub(r' {2,}', ' ', text)
    return text.strip()


def _first_paragraphs(content: str, max_paragraphs: int = 3) -> list[str]:
    if not content:
        return []

    paragraphs: list[str] = []
    if '<p' in content.lower():
        for match in re.findall(r'<p\b[^>]*>(.*?)</p\s*>', content, flags=re.IGNORECASE | re.DOTALL):
            text = _strip_html(match)
            if text:
                paragraphs.append(text)
            if len(paragraphs) >= max_paragraphs:
                break
    else:
        stripped = _strip_html(content)
        for part in re.split(r'\n\s*\n+', stripped):
            text = part.strip()
            if text:
                paragraphs.append(text)
            if len(paragraphs) >= max_paragraphs:
                break

    return paragraphs


def _take_sentences(text: str, max_sentences: int = 3, max_chars: int = 360) -> str:
    cleaned = re.sub(r'\s+', ' ', (text or '')).strip()
    if not cleaned:
        return ''

    parts = re.split(r'(?<=[\.!\?…。])\s+', cleaned)
    selected: list[str] = []
    for part in parts:
        part = part.strip()
        if not part:
            continue
        selected.append(part)
        if len(selected) >= max_sentences:
            break

    result = ' '.join(selected).strip()
    if len(result) > max_chars:
        result = result[: max_chars - 1].rstrip() + '…'
    return result


def build_article_summary(title: str, content: str | None, fallback_summary: str | None = None) -> str:
    paragraphs = _first_paragraphs(content or '', max_paragraphs=3)
    base = ' '.join(paragraphs).strip()
    if not base and fallback_summary:
        base = _strip_html(fallback_summary)

    summary = _take_sentences(base, max_sentences=3, max_chars=360)
    if summary:
        return summary

    safe_title = (title or '').strip()
    return safe_title[:180] + ('…' if len(safe_title) > 180 else '')


class SummaryScheduler:
    """Background scheduler for generating role summaries"""
    
    def __init__(self, pipeline=None):
        """Initialize the scheduler
        
        Args:
            pipeline: RAG pipeline instance for LLM access
        """
        self.scheduler = BackgroundScheduler()
        self.pipeline = pipeline
        
    def start(self, run_immediately: bool = False):
        """Start the summary scheduler - runs at 12:00 AM and 12:00 PM
        
        Args:
            run_immediately: If True, generate summaries immediately on startup.
                           Default is False to avoid rate limiting on restart.
        """
        logger.info("Starting Summary Scheduler...")
        
        # Schedule for 12:00 AM (midnight)
        self.scheduler.add_job(
            self._generate_all_summaries,
            CronTrigger(hour=0, minute=0),  # 00:00
            id='summary_midnight',
            name='Generate summaries at midnight',
            replace_existing=True
        )
        
        # Schedule for 12:00 PM (noon)
        self.scheduler.add_job(
            self._generate_all_summaries,
            CronTrigger(hour=12, minute=0),  # 12:00
            id='summary_noon',
            name='Generate summaries at noon',
            replace_existing=True
        )
        
        self.scheduler.start()
        logger.info("Summary Scheduler started - will run at 12:00 AM and 12:00 PM")
        
        # Only run immediately if explicitly requested (to avoid rate limiting)
        if run_immediately:
            logger.info("Running initial summary generation...")
            self._generate_all_summaries()
        else:
            logger.info("Skipping initial generation - using cached summaries (scheduled runs at 12 AM/PM)")
        
    def stop(self):
        """Stop the scheduler"""
        if self.scheduler.running:
            self.scheduler.shutdown()
            logger.info("Summary Scheduler stopped")
            
    def _generate_all_summaries(self):
        """Generate summaries for all role types"""
        from rag_chatbot.database import db, role_summary_manager
        
        logger.info(f"[{datetime.now()}] Starting scheduled summary generation...")
        
        # Define all role types
        role_types = [
            ('frontend_dev', 'Frontend Developer'),
            ('backend_dev', 'Backend Developer'),
            ('mobile_dev', 'Mobile Developer'),
            ('devops', 'DevOps Engineer'),
            ('data_scientist', 'Data Scientist'),
            ('qa_engineer', 'QA Engineer'),
            ('security', 'Security Engineer'),
            ('cloud_architect', 'Cloud Architect'),
            ('ai_ml', 'AI/ML Engineer')
        ]
        
        for i, (role_type, role_name) in enumerate(role_types):
            try:
                self._generate_role_summary(role_type, role_name)
                logger.info(f"  ✓ Generated summary for {role_type}")
            except Exception as e:
                logger.error(f"  ✗ Failed to generate summary for {role_type}: {e}")
                
        logger.info(f"[{datetime.now()}] Scheduled summary generation complete")
        
    def _generate_role_summary(self, role_type: str, role_name: str):
        """Generate summary for a specific role
        
        Args:
            role_type: Role type identifier
            role_name: Human-readable role name
        """
        from rag_chatbot.database import db, role_summary_manager
        
        conn = db.get_connection()
        cursor = conn.cursor()
        
        # Get hottest news (last 7 days, sorted by total views)
        cursor.execute("""
            SELECT id, title, summary, intro_llm_summary, content,
                   COALESCE(view_count, 0) + COALESCE(online_view_count, 0) + 
                   COALESCE(explain_count, 0) + COALESCE(summary_count, 0) + 
                   COALESCE(link_click_count, 0) as total_interaction, 
                   published_date, url
            FROM technical_articles
            WHERE role_type = ? 
            AND published_date >= date('now', '-7 days')
            ORDER BY total_interaction DESC, published_date DESC
            LIMIT 3
        """, (role_type,))
        hot_news = cursor.fetchall()
        
        # Get recently added documents (last 7 days)
        cursor.execute("""
            SELECT id, original_filename, upload_date, metadata
            FROM documents
                        WHERE status = 'active'
                            AND upload_date >= date('now', '-7 days')
            ORDER BY upload_date DESC
            LIMIT 3
        """)
        new_docs = cursor.fetchall()
        
        # Build context for AI summary
        context_parts = []
        
        # Prepare structured data
        hot_news_list = []
        if hot_news:
            context_parts.append("**Tin tức nổi bật tuần này:**")
            for news_id, title, summary, intro_llm_summary, content, views, pub_date, url in hot_news:
                news_summary = (intro_llm_summary or '').strip() or build_article_summary(title, content, fallback_summary=summary)
                context_parts.append(f"- {title}: {news_summary} ({views} lượt tương tác)")
                hot_news_list.append({
                    'id': news_id,
                    'title': title,
                    'summary': news_summary,
                    'views': views,
                    'url': url
                })
        
        # Prepare new documents data
        new_docs_list = []
        if new_docs:
            context_parts.append("\n**Tài liệu mới được thêm:**")
            for doc_id, filename, upload_date, metadata in new_docs:
                description = ""
                if metadata:
                    try:
                        meta_dict = json.loads(metadata)
                        description = meta_dict.get('description', '')
                    except:
                        pass
                
                context_parts.append(f"- {filename}")
                new_docs_list.append({
                    'id': doc_id,
                    'filename': filename,
                    'upload_date': upload_date,
                    'description': description
                })
        
        # Generate summary text WITHOUT LLM (avoid rate limits)
        summary_text = f"Chào mừng bạn trở lại! "
        if hot_news:
            summary_text += f"Tuần này có {len(hot_news)} tin tức nổi bật: "
            news_titles = [n['title'] for n in hot_news_list[:3]]
            summary_text += "; ".join(news_titles) + ". "
        if new_docs:
            summary_text += f"Có {len(new_docs)} tài liệu mới. "
        summary_text += "Hãy khám phá ngay!"
        
        # Save to database
        stats = {
            'hot_news_count': len(hot_news),
            'new_docs_count': len(new_docs)
        }
        
        role_summary_manager.save_summary(
            role_type=role_type,
            summary_text=summary_text,
            hot_news=hot_news_list,
            new_docs=new_docs_list,
            stats=stats
        )
        
    def force_generate(self, role_type: str = None):
        """Force generate summaries immediately
        
        Args:
            role_type: Specific role to generate for, or None for all roles
        """
        if role_type:
            role_names = {
                'frontend_dev': 'Frontend Developer',
                'backend_dev': 'Backend Developer',
                'mobile_dev': 'Mobile Developer',
                'devops': 'DevOps Engineer',
                'data_scientist': 'Data Scientist',
                'qa_engineer': 'QA Engineer',
                'security': 'Security Engineer',
                'cloud_architect': 'Cloud Architect',
                'ai_ml': 'AI/ML Engineer'
            }
            role_name = role_names.get(role_type, role_type)
            self._generate_role_summary(role_type, role_name)
        else:
            self._generate_all_summaries()


# Global scheduler instance
_summary_scheduler = None


def start_summary_scheduler(pipeline=None, run_immediately: bool = False):
    """Start the global summary scheduler
    
    Args:
        pipeline: RAG pipeline instance for LLM access
        run_immediately: If True, generate summaries immediately on startup.
                        Default is False to avoid rate limiting on restart.
    """
    global _summary_scheduler
    
    if _summary_scheduler is None:
        _summary_scheduler = SummaryScheduler(pipeline)
        
    _summary_scheduler.start(run_immediately=run_immediately)
    return _summary_scheduler


def stop_summary_scheduler():
    """Stop the global summary scheduler"""
    global _summary_scheduler
    
    if _summary_scheduler:
        _summary_scheduler.stop()
        _summary_scheduler = None


def force_generate_summaries(role_type: str = None):
    """Force generate summaries immediately
    
    Args:
        role_type: Specific role to generate for, or None for all roles
    """
    global _summary_scheduler
    
    if _summary_scheduler:
        _summary_scheduler.force_generate(role_type)


def force_generate_summary(pipeline=None, role_type: str = 'developer'):
    """Force generate a summary for testing without using scheduler
    
    This function generates a simple summary WITHOUT calling LLM to avoid rate limits.
    Perfect for testing the summary display UI.
    
    Args:
        pipeline: RAG pipeline instance (optional)
        role_type: Role type for the summary
        
    Returns:
        dict: Summary data with hot_news, new_docs, summary text, and stats
    """
    from rag_chatbot.database import db, role_summary_manager
    
    conn = db.get_connection()
    cursor = conn.cursor()
    
    # Get hottest news (last 7 days, sorted by total views)
    cursor.execute("""
        SELECT id, title, summary, intro_llm_summary, content,
               COALESCE(view_count, 0) + COALESCE(online_view_count, 0) as total_views, 
               published_date, url
        FROM technical_articles
        WHERE role_type = ? 
        AND published_date >= date('now', '-7 days')
        ORDER BY total_views DESC, published_date DESC
        LIMIT 3
    """, (role_type,))
    hot_news = cursor.fetchall()
    
    # Get recently added documents (last 7 days)
    cursor.execute("""
        SELECT id, original_filename, upload_date, metadata, folder
        FROM documents
                WHERE status = 'active'
                    AND upload_date >= date('now', '-7 days')
        ORDER BY upload_date DESC
        LIMIT 3
    """)
    new_docs = cursor.fetchall()
    
    conn.close()
    
    # Build structured data
    hot_news_list = []
    for news_id, title, summary, intro_llm_summary, content, views, pub_date, url in hot_news:
        hot_news_list.append({
            'id': news_id,
            'title': title,
            'summary': (intro_llm_summary or '').strip() or build_article_summary(title, content, fallback_summary=summary),
            'views': views,
            'url': url
        })
    
    new_docs_list = []
    for doc_id, filename, upload_date, metadata, folder in new_docs:
        description = ""
        if metadata:
            try:
                meta_dict = json.loads(metadata)
                description = meta_dict.get('description', '')
            except:
                pass
        
        new_docs_list.append({
            'id': doc_id,
            'filename': filename,
            'upload_date': upload_date,
            'description': description,
            'folder': folder or 'Chung',
            'type': 'company'
        })
    
    # Generate simple summary text (NO LLM call - avoids rate limits)
    summary_text = "Chào mừng bạn trở lại! "
    if hot_news_list:
        summary_text += f"Tuần này có {len(hot_news_list)} tin tức nổi bật: "
        news_titles = [n['title'][:50] + '...' if len(n['title']) > 50 else n['title'] for n in hot_news_list[:3]]
        summary_text += "; ".join(news_titles) + ". "
    if new_docs_list:
        summary_text += f"Có {len(new_docs_list)} tài liệu mới được thêm vào. "
    summary_text += "Hãy khám phá ngay để cập nhật kiến thức mới nhất!"
    
    # Stats
    stats = {
        'hot_news_count': len(hot_news_list),
        'new_docs_count': len(new_docs_list),
        'pending_uploads': 0
    }
    
    # Save to database for caching
    role_summary_manager.save_summary(
        role_type=role_type,
        summary_text=summary_text,
        hot_news=hot_news_list,
        new_docs=new_docs_list,
        stats=stats
    )
    
    logger.info(f"Force generated summary for {role_type}: {len(hot_news_list)} news, {len(new_docs_list)} docs")
    
    return {
        'summary': summary_text,
        'hot_news': hot_news_list,
        'new_docs': new_docs_list,
        'stats': stats,
        'generated_at': datetime.now().isoformat()
    }
