"""
News Fetcher Service
Fetches technical news from RSS feeds and web sources
"""
import feedparser
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
from typing import List, Dict, Optional
import time
from ..database import news_manager, db
from ..pipeline import LocalRAGPipeline


# Role-specific news sources configuration
ROLE_NEWS_SOURCES = {
    'security_engineer': [
        {
            'name': 'CVE Recent',
            'url': 'https://cve.mitre.org/data/downloads/allitems-cvrf-year-2024.xml',
            'type': 'api',
            'description': 'Recent CVE vulnerabilities'
        },
        {
            'name': 'The Hacker News',
            'url': 'https://feeds.feedburner.com/TheHackersNews',
            'type': 'rss',
            'description': 'Cybersecurity news and analysis'
        },
        {
            'name': 'Krebs on Security',
            'url': 'https://krebsonsecurity.com/feed/',
            'type': 'rss',
            'description': 'In-depth security reporting'
        },
        {
            'name': 'Schneier on Security',
            'url': 'https://www.schneier.com/feed/atom/',
            'type': 'rss',
            'description': 'Security and privacy insights'
        }
    ],
    'devops_engineer': [
        {
            'name': 'Kubernetes Blog',
            'url': 'https://kubernetes.io/feed.xml',
            'type': 'rss',
            'description': 'Official Kubernetes updates'
        },
        {
            'name': 'Docker Blog',
            'url': 'https://www.docker.com/blog/feed/',
            'type': 'rss',
            'description': 'Docker news and tutorials'
        },
        {
            'name': 'AWS News',
            'url': 'https://aws.amazon.com/blogs/aws/feed/',
            'type': 'rss',
            'description': 'AWS service announcements'
        },
        {
            'name': 'DevOps.com',
            'url': 'https://devops.com/feed/',
            'type': 'rss',
            'description': 'DevOps best practices'
        }
    ],
    'backend_developer': [
        {
            'name': 'Python Insider',
            'url': 'https://blog.python.org/feeds/posts/default',
            'type': 'rss',
            'description': 'Official Python blog'
        },
        {
            'name': 'Node.js Blog',
            'url': 'https://nodejs.org/en/feed/blog.xml',
            'type': 'rss',
            'description': 'Node.js releases and updates'
        },
        {
            'name': 'Real Python',
            'url': 'https://realpython.com/atom.xml',
            'type': 'rss',
            'description': 'Python tutorials'
        }
    ],
    'frontend_developer': [
        {
            'name': 'React Blog',
            'url': 'https://react.dev/rss.xml',
            'type': 'rss',
            'description': 'React updates and announcements'
        },
        {
            'name': 'CSS-Tricks',
            'url': 'https://css-tricks.com/feed/',
            'type': 'rss',
            'description': 'Web development tips'
        },
        {
            'name': 'Smashing Magazine',
            'url': 'https://www.smashingmagazine.com/feed/',
            'type': 'rss',
            'description': 'Web design and development'
        }
    ],
    'data_scientist': [
        {
            'name': 'PyTorch Blog',
            'url': 'https://pytorch.org/blog/feed.xml',
            'type': 'rss',
            'description': 'PyTorch updates and tutorials'
        },
        {
            'name': 'TensorFlow Blog',
            'url': 'https://blog.tensorflow.org/feeds/posts/default',
            'type': 'rss',
            'description': 'TensorFlow news'
        },
        {
            'name': 'Towards Data Science',
            'url': 'https://towardsdatascience.com/feed',
            'type': 'rss',
            'description': 'Data science articles'
        }
    ],
    'cloud_engineer': [
        {
            'name': 'AWS Blog',
            'url': 'https://aws.amazon.com/blogs/aws/feed/',
            'type': 'rss',
            'description': 'AWS updates'
        },
        {
            'name': 'Google Cloud Blog',
            'url': 'https://cloud.google.com/blog/rss',
            'type': 'rss',
            'description': 'Google Cloud updates'
        },
        {
            'name': 'Azure Blog',
            'url': 'https://azure.microsoft.com/en-us/blog/feed/',
            'type': 'rss',
            'description': 'Microsoft Azure updates'
        }
    ]
}


class NewsFetcher:
    """Fetches and processes technical news articles"""
    
    def __init__(self, pipeline: Optional[LocalRAGPipeline] = None):
        self.pipeline = pipeline
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
    
    def fetch_rss_feed(self, url: str, max_articles: int = 10) -> List[Dict]:
        """Fetch articles from RSS feed"""
        try:
            feed = feedparser.parse(url)
            articles = []
            
            for entry in feed.entries[:max_articles]:
                # Parse published date
                published_date = None
                if hasattr(entry, 'published_parsed') and entry.published_parsed:
                    published_date = datetime(*entry.published_parsed[:6])
                elif hasattr(entry, 'updated_parsed') and entry.updated_parsed:
                    published_date = datetime(*entry.updated_parsed[:6])
                else:
                    published_date = datetime.now()
                
                # Get summary
                summary = ''
                if hasattr(entry, 'summary'):
                    summary = self._clean_html(entry.summary)
                elif hasattr(entry, 'description'):
                    summary = self._clean_html(entry.description)
                
                # Truncate summary to reasonable length
                if len(summary) > 500:
                    summary = summary[:497] + '...'
                
                article = {
                    'title': entry.title if hasattr(entry, 'title') else 'Untitled',
                    'url': entry.link if hasattr(entry, 'link') else '',
                    'summary': summary,
                    'content': '',  # Will be fetched separately if needed
                    'published_date': published_date.strftime('%Y-%m-%d %H:%M:%S')
                }
                
                articles.append(article)
            
            return articles
        
        except Exception as e:
            print(f"Error fetching RSS feed {url}: {e}")
            return []
    
    def _clean_html(self, html_text: str) -> str:
        """Remove HTML tags and clean text"""
        if not html_text:
            return ''
        
        soup = BeautifulSoup(html_text, 'html.parser')
        text = soup.get_text(separator=' ', strip=True)
        # Remove extra whitespace
        text = ' '.join(text.split())
        return text
    
    def fetch_article_content(self, url: str) -> str:
        """Fetch full article content from URL"""
        try:
            response = self.session.get(url, timeout=15)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Remove unwanted elements
            for element in soup(['script', 'style', 'nav', 'footer', 'aside', 'header', 'iframe', 'noscript']):
                element.decompose()
            
            # Remove ads and promotional content
            for ad_class in ['advertisement', 'ad-container', 'promo', 'sidebar', 'related-posts']:
                for ad in soup.find_all(class_=lambda c: c and ad_class in c.lower()):
                    ad.decompose()
            
            # Try multiple strategies to find article content
            content = ''
            
            # Strategy 1: Look for article tag
            article_tag = soup.find('article')
            if article_tag:
                # For The Hacker News specifically, look for article body
                article_body = article_tag.find('div', class_=lambda c: c and 'articlebody' in c.lower() if c else False)
                if article_body:
                    content = article_body.get_text(separator='\n', strip=True)
                else:
                    content = article_tag.get_text(separator='\n', strip=True)
            
            # Strategy 2: Look for main content area
            if not content or len(content) < 500:
                main_content = soup.find('main') or soup.find('div', class_=lambda c: c and ('content' in c.lower() or 'article' in c.lower()) if c else False)
                if main_content:
                    content = main_content.get_text(separator='\n', strip=True)
            
            # Strategy 3: Look for paragraphs within body
            if not content or len(content) < 500:
                paragraphs = soup.find_all('p')
                if len(paragraphs) > 3:
                    content = '\n\n'.join(p.get_text(strip=True) for p in paragraphs if len(p.get_text(strip=True)) > 50)
            
            # Clean up
            lines = [line.strip() for line in content.split('\n') if line.strip()]
            # Remove duplicate lines and very short lines
            seen = set()
            clean_lines = []
            for line in lines:
                if len(line) > 20 and line not in seen:
                    seen.add(line)
                    clean_lines.append(line)
            
            content = '\n'.join(clean_lines)
            
            # Ensure we got meaningful content
            word_count = len(content.split())
            print(f"[FETCH] Extracted {word_count} words from {url[:60]}...")
            
            if word_count < 50:
                print(f"[WARN] Content too short ({word_count} words), may be incomplete")
            
            # Limit content length but keep more for better summaries
            if len(content) > 15000:
                content = content[:15000] + '\n...(content truncated for processing)'
            
            return content
        
        except Exception as e:
            print(f"[ERROR] Failed to fetch article content from {url}: {e}")
            import traceback
            traceback.print_exc()
            return ''
    
    def fetch_news_for_role(self, role_type: str, fetch_content: bool = False) -> int:
        """Fetch news articles for a specific role"""
        if role_type not in ROLE_NEWS_SOURCES:
            print(f"No news sources configured for role: {role_type}")
            return 0
        
        sources = ROLE_NEWS_SOURCES[role_type]
        total_articles = 0
        
        for source_config in sources:
            print(f"Fetching from {source_config['name']}...")
            
            # Get or create source in database
            db_sources = news_manager.get_sources_by_role(role_type)
            source_id = None
            
            for db_source in db_sources:
                if db_source['source_url'] == source_config['url']:
                    source_id = db_source['id']
                    break
            
            if not source_id:
                source_id = news_manager.add_news_source(
                    source_name=source_config['name'],
                    source_url=source_config['url'],
                    source_type=source_config['type'],
                    role_type=role_type
                )
            
            # Fetch articles
            if source_config['type'] == 'rss':
                articles = self.fetch_rss_feed(source_config['url'])
                
                for article in articles:
                    # Optionally fetch full content
                    if fetch_content and article['url']:
                        article['content'] = self.fetch_article_content(article['url'])
                    
                    # Add to database
                    news_manager.add_article(
                        source_id=source_id,
                        title=article['title'],
                        summary=article['summary'],
                        content=article['content'],
                        url=article['url'],
                        published_date=article['published_date'],
                        role_type=role_type
                    )
                    
                    total_articles += 1
                
                # Small delay to be polite
                time.sleep(1)
        
        print(f"Fetched {total_articles} articles for {role_type}")
        return total_articles
    
    def fetch_all_roles(self, fetch_content: bool = False) -> Dict[str, int]:
        """Fetch news for all roles"""
        results = {}
        
        for role_type in ROLE_NEWS_SOURCES.keys():
            count = self.fetch_news_for_role(role_type, fetch_content)
            results[role_type] = count
        
        return results
    
    def embed_articles(self, role_type: str = None, limit: int = 50):
        """Embed article content into vector store for searchability"""
        if not self.pipeline:
            print("No pipeline configured for embedding")
            return
        
        # Get unem bedded articles
        conn = db.get_connection()
        cursor = conn.cursor()
        
        if role_type:
            cursor.execute("""
                SELECT * FROM technical_articles 
                WHERE role_type = ? AND is_embedded = 0 AND content != ''
                LIMIT ?
            """, (role_type, limit))
        else:
            cursor.execute("""
                SELECT * FROM technical_articles 
                WHERE is_embedded = 0 AND content != ''
                LIMIT ?
            """, (limit,))
        
        articles = cursor.fetchall()
        conn.close()
        
        print(f"Embedding {len(articles)} articles...")
        
        for article in articles:
            article_id = article[0]
            title = article[3]
            summary = article[4]
            content = article[5]
            url = article[6]
            
            # Create document text
            doc_text = f"""
Title: {title}
URL: {url}
Type: Technical Article

Summary:
{summary}

Content:
{content}
"""
            
            try:
                # Save as temporary text file and ingest
                import tempfile
                import os
                
                with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False, encoding='utf-8') as f:
                    f.write(doc_text)
                    temp_path = f.name
                
                # Ingest into pipeline
                self.pipeline.store_nodes(input_files=[temp_path])
                
                # Clean up
                os.unlink(temp_path)
                
                # Mark as embedded
                news_manager.mark_article_embedded(article_id)
                print(f"✓ Embedded: {title[:50]}...")
                
            except Exception as e:
                print(f"✗ Error embedding article {article_id}: {e}")
        
        # Rebuild chat engine
        self.pipeline.set_chat_mode()
        print("Chat engine updated with new articles")


def init_default_sources():
    """Initialize default news sources in database"""
    print("Initializing default news sources...")
    
    for role_type, sources in ROLE_NEWS_SOURCES.items():
        for source_config in sources:
            # Check if source already exists
            existing = news_manager.get_sources_by_role(role_type)
            exists = any(s['source_url'] == source_config['url'] for s in existing)
            
            if not exists:
                news_manager.add_news_source(
                    source_name=source_config['name'],
                    source_url=source_config['url'],
                    source_type=source_config['type'],
                    role_type=role_type
                )
                print(f"✓ Added source: {source_config['name']} for {role_type}")
    
    print("Default sources initialized!")


def update_online_view_counts():
    """
    Fetch and update online view counts for articles from external sources.
    For Hacker News articles, we can use the Hacker News API.
    For other sources, we can try to scrape view counts or use API if available.
    """
    print("[NEWS] Updating online view counts...")
    
    conn = db.get_connection()
    cursor = conn.cursor()
    
    # Get all articles with URLs
    cursor.execute("""
        SELECT id, url, title FROM technical_articles 
        WHERE url IS NOT NULL AND url != ''
        ORDER BY published_date DESC
        LIMIT 200
    """)
    
    articles = cursor.fetchall()
    updated_count = 0
    
    for article in articles:
        article_id, url, title = article
        online_views = 0
        
        try:
            # Check if it's a Hacker News article
            if 'ycombinator.com' in url or 'news.ycombinator.com' in url:
                online_views = fetch_hackernews_score(url)
            
            # Update if we got a valid count
            if online_views > 0:
                cursor.execute("""
                    UPDATE technical_articles 
                    SET online_view_count = ?
                    WHERE id = ?
                """, (online_views, article_id))
                updated_count += 1
                
        except Exception as e:
            print(f"Error fetching online views for {url}: {e}")
            continue
        
        # Be polite with rate limiting
        time.sleep(0.5)
    
    conn.commit()
    print(f"[NEWS] Updated online view counts for {updated_count} articles")
    return updated_count


def fetch_hackernews_score(url: str) -> int:
    """
    Fetch the score (upvotes) for a Hacker News article.
    The score represents online engagement.
    """
    try:
        # Extract item ID from URL
        if '/item?id=' in url:
            item_id = url.split('id=')[1].split('&')[0]
        else:
            return 0
        
        # Use Hacker News API
        api_url = f"https://hacker-news.firebaseio.com/v0/item/{item_id}.json"
        response = requests.get(api_url, timeout=5)
        
        if response.status_code == 200:
            data = response.json()
            score = data.get('score', 0)
            descendants = data.get('descendants', 0)  # number of comments
            
            # Combine score and comments for engagement metric
            # Score is weighted more heavily
            online_views = score + (descendants // 2)
            return online_views
        
    except Exception as e:
        print(f"Error fetching HN score: {e}")
    
    return 0


def cleanup_old_articles(retention_days_by_views: dict = None):
    """
    Clean up old articles based on their popularity.
    Articles with more views are retained longer.
    
    Args:
        retention_days_by_views: Dict mapping view thresholds to retention days
                                 e.g., {100: 90, 50: 60, 10: 30, 0: 7}
    """
    if retention_days_by_views is None:
        # Default retention policy: more popular = longer retention
        retention_days_by_views = {
            100: 90,   # 100+ total views: keep for 90 days
            50: 60,    # 50+ total views: keep for 60 days
            20: 45,    # 20+ total views: keep for 45 days
            10: 30,    # 10+ total views: keep for 30 days
            5: 14,     # 5+ total views: keep for 14 days
            0: 7       # Less than 5 views: keep for 7 days
        }
    
    print("[NEWS] Starting article cleanup based on popularity...")
    
    conn = db.get_connection()
    cursor = conn.cursor()
    
    total_deleted = 0
    
    # Process each retention tier
    for min_views in sorted(retention_days_by_views.keys(), reverse=True):
        retention_days = retention_days_by_views[min_views]
        cutoff_date = datetime.now() - timedelta(days=retention_days)
        cutoff_str = cutoff_date.strftime('%Y-%m-%d')
        
        # Find next tier for upper bound
        view_tiers = sorted(retention_days_by_views.keys(), reverse=True)
        tier_index = view_tiers.index(min_views)
        
        if tier_index == 0:
            # Top tier: no upper bound
            cursor.execute("""
                DELETE FROM technical_articles
                WHERE published_date < ?
                AND (view_count + online_view_count) >= ?
            """, (cutoff_str, min_views))
        else:
            # Has upper bound from next tier
            max_views = view_tiers[tier_index - 1]
            cursor.execute("""
                DELETE FROM technical_articles
                WHERE published_date < ?
                AND (view_count + online_view_count) >= ?
                AND (view_count + online_view_count) < ?
            """, (cutoff_str, min_views, max_views))
        
        deleted = cursor.rowcount
        total_deleted += deleted
        
        if deleted > 0:
            print(f"  Deleted {deleted} articles with {min_views}+ views older than {retention_days} days")
    
    conn.commit()
    print(f"[NEWS] Cleanup complete. Total articles deleted: {total_deleted}")
    return total_deleted


# Scheduled fetch function
def scheduled_news_fetch(pipeline: LocalRAGPipeline = None, fetch_content: bool = True):
    """Run periodic news fetch (can be scheduled with cron or APScheduler)"""
    print(f"[{datetime.now()}] Starting scheduled news fetch...")
    
    fetcher = NewsFetcher(pipeline)
    results = fetcher.fetch_all_roles(fetch_content=fetch_content)
    
    print(f"Fetch complete: {results}")
    
    # Embed new articles if pipeline provided
    if pipeline:
        for role_type in results.keys():
            if results[role_type] > 0:
                fetcher.embed_articles(role_type, limit=results[role_type])
    
    # Update online view counts
    update_online_view_counts()
    
    # Cleanup old articles based on popularity
    cleanup_old_articles()
    
    print(f"[{datetime.now()}] News fetch completed!")
