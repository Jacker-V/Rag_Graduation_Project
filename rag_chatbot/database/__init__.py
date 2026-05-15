"""
Database models for the internal knowledge system
"""
import sqlite3
import json
from datetime import datetime
from typing import List, Dict, Optional
from pathlib import Path


class Database:
    """Database handler for the knowledge system"""
    
    def __init__(self, db_path: str = "data/knowledge_system.db"):
        resolved_path = Path(db_path).resolve()
        self.db_path = str(resolved_path)
        resolved_path.parent.mkdir(parents=True, exist_ok=True)
        self.init_database()
    
    def get_connection(self):
        """Get database connection"""
        return sqlite3.connect(self.db_path)
    
    def init_database(self):
        """Initialize database tables"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        # Documents table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS documents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                filename TEXT NOT NULL,
                original_filename TEXT NOT NULL,
                file_type TEXT NOT NULL,
                file_size INTEGER,
                upload_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                uploaded_by TEXT DEFAULT 'admin',
                status TEXT DEFAULT 'active',
                metadata TEXT
            )
        """)
        
        # User reports table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                question TEXT NOT NULL,
                answer TEXT,
                report_type TEXT NOT NULL,
                report_reason TEXT,
                user_comment TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                status TEXT DEFAULT 'pending',
                resolved_at TIMESTAMP,
                resolved_by TEXT,
                resolution_notes TEXT
            )
        """)
        
        # Chat history table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS chat_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                user_id INTEGER,
                user_type TEXT DEFAULT 'user',
                question TEXT NOT NULL,
                answer TEXT NOT NULL,
                sources TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (id)
            )
        """)
        
        # Cross-user cache for common template questions (TTL enforced in application code)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS template_answer_cache (
                cache_key TEXT PRIMARY KEY,
                answer TEXT NOT NULL,
                sources TEXT,
                created_at INTEGER NOT NULL
            )
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_template_answer_cache_created_at ON template_answer_cache(created_at)")
        
        # User roles and preferences table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_roles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER UNIQUE NOT NULL,
                role_type TEXT NOT NULL,
                department TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (id)
            )
        """)
        
        # Technical news sources table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS news_sources (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_name TEXT NOT NULL,
                source_url TEXT NOT NULL,
                source_type TEXT NOT NULL,
                role_type TEXT NOT NULL,
                update_frequency TEXT DEFAULT 'daily',
                is_active INTEGER DEFAULT 1,
                last_fetched TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Technical articles/news table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS technical_articles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_id INTEGER,
                title TEXT NOT NULL,
                summary TEXT,
                intro_llm_summary TEXT,
                intro_llm_summary_updated_at INTEGER,
                content TEXT,
                url TEXT NOT NULL,
                published_date TIMESTAMP,
                role_type TEXT,
                is_embedded INTEGER DEFAULT 0,
                view_count INTEGER DEFAULT 0,
                online_view_count INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (source_id) REFERENCES news_sources (id)
            )
        """)
        
        # Add online_view_count column if it doesn't exist (migration)
        cursor.execute("PRAGMA table_info(technical_articles)")
        columns = [col[1] for col in cursor.fetchall()]
        if 'online_view_count' not in columns:
            cursor.execute("ALTER TABLE technical_articles ADD COLUMN online_view_count INTEGER DEFAULT 0")
            print("[DB] Added online_view_count column to technical_articles")

        # Add intro LLM summary columns (migration)
        if 'intro_llm_summary' not in columns:
            cursor.execute("ALTER TABLE technical_articles ADD COLUMN intro_llm_summary TEXT")
            print("[DB] Added intro_llm_summary column to technical_articles")
        if 'intro_llm_summary_updated_at' not in columns:
            cursor.execute("ALTER TABLE technical_articles ADD COLUMN intro_llm_summary_updated_at INTEGER")
            print("[DB] Added intro_llm_summary_updated_at column to technical_articles")
        
        # Add interaction count columns (migration)
        if 'explain_count' not in columns:
            cursor.execute("ALTER TABLE technical_articles ADD COLUMN explain_count INTEGER DEFAULT 0")
            print("[DB] Added explain_count column to technical_articles")
        if 'summary_count' not in columns:
            cursor.execute("ALTER TABLE technical_articles ADD COLUMN summary_count INTEGER DEFAULT 0")
            print("[DB] Added summary_count column to technical_articles")
        if 'link_click_count' not in columns:
            cursor.execute("ALTER TABLE technical_articles ADD COLUMN link_click_count INTEGER DEFAULT 0")
            print("[DB] Added link_click_count column to technical_articles")
        
        # User-uploaded documents (pending approval)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_documents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                filename TEXT NOT NULL,
                original_filename TEXT NOT NULL,
                file_type TEXT NOT NULL,
                file_size INTEGER,
                uploaded_by INTEGER NOT NULL,
                role_type TEXT,
                description TEXT,
                status TEXT DEFAULT 'pending',
                approved_by INTEGER,
                approved_at TIMESTAMP,
                rejection_reason TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (uploaded_by) REFERENCES users (id),
                FOREIGN KEY (approved_by) REFERENCES users (id)
            )
        """)
        
        # Add folder column to documents tables (migration)
        cursor.execute("PRAGMA table_info(documents)")
        doc_columns = [col[1] for col in cursor.fetchall()]
        if 'folder' not in doc_columns:
            cursor.execute("ALTER TABLE documents ADD COLUMN folder TEXT DEFAULT 'Chung'")
            print("[DB] Added folder column to documents table")
        
        # Add admin_pinned column to documents table (migration)
        if 'admin_pinned' not in doc_columns:
            cursor.execute("ALTER TABLE documents ADD COLUMN admin_pinned INTEGER DEFAULT 0")
            print("[DB] Added admin_pinned column to documents table")
        
        cursor.execute("PRAGMA table_info(user_documents)")
        user_doc_columns = [col[1] for col in cursor.fetchall()]
        if 'folder' not in user_doc_columns:
            cursor.execute("ALTER TABLE user_documents ADD COLUMN folder TEXT DEFAULT 'Chung'")
            print("[DB] Added folder column to user_documents table")
        
        # Document usage tracking table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS document_usage (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                document_id INTEGER NOT NULL,
                document_type TEXT NOT NULL,
                user_id INTEGER,
                action_type TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (document_id) REFERENCES documents (id),
                FOREIGN KEY (user_id) REFERENCES users (id)
            )
        """)
        
        # Document folders configuration table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS document_folders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                folder_name TEXT UNIQUE NOT NULL,
                folder_icon TEXT DEFAULT 'folder',
                display_order INTEGER DEFAULT 0,
                is_active INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Insert default folders if not exist
        default_folders = [
            ('Nhân sự & Chính sách', 'users-cog', 1),
            ('Tài liệu Kỹ thuật', 'code', 2),
            ('Tài liệu Đào tạo', 'graduation-cap', 3),
            ('Tài chính & Ngân sách', 'money-bill-wave', 4),
            ('Chung', 'folder-open', 5)
        ]
        
        for folder_name, icon, order in default_folders:
            cursor.execute("""
                INSERT OR IGNORE INTO document_folders (folder_name, folder_icon, display_order)
                VALUES (?, ?, ?)
            """, (folder_name, icon, order))
        
        # Remove old English folders if they exist
        old_english_folders = ['HR & Policies', 'Technical Documentation', 'Training Materials', 'Finance & Budgets', 'General']
        for old_folder in old_english_folders:
            cursor.execute("DELETE FROM document_folders WHERE folder_name = ?", (old_folder,))
        
        # Clean up: Remove personal documents from main documents table (they should only be in user_documents)
        # Personal documents have uploaded_by starting with 'user_'
        cursor.execute("""
            DELETE FROM documents 
            WHERE uploaded_by LIKE 'user_%'
        """)
        deleted_count = cursor.rowcount
        if deleted_count > 0:
            print(f"[DB] Cleaned up {deleted_count} personal documents from main documents table")
        
        print("[DB] Document folders initialized")
        
        # Admin activity log table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS admin_activity (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                activity_type TEXT NOT NULL,
                description TEXT,
                admin_id INTEGER,
                metadata TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        print("[DB] Admin activity table initialized")
        
        # Cached role summaries table (for periodic pre-generation at 12 AM/PM)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS role_summaries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                role_type TEXT NOT NULL UNIQUE,
                summary_text TEXT NOT NULL,
                hot_news TEXT,
                new_docs TEXT,
                stats TEXT,
                generated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        print("[DB] Role summaries table initialized")
        
        # User pinned documents table (for both company and personal documents)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS pinned_documents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                document_id INTEGER NOT NULL,
                document_type TEXT NOT NULL,
                pinned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user_id, document_id, document_type)
            )
        """)
        print("[DB] Pinned documents table initialized")
        
        self._migrate_chat_history_table(cursor)
        
        conn.commit()
        conn.close()
    
    def _migrate_chat_history_table(self, cursor):
        """Add user_id column to chat_history if it doesn't exist"""
        try:
            # Check if user_id column exists
            cursor.execute("PRAGMA table_info(chat_history)")
            columns = [column[1] for column in cursor.fetchall()]
            
            if 'user_id' not in columns:
                print("Migrating chat_history table to add user_id column...")
                # Add user_id column (SQLite allows adding nullable columns)
                cursor.execute("ALTER TABLE chat_history ADD COLUMN user_id INTEGER")
                print("✓ Migration completed: user_id column added to chat_history")
        except Exception as e:
            print(f"Migration note: {e}")


class DocumentManager:
    """Manager for document operations"""
    
    def __init__(self, db: Database):
        self.db = db
    
    def add_document(
        self,
        filename: str,
        original_filename: str,
        file_type: str,
        file_size: int,
        uploaded_by: str = "admin",
        metadata: Optional[Dict] = None
    ) -> int:
        """Add a new document to the database"""
        conn = self.db.get_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT INTO documents 
            (filename, original_filename, file_type, file_size, uploaded_by, metadata)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            filename,
            original_filename,
            file_type,
            file_size,
            uploaded_by,
            json.dumps(metadata) if metadata else None
        ))
        
        doc_id = cursor.lastrowid
        conn.commit()
        conn.close()
        
        return doc_id
    
    def get_all_documents(self) -> List[Dict]:
        """Get all documents"""
        conn = self.db.get_connection()
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT * FROM documents 
            WHERE status = 'active'
            ORDER BY upload_date DESC
        """)
        
        documents = [dict(row) for row in cursor.fetchall()]
        conn.close()
        
        return documents
    
    def delete_document(self, doc_id: int) -> bool:
        """Soft delete a document"""
        conn = self.db.get_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            UPDATE documents 
            SET status = 'deleted'
            WHERE id = ?
        """, (doc_id,))
        
        success = cursor.rowcount > 0
        conn.commit()
        conn.close()
        
        return success
    
    def get_document(self, doc_id: int) -> Optional[Dict]:
        """Get a specific document"""
        conn = self.db.get_connection()
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute("SELECT * FROM documents WHERE id = ?", (doc_id,))
        row = cursor.fetchone()
        conn.close()
        
        return dict(row) if row else None


class ReportManager:
    """Manager for user report operations"""
    
    def __init__(self, db: Database):
        self.db = db
    
    def create_report(
        self,
        question: str,
        answer: str,
        report_type: str,
        report_reason: str,
        user_comment: Optional[str] = None
    ) -> int:
        """Create a new user report"""
        conn = self.db.get_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT INTO user_reports 
            (question, answer, report_type, report_reason, user_comment)
            VALUES (?, ?, ?, ?, ?)
        """, (question, answer, report_type, report_reason, user_comment))
        
        report_id = cursor.lastrowid
        conn.commit()
        conn.close()
        
        return report_id
    
    def get_all_reports(self, status: Optional[str] = None) -> List[Dict]:
        """Get all reports, optionally filtered by status"""
        conn = self.db.get_connection()
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        if status:
            cursor.execute("""
                SELECT * FROM user_reports 
                WHERE status = ?
                ORDER BY created_at DESC
            """, (status,))
        else:
            cursor.execute("""
                SELECT * FROM user_reports 
                ORDER BY created_at DESC
            """)
        
        reports = [dict(row) for row in cursor.fetchall()]
        conn.close()
        
        return reports
    
    def resolve_report(
        self,
        report_id: int,
        resolved_by: str,
        resolution_notes: Optional[str] = None
    ) -> bool:
        """Mark a report as resolved"""
        conn = self.db.get_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            UPDATE user_reports 
            SET status = 'resolved',
                resolved_at = CURRENT_TIMESTAMP,
                resolved_by = ?,
                resolution_notes = ?
            WHERE id = ?
        """, (resolved_by, resolution_notes, report_id))
        
        success = cursor.rowcount > 0
        conn.commit()
        conn.close()
        
        return success
    
    def get_report(self, report_id: int) -> Optional[Dict]:
        """Get a specific report"""
        conn = self.db.get_connection()
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute("SELECT * FROM user_reports WHERE id = ?", (report_id,))
        row = cursor.fetchone()
        conn.close()
        
        return dict(row) if row else None


class ChatHistoryManager:
    """Manager for chat history operations"""
    
    def __init__(self, db: Database):
        self.db = db
    
    def add_chat(
        self,
        session_id: str,
        question: str,
        answer: str,
        sources: Optional[List[Dict]] = None,
        user_type: str = "user",
        user_id: Optional[int] = None
    ) -> int:
        """Add a chat interaction to history"""
        conn = self.db.get_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT INTO chat_history 
            (session_id, user_id, user_type, question, answer, sources)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            session_id,
            user_id,
            user_type,
            question,
            answer,
            json.dumps(sources) if sources else None
        ))
        
        chat_id = cursor.lastrowid
        conn.commit()
        conn.close()
        
        return chat_id
    
    def get_session_history(self, session_id: str) -> List[Dict]:
        """Get chat history for a session"""
        conn = self.db.get_connection()
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT * FROM chat_history 
            WHERE session_id = ?
            ORDER BY created_at ASC
        """, (session_id,))
        
        history = [dict(row) for row in cursor.fetchall()]
        conn.close()
        
        return history
    
    def get_chat_count(self) -> int:
        """Get total number of chats"""
        conn = self.db.get_connection()
        cursor = conn.cursor()
        
        cursor.execute("SELECT COUNT(*) FROM chat_history")
        count = cursor.fetchone()[0]
        conn.close()
        
        return count
    
    def get_user_history(self, user_id: int) -> List[Dict]:
        """Get all chat history for a specific user"""
        conn = self.db.get_connection()
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT * FROM chat_history 
            WHERE user_id = ?
            ORDER BY created_at DESC
        """, (user_id,))
        
        history = [dict(row) for row in cursor.fetchall()]
        conn.close()
        
        return history
    
    def get_user_chat_count(self, user_id: int) -> int:
        """Get total number of chats for a specific user"""
        conn = self.db.get_connection()
        cursor = conn.cursor()
        
        cursor.execute("SELECT COUNT(*) FROM chat_history WHERE user_id = ?", (user_id,))
        count = cursor.fetchone()[0]
        conn.close()
        
        return count


# Initialize global database instance
db = Database()
document_manager = DocumentManager(db)
report_manager = ReportManager(db)
chat_history_manager = ChatHistoryManager(db)


class UserRoleManager:
    """Manager for user roles and preferences"""
    
    def __init__(self, db: Database):
        self.db = db
    
    def set_user_role(self, user_id: int, role_type: str, department: str = None) -> bool:
        """Set or update user's role"""
        conn = self.db.get_connection()
        cursor = conn.cursor()
        
        # Check if role exists
        cursor.execute("SELECT id FROM user_roles WHERE user_id = ?", (user_id,))
        existing = cursor.fetchone()
        
        if existing:
            cursor.execute("""
                UPDATE user_roles 
                SET role_type = ?, department = ?, updated_at = CURRENT_TIMESTAMP
                WHERE user_id = ?
            """, (role_type, department, user_id))
        else:
            cursor.execute("""
                INSERT INTO user_roles (user_id, role_type, department)
                VALUES (?, ?, ?)
            """, (user_id, role_type, department))
        
        conn.commit()
        conn.close()
        return True
    
    def get_user_role(self, user_id: int) -> Optional[Dict]:
        """Get user's role"""
        conn = self.db.get_connection()
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute("SELECT * FROM user_roles WHERE user_id = ?", (user_id,))
        row = cursor.fetchone()
        conn.close()
        
        return dict(row) if row else None


class NewsManager:
    """Manager for technical news and articles"""
    
    def __init__(self, db: Database):
        self.db = db
    
    def add_news_source(self, source_name: str, source_url: str, source_type: str, 
                        role_type: str, update_frequency: str = 'daily') -> int:
        """Add a new news source"""
        conn = self.db.get_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT INTO news_sources 
            (source_name, source_url, source_type, role_type, update_frequency)
            VALUES (?, ?, ?, ?, ?)
        """, (source_name, source_url, source_type, role_type, update_frequency))
        
        source_id = cursor.lastrowid
        conn.commit()
        conn.close()
        return source_id
    
    def get_sources_by_role(self, role_type: str) -> List[Dict]:
        """Get news sources for a specific role"""
        conn = self.db.get_connection()
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT * FROM news_sources 
            WHERE role_type = ? AND is_active = 1
            ORDER BY source_name
        """, (role_type,))
        
        sources = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return sources
    
    def add_article(self, source_id: int, title: str, summary: str, content: str,
                    url: str, published_date: str, role_type: str) -> int:
        """Add a new article"""
        conn = self.db.get_connection()
        cursor = conn.cursor()
        
        # Check if article already exists (by URL)
        cursor.execute("SELECT id FROM technical_articles WHERE url = ?", (url,))
        existing = cursor.fetchone()
        
        if existing:
            conn.close()
            return existing[0]
        
        cursor.execute("""
            INSERT INTO technical_articles 
            (source_id, title, summary, content, url, published_date, role_type)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (source_id, title, summary, content, url, published_date, role_type))
        
        article_id = cursor.lastrowid
        conn.commit()
        conn.close()
        return article_id
    
    def get_articles_by_role(self, role_type: str, limit: int = 20, sort_by: str = 'date') -> List[Dict]:
        """Get articles for a specific role with configurable sorting.
        
        Args:
            role_type: The role type to filter articles
            limit: Maximum number of articles to return
            sort_by: 'date' for newest first, 'interaction' for most engaged first
        """
        conn = self.db.get_connection()
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # Calculate total interactions: views + explains + summaries + link clicks
        if sort_by == 'interaction':
            order_clause = """
                ORDER BY (COALESCE(a.view_count, 0) + COALESCE(a.online_view_count, 0) + 
                          COALESCE(a.explain_count, 0) + COALESCE(a.summary_count, 0) + 
                          COALESCE(a.link_click_count, 0)) DESC, 
                         a.published_date DESC NULLS LAST
            """
        else:  # default: sort by date
            # Use created_at as fallback for NULL published_date
            order_clause = "ORDER BY COALESCE(a.published_date, a.created_at) DESC"
        
        cursor.execute(f"""
            SELECT a.*, s.source_name,
                   (COALESCE(a.view_count, 0) + COALESCE(a.online_view_count, 0)) as total_views,
                   (COALESCE(a.view_count, 0) + COALESCE(a.online_view_count, 0) + 
                    COALESCE(a.explain_count, 0) + COALESCE(a.summary_count, 0) + 
                    COALESCE(a.link_click_count, 0)) as total_interactions
            FROM technical_articles a
            LEFT JOIN news_sources s ON a.source_id = s.id
            WHERE a.role_type = ?
            {order_clause}
            LIMIT ?
        """, (role_type, limit))
        
        articles = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return articles

    def get_article_by_id(self, article_id: int) -> Optional[Dict]:
        """Fetch a single article by ID."""
        conn = self.db.get_connection()
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT a.*, s.source_name FROM technical_articles a LEFT JOIN news_sources s ON a.source_id = s.id WHERE a.id = ?", (article_id,))
        row = cursor.fetchone()
        conn.close()
        return dict(row) if row else None

    def update_article_content(self, article_id: int, content: str) -> bool:
        """Persist fetched article content."""
        conn = self.db.get_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE technical_articles SET content = ? WHERE id = ?", (content, article_id))
        success = cursor.rowcount > 0
        conn.commit()
        conn.close()
        return success
    
    def mark_article_embedded(self, article_id: int) -> bool:
        """Mark article as embedded in vector store"""
        conn = self.db.get_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            UPDATE technical_articles 
            SET is_embedded = 1
            WHERE id = ?
        """, (article_id,))
        
        success = cursor.rowcount > 0
        conn.commit()
        conn.close()
        return success
    
    def increment_view_count(self, article_id: int) -> bool:
        """Increment internal article view count"""
        conn = self.db.get_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            UPDATE technical_articles 
            SET view_count = view_count + 1
            WHERE id = ?
        """, (article_id,))
        
        conn.commit()
        conn.close()
        return True
    
    def increment_explain_count(self, article_id: int) -> bool:
        """Increment explain action count for an article"""
        conn = self.db.get_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            UPDATE technical_articles 
            SET explain_count = COALESCE(explain_count, 0) + 1
            WHERE id = ?
        """, (article_id,))
        
        conn.commit()
        conn.close()
        return True
    
    def increment_summary_count(self, article_id: int) -> bool:
        """Increment summary action count for an article"""
        conn = self.db.get_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            UPDATE technical_articles 
            SET summary_count = COALESCE(summary_count, 0) + 1
            WHERE id = ?
        """, (article_id,))
        
        conn.commit()
        conn.close()
        return True
    
    def increment_link_click_count(self, article_id: int) -> bool:
        """Increment link click count for an article"""
        conn = self.db.get_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            UPDATE technical_articles 
            SET link_click_count = COALESCE(link_click_count, 0) + 1
            WHERE id = ?
        """, (article_id,))
        
        conn.commit()
        conn.close()
        return True
    
    def update_online_view_count(self, article_url: str, online_views: int) -> bool:
        """Update online view count for an article by URL"""
        conn = self.db.get_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            UPDATE technical_articles 
            SET online_view_count = ?
            WHERE url = ?
        """, (online_views, article_url))
        
        success = cursor.rowcount > 0
        conn.commit()
        conn.close()
        return success

    def find_article_by_title(self, title_query: str) -> Optional[Dict]:
        """Find a single article whose title matches the provided text."""
        if not title_query:
            return None

        conn = self.db.get_connection()
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT a.*, s.source_name
            FROM technical_articles a
            LEFT JOIN news_sources s ON a.source_id = s.id
            WHERE LOWER(a.title) LIKE LOWER(?)
            ORDER BY a.published_date DESC
            LIMIT 1
            """,
            (f"%{title_query}%",)
        )

        row = cursor.fetchone()
        conn.close()
        return dict(row) if row else None


class UserDocumentManager:
    """Manager for user-uploaded documents pending approval"""
    
    def __init__(self, db: Database):
        self.db = db
        # Auth database stores user profile information (username/full name)
        base_path = Path(self.db.db_path)
        self.auth_db_path = str(base_path.with_name('knowledge_base.db'))

    def _get_user_info_map(self, user_ids: List[int], _retry: bool = False) -> Dict[int, Dict]:
        """Fetch user info for provided IDs from authentication database."""
        unique_ids = sorted({uid for uid in user_ids if uid})
        if not unique_ids:
            return {}

        auth_path = Path(self.auth_db_path)
        if not auth_path.exists():
            return {}

        try:
            conn = sqlite3.connect(self.auth_db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            placeholders = ','.join('?' for _ in unique_ids)
            cursor.execute(
                f"SELECT id, username, full_name, email FROM users WHERE id IN ({placeholders})",
                tuple(unique_ids)
            )
            user_map = {row['id']: dict(row) for row in cursor.fetchall()}
            conn.close()
            return user_map
        except sqlite3.OperationalError as exc:
            message = str(exc).lower()
            if "no such table" in message and "users" in message and not _retry:
                try:
                    from rag_chatbot.auth import AuthManager
                    AuthManager(self.auth_db_path)
                    return self._get_user_info_map(user_ids, _retry=True)
                except Exception as bootstrap_err:
                    print(f"Warning: could not initialize auth DB: {bootstrap_err}")
            print(f"Warning: could not load uploader info: {exc}")
            return {}
        except Exception as e:
            print(f"Warning: could not load uploader info: {e}")
            return {}

    def _attach_uploader_metadata(self, documents: List[Dict]) -> List[Dict]:
        """Add uploader_name/email fields using auth database (best effort)."""
        user_ids = [doc.get('uploaded_by') for doc in documents if doc.get('uploaded_by')]
        user_map = self._get_user_info_map(user_ids)
        for doc in documents:
            uploader_id = doc.get('uploaded_by')
            user = user_map.get(uploader_id)
            if user:
                full_name = user.get('full_name')
                username = user.get('username')
                doc['uploader_name'] = full_name or username or f"User #{uploader_id}"
                doc['uploader_username'] = username
                doc['uploader_email'] = user.get('email')
            else:
                doc['uploader_name'] = f"User #{uploader_id}" if uploader_id else 'Unknown'
                doc['uploader_username'] = None
                doc['uploader_email'] = None
        return documents
    
    def add_user_document(self, filename: str, original_filename: str, file_type: str,
                          file_size: int, uploaded_by: int, role_type: str, 
                          description: str = None) -> int:
        """Add a user-uploaded document"""
        conn = self.db.get_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT INTO user_documents 
            (filename, original_filename, file_type, file_size, uploaded_by, role_type, description)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (filename, original_filename, file_type, file_size, uploaded_by, role_type, description))
        
        doc_id = cursor.lastrowid
        conn.commit()
        conn.close()
        return doc_id
    
    def get_pending_documents(self) -> List[Dict]:
        """Get all documents pending approval"""
        conn = self.db.get_connection()
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT * FROM user_documents 
            WHERE status = 'pending'
            ORDER BY created_at DESC
        """)
        
        documents = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return self._attach_uploader_metadata(documents)
    
    def get_user_documents(self, user_id: int) -> List[Dict]:
        """Get all documents uploaded by a user"""
        conn = self.db.get_connection()
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT * FROM user_documents 
            WHERE uploaded_by = ?
            ORDER BY created_at DESC
        """, (user_id,))
        
        documents = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return self._attach_uploader_metadata(documents)
    
    def approve_document(self, doc_id: int, approved_by: int) -> bool:
        """Approve a user document"""
        conn = self.db.get_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            UPDATE user_documents 
            SET status = 'approved', approved_by = ?, approved_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (approved_by, doc_id))
        
        success = cursor.rowcount > 0
        conn.commit()
        conn.close()
        return success
    
    def reject_document(self, doc_id: int, approved_by: int, reason: str) -> bool:
        """Reject a user document"""
        conn = self.db.get_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            UPDATE user_documents 
            SET status = 'rejected', approved_by = ?, approved_at = CURRENT_TIMESTAMP,
                rejection_reason = ?
            WHERE id = ?
        """, (approved_by, reason, doc_id))
        
        success = cursor.rowcount > 0
        conn.commit()
        conn.close()
        return success
    
    def get_approved_documents_by_role(self, role_type: str) -> List[Dict]:
        """Get all approved documents for a role"""
        conn = self.db.get_connection()
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT * FROM user_documents 
            WHERE status = 'approved' AND role_type = ?
            ORDER BY (approved_at IS NULL), approved_at DESC, created_at DESC
        """, (role_type,))
        
        documents = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return self._attach_uploader_metadata(documents)
    
    def get_document(self, doc_id: int) -> Optional[Dict]:
        """Get a specific user document"""
        conn = self.db.get_connection()
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute("SELECT * FROM user_documents WHERE id = ?", (doc_id,))
        row = cursor.fetchone()
        conn.close()
        
        return dict(row) if row else None


def ensure_folder_exists(folder_name: str):
    """Ensure a folder exists in the document_folders table"""
    if not folder_name or folder_name.strip() == '':
        return
    
    conn = db.get_connection()
    cursor = conn.cursor()
    
    try:
        # Check if folder exists
        cursor.execute("SELECT id FROM document_folders WHERE folder_name = ?", (folder_name,))
        if not cursor.fetchone():
            # Get max display order
            cursor.execute("SELECT MAX(display_order) FROM document_folders")
            max_order = cursor.fetchone()[0] or 0
            
            # Insert new folder
            cursor.execute("""
                INSERT INTO document_folders (folder_name, folder_icon, display_order)
                VALUES (?, 'folder', ?)
            """, (folder_name, max_order + 1))
            conn.commit()
            print(f"[DB] Created new folder: {folder_name}")
    except Exception as e:
        print(f"[DB] Error ensuring folder exists: {e}")
    finally:
        conn.close()


class RoleSummaryManager:
    """Manager for pre-generated role summaries"""
    
    def __init__(self, database: Database):
        self.db = database
    
    def save_summary(self, role_type: str, summary_text: str, hot_news: List, new_docs: List, stats: Dict) -> bool:
        """Save a pre-generated summary for a role"""
        conn = self.db.get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute("""
                INSERT OR REPLACE INTO role_summaries 
                (role_type, summary_text, hot_news, new_docs, stats, generated_at)
                VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            """, (
                role_type,
                summary_text,
                json.dumps(hot_news),
                json.dumps(new_docs),
                json.dumps(stats)
            ))
            conn.commit()
            return True
        except Exception as e:
            print(f"[DB] Error saving role summary: {e}")
            return False
        finally:
            conn.close()
    
    def get_summary(self, role_type: str) -> Optional[Dict]:
        """Get the cached summary for a role"""
        conn = self.db.get_connection()
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT * FROM role_summaries 
            WHERE role_type = ?
        """, (role_type,))
        
        row = cursor.fetchone()
        conn.close()
        
        if not row:
            return None
        
        result = dict(row)
        # Parse JSON fields
        try:
            result['hot_news'] = json.loads(result['hot_news']) if result['hot_news'] else []
            result['new_docs'] = json.loads(result['new_docs']) if result['new_docs'] else []
            result['stats'] = json.loads(result['stats']) if result['stats'] else {}
        except:
            pass
        
        return result
    
    def get_all_role_types(self) -> List[str]:
        """Get all unique role types that have articles"""
        conn = self.db.get_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT DISTINCT role_type FROM technical_articles
            WHERE role_type IS NOT NULL
        """)
        
        roles = [row[0] for row in cursor.fetchall()]
        conn.close()
        return roles


# Initialize global managers
user_role_manager = UserRoleManager(db)
news_manager = NewsManager(db)
user_document_manager = UserDocumentManager(db)
role_summary_manager = RoleSummaryManager(db)
