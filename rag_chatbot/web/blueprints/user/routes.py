"""
Flask backend API for the User Interface
Serves the HTML UI and provides REST API endpoints for:
- Querying the chatbot
- Getting document list
- Viewing statistics
- Submitting reports
- User authentication
"""
import os
import json
import sqlite3
import time
import hashlib
import re
from typing import Dict
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv(override=True)

from flask import Blueprint, render_template, request, jsonify, send_from_directory, Response, stream_with_context, redirect
from rag_chatbot.logger import Logger
from rag_chatbot.database import report_manager, chat_history_manager, document_manager, news_manager
from rag_chatbot.chat_storage import chat_storage
from rag_chatbot.query_optimizer import extract_document_from_query, translate_query_to_vietnamese, should_use_vietnamese_response
from functools import wraps
import uuid
import sys
from pathlib import Path
import asyncio

# Set offline mode for HuggingFace
os.environ['HF_HUB_OFFLINE'] = '1'
os.environ['TRANSFORMERS_OFFLINE'] = '1'

def _find_project_root(start: Path) -> Path:
    """Find repo root by walking up until the UI folder is found."""
    current = start
    for _ in range(10):
        if (current / 'UI').exists():
            return current
        current = current.parent
    return start.parent


PROJECT_ROOT = _find_project_root(Path(__file__).resolve())

# Absolute paths used by routes
UI_DIR = str(PROJECT_ROOT / 'UI')
DB_PATH = str(PROJECT_ROOT / 'data' / 'knowledge_base.db')
DATA_DIR = str(PROJECT_ROOT / 'data' / 'data')
os.makedirs(DATA_DIR, exist_ok=True)


def _env_truthy(name: str) -> bool:
    return os.environ.get(name, '').strip().lower() in {'1', 'true', 'yes'}


def _cookie_secure() -> bool:
    # request.is_secure will reflect X-Forwarded-Proto when ProxyFix is enabled.
    return request.is_secure


def _https_required_error_response():
    host = (request.host or '').split(':', 1)[0].strip()
    if _env_truthy('BEHIND_PROXY'):
        host = (os.environ.get('USER_DOMAIN') or host).strip() or host
    hint = f"Please access via https://{host}/login (do not use :7860/:7861)."
    return jsonify({'success': False, 'error': hint}), 400


def _cookie_domain() -> str | None:
    """Return a shared cookie domain for admin/user subdomains.

    See admin blueprint for rationale. This prevents losing the session when
    bouncing between USER_DOMAIN and ADMIN_DOMAIN behind HTTPS.
    """

    admin_domain = (os.environ.get('ADMIN_DOMAIN', '') or '').strip().lower()
    user_domain = (os.environ.get('USER_DOMAIN', '') or '').strip().lower()
    if not admin_domain or not user_domain:
        return None

    for host in (admin_domain, user_domain):
        if host in {'localhost', '127.0.0.1'}:
            return None
        if host.replace('.', '').isdigit():
            return None

    admin_parts = [p for p in admin_domain.split('.') if p]
    user_parts = [p for p in user_domain.split('.') if p]

    common = []
    for a, b in zip(reversed(admin_parts), reversed(user_parts)):
        if a != b:
            break
        common.append(a)

    if len(common) < 2:
        return None

    suffix = '.'.join(reversed(common))

    # duckdns.org is commonly treated as a public suffix (shared hosting).
    # Browsers may reject cookies scoped to it. Fall back to host-only cookies.
    if suffix == 'duckdns.org':
        return None

    # Only set Domain if the current request host is within that suffix.
    # This avoids breaking localhost/dev when ADMIN_DOMAIN/USER_DOMAIN are set.
    request_host = (request.host or '').split(':', 1)[0].strip().lower()
    if not request_host or not request_host.endswith(suffix):
        return None

    return '.' + suffix


def _public_admin_url() -> str:
    explicit = os.environ.get('ADMIN_PUBLIC_URL', '').strip()
    if explicit:
        return explicit.rstrip('/') + '/'

    if _env_truthy('BEHIND_PROXY'):
        domain = os.environ.get('ADMIN_DOMAIN', '').strip()
        if domain:
            return f"{request.scheme}://{domain.rstrip('/')}/admin"

    host = request.host.rsplit(':', 1)[0]
    return f"http://{host}:7860/admin"

# Blueprint (keeps existing @app.route usage)
app = Blueprint('user', __name__)

# Logger is still module-scoped
logger = Logger("logging.log")

# Injected by app factory
pipeline = None
auth_manager = None


def init_dependencies(*, pipeline_instance, auth_manager_instance):
    global pipeline, auth_manager
    pipeline = pipeline_instance
    auth_manager = auth_manager_instance

# Store session data
sessions = {}


def chunk_text(text: str, chunk_size: int = 80):
    """Yield small chunks of text for streaming responses."""
    for i in range(0, len(text), chunk_size):
        yield text[i:i+chunk_size]


def get_original_filename(uuid_filename: str) -> str:
    """Convert UUID-prefixed filename to original filename.
    
    Example: 'e0882bb0-aa40-4aaa-abdf-c86a396ad1fc_Chinh-sach-nghi-phep.docx' 
             -> 'Chinh-sach-nghi-phep.docx'
    """
    if not uuid_filename:
        return uuid_filename
    
    # First try to look up in database
    try:
        from rag_chatbot.database import document_manager, db
        
        # Check company documents
        docs = document_manager.get_all_documents()
        for doc in docs:
            if doc.get('filename') == uuid_filename:
                return doc.get('original_filename') or uuid_filename
        
        # Check personal documents
        conn = db.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT original_filename FROM user_documents WHERE filename = ?", (uuid_filename,))
        row = cursor.fetchone()
        conn.close()
        if row and row[0]:
            return row[0]
    except Exception:
        pass
    
    # Fallback: Remove UUID prefix pattern (xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx_)
    import re
    uuid_pattern = r'^[a-f0-9]{8}-?[a-f0-9]{4}-?[a-f0-9]{4}-?[a-f0-9]{4}-?[a-f0-9]{12}_'
    cleaned = re.sub(uuid_pattern, '', uuid_filename, flags=re.IGNORECASE)
    return cleaned if cleaned else uuid_filename


def normalize_selected_filenames(selected_docs):
    """Extract unique filenames from the selected documents payload."""
    if not selected_docs:
        return []

    filenames = []
    seen = set()

    for doc in selected_docs:
        if not isinstance(doc, dict):
            continue
        raw_name = (doc.get('filename') or doc.get('file_name') or '').strip()
        if not raw_name:
            continue
        base_name = os.path.basename(raw_name)
        if base_name and base_name not in seen:
            seen.add(base_name)
            filenames.append(base_name)

    return filenames


def record_chat_interaction(session_id: str, question: str, answer: str, sources, user_id):
    """Persist chat data in both the in-memory session cache and storage layers."""
    sources = sources or []

    if session_id not in sessions:
        sessions[session_id] = {}

    sessions[session_id]['last_response'] = {
        'question': question,
        'answer': answer,
        'sources': sources
    }

    chat_history_manager.add_chat(
        session_id=session_id,
        question=question,
        answer=answer,
        sources=sources,
        user_type="user",
        user_id=user_id
    )

    if user_id:
        chat_storage.save_chat(
            user_id=user_id,
            question=question,
            answer=answer,
            sources=sources,
            session_id=session_id
        )


def extract_news_query(message: str):
    if not message:
        return None
    lowered = message.lower()
    triggers = [
        "tell me more about",
        "chi tiết về",
        "hãy cho tôi biết thêm về",
        "news:"
    ]
    if not any(trigger in lowered for trigger in triggers):
        return None
    for trigger in triggers:
        idx = lowered.find(trigger)
        if idx != -1:
            candidate = message[idx + len(trigger):].strip(" :\"'“”")
            if candidate:
                return candidate
    return message.strip()


def get_news_article_answer(message: str):
    """Return a canned response sourced from the news database if applicable."""
    query = extract_news_query(message)
    if not query:
        return None

    article = news_manager.find_article_by_title(query)
    if not article:
        return None

    answer = build_article_summary(article)
    source_name = article.get('source_name') or 'Tech News'
    published = article.get('published_date') or 'Unknown date'
    link = article.get('url')

    return {
        'answer': answer,
        'sources': [{
            'filename': f"{source_name} article",
            'page': published,
            'score': 1.0,
            'link': link
        }]
    }


PROMO_SNIPPET_PATTERNS = [
    "5 ways to secure containers",
    "containers move fast",
    "manage container risk at scale",
    "they're created and removed in seconds"
]


def is_placeholder_snippet(text: str | None) -> bool:
    """Check if text is just a promotional snippet, not actual article content."""
    if not text:
        return False
    lowered = text.lower()
    # Must have at least 2 promo patterns to be considered placeholder
    matches = sum(1 for pattern in PROMO_SNIPPET_PATTERNS if pattern in lowered)
    return matches >= 2


def _extract_sentences(text: str, max_sentences: int = 6) -> list[str]:
    if not text:
        return []
    sentences = re.split(r'(?<=[.!?])\s+', text.strip())
    results = []
    for sentence in sentences:
        cleaned = sentence.strip()
        if len(cleaned.split()) < 4:
            continue
        results.append(cleaned)
        if len(results) >= max_sentences:
            break
    return results


def _prepare_article_chunk(content: str, limit: int = 6000) -> str:
    if not content or is_placeholder_snippet(content):
        return ''
    text = re.sub(r'\s+', ' ', content).strip()
    if len(text) <= limit:
        return text
    truncated = text[:limit]
    last_period = truncated.rfind('. ')
    if last_period > 2000:
        truncated = truncated[:last_period+1]
    return truncated + "\n...(article truncated for brevity)"


def build_article_summary(article: Dict, content_override: str | None = None) -> str:
    """Create a human-friendly summary for a news article."""
    title = article.get('title', 'this article')
    base_summary = (article.get('summary') or '').strip()
    if is_placeholder_snippet(base_summary):
        base_summary = ''

    content_candidate = content_override or article.get('content') or ''
    if is_placeholder_snippet(content_candidate):
        content_candidate = ''

    content = content_candidate.strip()
    sentences = _extract_sentences(content, max_sentences=10)
    key_points = sentences[:6]

    paragraphs = []

    lead_sentence = ''
    if base_summary and len(base_summary.split()) > 10:
        lead_sentence = base_summary
    elif sentences:
        lead_sentence = sentences[0]

    if lead_sentence:
        paragraphs.append(f"**{title}** — {lead_sentence}" if title.lower() not in lead_sentence.lower() else lead_sentence)
    elif title:
        paragraphs.append(f"**{title}** — Key highlights forthcoming once we have more details.")

    if key_points and len(key_points) > 1:
        supporting_text = " ".join(key_points[1:])
        if supporting_text:
            paragraphs.append(supporting_text)

    metadata_lines = []
    source_name = article.get('source_name') or article.get('source')
    published = article.get('published_date')
    link = article.get('url')
    if source_name or published:
        parts = [part for part in [source_name, published] if part]
        metadata_lines.append(' • '.join(parts))
    if link:
        metadata_lines.append(link)

    if metadata_lines:
        paragraphs.append("Source: " + " | ".join(metadata_lines))

    return "\n\n".join(paragraphs)


def build_structured_brief(article: Dict, raw_text: str) -> str:
    usable_text = raw_text if not is_placeholder_snippet(raw_text) else ''
    sentences = _extract_sentences(usable_text, max_sentences=10)
    if not sentences:
        return ''

    overview = sentences[:2]
    findings = sentences[2:6]
    impact = sentences[6:8]
    recommendations = sentences[8:10]

    paragraphs = []
    title = article.get('title', 'this article')

    if overview:
        paragraphs.append(f"**{title}** — {' '.join(overview)}")

    if findings:
        paragraphs.append("What stands out: " + " ".join(findings))

    if impact:
        paragraphs.append("Why it matters: " + " ".join(impact))

    if recommendations:
        paragraphs.append("Suggested focus: " + " ".join(recommendations))

    return "\n\n".join(paragraphs)


def generate_llm_article_summary(article: Dict, content: str) -> str:
    """Use the configured LLM to build a deeper summary from raw article text."""
    primary_text = '' if is_placeholder_snippet(content) else (content or '')
    cleaned_content = _prepare_article_chunk(primary_text)
    if not cleaned_content:
        fallback = (
            article.get('summary') or
            article.get('content_snippet') or
            article.get('description') or
            ''
        )
        cleaned_content = _prepare_article_chunk(fallback, limit=2000)
    if not cleaned_content:
        print('[WARN] No usable content for LLM article summarization')
        return ''

    title = article.get('title') or 'this article'
    source_name = article.get('source_name') or article.get('source') or 'Tech News'
    published = article.get('published_date') or 'Unknown date'

    print(f'[INFO] Summarizing article: {title[:80]}...')
    print(f'[INFO] Content length for LLM: {len(cleaned_content)} chars')

    prompt = (
        "You are a cybersecurity analyst. Read the following news article and provide a comprehensive,"
        " natural summary that helps readers understand what happened, why it matters, and what they should know.\n\n"
        "Write in a clear, informative style - NOT in a rigid format. Explain the story naturally as if briefing a colleague.\n\n"
        f"Article: {title}\n"
        f"Source: {source_name}\n"
        f"Date: {published}\n\n"
        "Content:\n" + cleaned_content + "\n\n"
        "Provide a detailed summary covering:\n"
        "- What happened (the main story/incident/announcement)\n"
        "- Technical details and important specifics\n"
        "- Why this matters and potential impact\n"
        "- Any recommendations or actions mentioned\n\n"
        "Write naturally and comprehensively. Use paragraphs, not bullet points."
    )

    # Use the correct LLM based on configuration
    llm = pipeline._default_model
    if not llm:
        print('[WARN] LLM not initialized for article summary request')
        return ''

    try:
        print('[INFO] Calling LLM for article summary...')
        result = llm.complete(prompt)
        text = getattr(result, 'text', '') if result is not None else ''
        output = (text or '').strip()
        print(f'[INFO] LLM returned {len(output)} chars')
        return output
    except Exception as exc:
        print(f'[ERROR] LLM article summary failed: {exc}')
        import traceback
        traceback.print_exc()
        return ''


SOURCE_TOKEN_PATTERN = re.compile(r'\w+')


def _extract_news_url_from_node_text(text: str) -> str | None:
    if not text:
        return None
    # The news ingestion stores a text blob with a line like: "URL: https://..."
    match = re.search(r'^\s*URL:\s*(https?://\S+)\s*$', text, flags=re.MULTILINE)
    if not match:
        return None
    return match.group(1).strip()


def _lookup_news_metadata_by_url(url: str) -> dict | None:
    if not url:
        return None
    try:
        from rag_chatbot.database import db
        conn = db.get_connection()
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT a.*, s.source_name
            FROM technical_articles a
            LEFT JOIN news_sources s ON a.source_id = s.id
            WHERE a.url = ?
            LIMIT 1
            """,
            (url,),
        )
        row = cursor.fetchone()
        conn.close()
        return dict(row) if row else None
    except Exception:
        return None


def select_relevant_sources(answer_text: str, source_nodes, max_sources: int = 2):
    """Return the most relevant source documents for a response."""
    if not source_nodes:
        return []

    # When multiple files are selected, picking sources by word-overlap with the
    # generated answer is unstable and can select the wrong file. Instead:
    # - Prefer the retriever score from the RAG engine
    # - Deduplicate per file, keeping the best-scoring chunk per file
    # - Detect embedded news chunks and show the correct news source label

    best_by_key: dict[str, dict] = {}
    news_cache: dict[str, dict | None] = {}

    for node in source_nodes:
        base_node = getattr(node, 'node', None)
        metadata = (
            getattr(base_node, 'metadata', None)
            or getattr(node, 'metadata', {})
            or {}
        )
        source_text = getattr(base_node, 'text', '') or ''
        retriever_score = float(getattr(node, 'score', 0.0) or 0.0)

        # Page label for documents (best-effort)
        page_label = (
            metadata.get('page_label')
            or metadata.get('page_number')
            or metadata.get('page')
        )

        # News detection: nodes created from news ingestion include URL line.
        news_url = _extract_news_url_from_node_text(source_text)
        if news_url:
            if news_url not in news_cache:
                news_cache[news_url] = _lookup_news_metadata_by_url(news_url)
            article = news_cache.get(news_url) or {}
            source_name = (article.get('source_name') or article.get('source') or 'Tech News').strip()
            published = (article.get('published_date') or 'Unknown date')
            display_filename = f"{source_name} article"
            display_page = published
            key = f"news::{news_url}"
        else:
            uuid_filename = (
                metadata.get('file_name')
                or metadata.get('file_path')
                or metadata.get('source')
                or 'Unknown'
            )
            display_filename = get_original_filename(os.path.basename(str(uuid_filename)))
            display_page = page_label
            key = f"doc::{display_filename}"

        current = best_by_key.get(key)
        if (current is None) or (retriever_score > float(current.get('score', 0.0) or 0.0)):
            best_by_key[key] = {
                'filename': display_filename,
                'page': display_page,
                'score': retriever_score,
            }

    ranked = sorted(best_by_key.values(), key=lambda x: float(x.get('score', 0.0) or 0.0), reverse=True)
    return ranked[: max_sources or 0]


def format_llm_error_message(error_text: str):
    """Return a user-friendly message and HTTP status for LLM errors."""
    fallback = "Mô hình AI không thể tạo phản hồi ngay bây giờ. Vui lòng thử lại sau."
    status_code = 500
    if not error_text:
        return fallback, status_code
    lowered = error_text.lower()
    if '503' in error_text or 'unavailable' in lowered or 'overloaded' in lowered:
        return "Mô hình AI đang quá tải. Vui lòng đợi vài giây và thử lại.", 503
    if 'deadline' in lowered or 'timeout' in lowered:
        return "Yêu cầu AI mất quá lâu để phản hồi. Vui lòng thử lại câu hỏi.", 504
    if 'rate limit' in lowered or 'too many requests' in lowered or '429' in error_text or 'ratelimitreached' in lowered:
        return "⚠️ Đã đạt giới hạn API hôm nay. Hệ thống sử dụng GitHub Models miễn phí nên có giới hạn số lượng câu hỏi/ngày. Vui lòng thử lại sau vài giờ hoặc ngày mai.", 429
    return fallback, status_code


# Authentication decorator (optional for user interface - for future use)
def require_auth(optional=False):
    """Decorator to optionally require authentication"""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            # Get token from Authorization header or cookie
            auth_header = request.headers.get('Authorization')
            token = None
            
            if auth_header and auth_header.startswith('Bearer '):
                token = auth_header.split(' ')[1]
            else:
                token = request.cookies.get('session_token')
            
            if token:
                # Validate session
                is_valid, user_info = auth_manager.validate_session(token)
                if is_valid:
                    request.user = user_info
                else:
                    request.user = {}
                    if not optional:
                        return jsonify({'success': False, 'error': 'Invalid or expired session'}), 401
            else:
                request.user = {}
                if not optional:
                    return jsonify({'success': False, 'error': 'Authentication required'}), 401
            
            return f(*args, **kwargs)
        return decorated_function
    return decorator


def require_internal_service_token(f):
    """Decorator to protect internal-only endpoints.

    Requires INTERNAL_SERVICE_TOKEN and either:
      - Authorization: Bearer <token>
      - X-Internal-Token: <token>
    """

    @wraps(f)
    def decorated_function(*args, **kwargs):
        expected = os.environ.get('INTERNAL_SERVICE_TOKEN', '').strip()
        if not expected:
            return jsonify({'success': False, 'error': 'Internal service token not configured'}), 503

        auth_header = (request.headers.get('Authorization') or '').strip()
        token = (request.headers.get('X-Internal-Token') or '').strip()

        if not token and auth_header.lower().startswith('bearer '):
            token = auth_header.split(' ', 1)[1].strip()

        if not token or token != expected:
            return jsonify({'success': False, 'error': 'Unauthorized'}), 401

        return f(*args, **kwargs)

    return decorated_function


def _safe_text_snippet(text: str, limit: int = 800) -> str:
    text = (text or '').strip()
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + '…'


def _ensure_pipeline_ready_for_search() -> bool:
    try:
        if pipeline is None:
            return False
        if pipeline._query_engine is None:
            pipeline._initialize_existing_documents()
        return True
    except Exception as exc:
        print(f"[INTERNAL_TOOLS] Pipeline init failed: {exc}")
        return False


@app.route('/api/internal/tools/documents', methods=['GET'])
@require_internal_service_token
def internal_list_documents():
    """Internal tool: list documents (company + approved personal)."""
    try:
        from rag_chatbot.database import document_manager, user_document_manager

        company_docs = document_manager.get_all_documents() or []
        personal_docs = []
        try:
            # Best-effort: list all approved personal documents across roles.
            from rag_chatbot.database import db
            conn = db.get_connection()
            conn.row_factory = None
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT id, filename, original_filename, file_type, file_size, uploaded_by, role_type, status,
                       created_at, approved_at
                FROM user_documents
                WHERE status = 'approved'
                ORDER BY (approved_at IS NULL), approved_at DESC, created_at DESC
                """
            )
            rows = cursor.fetchall() or []
            conn.close()
            for row in rows:
                personal_docs.append(
                    {
                        'id': row[0],
                        'filename': row[1],
                        'original_filename': row[2],
                        'file_type': row[3],
                        'file_size': row[4],
                        'uploaded_by': row[5],
                        'role_type': row[6],
                        'status': row[7],
                        'created_at': row[8],
                        'approved_at': row[9],
                    }
                )
            personal_docs = user_document_manager._attach_uploader_metadata(personal_docs)  # best-effort
        except Exception as exc:
            print(f"[INTERNAL_TOOLS] Personal docs listing failed: {exc}")

        out = []
        for doc in company_docs:
            out.append(
                {
                    'document_type': 'company',
                    'id': doc.get('id'),
                    'filename': doc.get('filename'),
                    'original_filename': doc.get('original_filename'),
                    'file_type': doc.get('file_type'),
                    'file_size': doc.get('file_size'),
                    'uploaded_by': doc.get('uploaded_by'),
                    'upload_date': doc.get('upload_date'),
                    'status': doc.get('status'),
                }
            )
        for doc in personal_docs:
            out.append(
                {
                    'document_type': 'personal',
                    'id': doc.get('id'),
                    'filename': doc.get('filename'),
                    'original_filename': doc.get('original_filename'),
                    'file_type': doc.get('file_type'),
                    'file_size': doc.get('file_size'),
                    'uploaded_by': doc.get('uploaded_by'),
                    'role_type': doc.get('role_type'),
                    'status': doc.get('status'),
                }
            )

        return jsonify({'success': True, 'documents': out})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/internal/tools/documents/<string:doc_type>/<int:doc_id>', methods=['GET'])
@require_internal_service_token
def internal_get_document_metadata(doc_type: str, doc_id: int):
    """Internal tool: get metadata for a document."""
    try:
        doc_type = (doc_type or '').strip().lower()
        if doc_type not in {'company', 'personal'}:
            return jsonify({'success': False, 'error': 'Invalid doc_type'}), 400

        if doc_type == 'company':
            doc = document_manager.get_document(doc_id)
        else:
            from rag_chatbot.database import user_document_manager
            doc = user_document_manager.get_document(doc_id)

        if not doc:
            return jsonify({'success': False, 'error': 'Not found'}), 404

        return jsonify({'success': True, 'document_type': doc_type, 'document': doc})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/internal/tools/search', methods=['POST'])
@require_internal_service_token
def internal_search_chunks():
    """Internal tool: retrieve top chunks for a query from loaded nodes."""
    try:
        payload = request.get_json(silent=True) or {}
        query = (payload.get('query') or '').strip()
        top_k = int(payload.get('top_k') or 5)
        top_k = max(1, min(top_k, 20))

        filenames = payload.get('filenames')
        if filenames is None and payload.get('filename'):
            filenames = [payload.get('filename')]

        allowed_filenames = set()
        if isinstance(filenames, (list, tuple)):
            for f in filenames:
                if isinstance(f, str) and f.strip():
                    allowed_filenames.add(os.path.basename(f.strip()))

        if not query:
            return jsonify({'success': False, 'error': 'Missing query'}), 400

        if not _ensure_pipeline_ready_for_search():
            return jsonify({'success': False, 'error': 'Pipeline not ready'}), 503

        nodes = []
        try:
            nodes = pipeline._ingestion.get_all_nodes() or []
            if not nodes:
                nodes = pipeline._ingestion.get_ingested_nodes() or []
        except Exception as exc:
            print(f"[INTERNAL_TOOLS] Unable to read nodes: {exc}")

        if not nodes:
            return jsonify({'success': True, 'results': []})

        if allowed_filenames:
            filtered_nodes = []
            for n in nodes:
                md = getattr(n, 'metadata', {}) or {}
                uuid_filename = (
                    md.get('file_name')
                    or md.get('file_path')
                    or md.get('source')
                    or ''
                )
                original = get_original_filename(os.path.basename(str(uuid_filename)))
                if os.path.basename(str(original)) in allowed_filenames:
                    filtered_nodes.append(n)
            nodes = filtered_nodes
            if not nodes:
                return jsonify({'success': True, 'results': []})

        # Build a retriever on demand (fast vector-only retriever).
        retriever = pipeline._engine._retriever.get_retrievers(
            nodes=nodes,
            llm=pipeline._default_model,
            language=pipeline._language,
        )

        retrieved = retriever.retrieve(query)
        results = []
        for item in (retrieved or [])[:top_k]:
            base_node = getattr(item, 'node', None)
            metadata = getattr(base_node, 'metadata', {}) if base_node is not None else {}
            uuid_filename = (
                metadata.get('file_name')
                or metadata.get('file_path')
                or metadata.get('source')
                or 'Unknown'
            )
            original_filename = get_original_filename(os.path.basename(str(uuid_filename)))
            page_label = (
                metadata.get('page_label')
                or metadata.get('page_number')
                or metadata.get('page')
            )
            text = getattr(base_node, 'text', '') if base_node is not None else ''

            results.append(
                {
                    'text': _safe_text_snippet(text),
                    'score': float(getattr(item, 'score', 0.0) or 0.0),
                    'filename': original_filename,
                    'page': page_label,
                    'metadata': {
                        'file_name': uuid_filename,
                        'file_path': metadata.get('file_path'),
                        'page_label': page_label,
                    },
                }
            )

        return jsonify({'success': True, 'results': results})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/')
def index():
    """Serve the main HTML page (requires authentication)"""
    # Check if user is authenticated
    token = request.cookies.get('session_token')
    if not token:
        return redirect('/login')
    
    is_valid, user_info = auth_manager.validate_session(token)
    if not is_valid:
        return redirect('/login')
    
    # Check if user is admin - redirect admins to admin web
    if user_info['role'] == 'admin':
        return redirect(_public_admin_url())
    
    # Send response with no-cache headers to prevent back button issues
    response = send_from_directory(UI_DIR, 'user_index.html')
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response


@app.route('/login')
def login_page():
    """Serve the login page"""
    # If already logged in, redirect to appropriate page based on role
    token = request.cookies.get('session_token')
    if token:
        is_valid, user_info = auth_manager.validate_session(token)
        if is_valid:
            if user_info['role'] == 'admin':
                # Admin should go to admin web
                return redirect(_public_admin_url())
            else:
                # User already logged in, go to home page
                # Don't redirect to avoid loop, just serve the home page directly
                response = send_from_directory(UI_DIR, 'user_index.html')
                response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
                response.headers['Pragma'] = 'no-cache'
                response.headers['Expires'] = '0'
                return response
    
    return send_from_directory(UI_DIR, 'login.html')


@app.route('/signup')
def signup_page():
    """Serve the signup page"""
    return send_from_directory(UI_DIR, 'signup.html')


# Authentication API Endpoints
# ============================================================

@app.route('/api/auth/register', methods=['POST'])
def register():
    """Register a new user"""
    try:
        data = request.json
        username = data.get('username')
        email = data.get('email')
        password = data.get('password')
        full_name = data.get('full_name')
        technical_role = data.get('technical_role')
        
        success, message, user_id = auth_manager.register_user(
            username=username,
            email=email,
            password=password,
            full_name=full_name,
            role='user',  # Default role is user
            technical_role=technical_role
        )
        
        if success:
            return jsonify({
                'success': True,
                'message': message,
                'user_id': user_id
            })
        else:
            return jsonify({
                'success': False,
                'error': message
            }), 400
            
    except Exception as e:
        error_msg = str(e)
        status_code = 500
        if "No documents loaded" in error_msg:
            error_msg = "No documents available yet. Please contact your administrator to upload company documents first."
            status_code = 503
        else:
            error_msg, status_code = format_llm_error_message(error_msg)
        return jsonify({
            'success': False,
            'error': error_msg
        }), status_code


@app.route('/api/auth/login', methods=['POST'])
def login():
    """Authenticate user and create session"""
    try:
        if _env_truthy('BEHIND_PROXY') and not request.is_secure:
            return _https_required_error_response()

        data = request.json
        username = data.get('username')
        password = data.get('password')
        
        # Get client info
        ip_address = request.remote_addr
        user_agent = request.headers.get('User-Agent')
        
        success, message, session_token, user_info = auth_manager.login(
            username=username,
            password=password,
            ip_address=ip_address,
            user_agent=user_agent
        )
        
        if success:
            # In proxy deployments (separate subdomains), keep user logins on user domain.
            if _env_truthy('BEHIND_PROXY') and (user_info or {}).get('role') == 'admin':
                admin_login = _public_admin_url().rstrip('/') + '/login'
                return jsonify({
                    'success': False,
                    'error': f"Please log in on the admin site: {admin_login}",
                }), 403

            response = jsonify({
                'success': True,
                'message': message,
                'session_token': session_token,
                'user': user_info,
                # Let the client redirect without hardcoding ports/scheme.
                'redirect_url': (
                    _public_admin_url()
                    if (user_info or {}).get('role') == 'admin'
                    else '/'
                ),
            })
            
            # Set session cookie
            cookie_kwargs = dict(
                max_age=24 * 60 * 60,  # 24 hours
                httponly=True,
                samesite='Lax',
                secure=_cookie_secure(),
                path='/',
            )
            domain = _cookie_domain()
            if domain:
                cookie_kwargs['domain'] = domain
            response.set_cookie('session_token', session_token, **cookie_kwargs)
            
            return response
        else:
            return jsonify({
                'success': False,
                'error': message
            }), 401
            
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/auth/logout', methods=['POST'])
def logout():
    """Logout user and invalidate session"""
    try:
        if _env_truthy('BEHIND_PROXY') and not request.is_secure:
            return _https_required_error_response()

        auth_header = request.headers.get('Authorization')
        token = None
        
        if auth_header and auth_header.startswith('Bearer '):
            token = auth_header.split(' ')[1]
        else:
            token = request.cookies.get('session_token')
        
        if token:
            auth_manager.logout(token)
        
        response = jsonify({
            'success': True,
            'message': 'Logged out successfully'
        })
        
        # Clear session cookie
        cookie_kwargs = dict(
            expires=0,
            httponly=True,
            samesite='Lax',
            secure=_cookie_secure(),
            path='/',
        )
        domain = _cookie_domain()
        if domain:
            cookie_kwargs['domain'] = domain
        response.set_cookie('session_token', '', **cookie_kwargs)
        
        return response
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/auth/validate', methods=['GET'])
def validate_session():
    """Validate current session"""
    try:
        auth_header = request.headers.get('Authorization')
        token = None
        
        if auth_header and auth_header.startswith('Bearer '):
            token = auth_header.split(' ')[1]
        else:
            token = request.cookies.get('session_token')
        
        if not token:
            return jsonify({
                'success': False,
                'error': 'No session token provided'
            }), 401
        
        is_valid, user_info = auth_manager.validate_session(token)
        
        if is_valid:
            return jsonify({
                'success': True,
                'user': user_info
            })
        else:
            return jsonify({
                'success': False,
                'error': 'Invalid or expired session'
            }), 401
            
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


# API Endpoints
# ============================================================

@app.route('/api/documents', methods=['GET'])
def get_documents():
    """Get list of all documents in the system"""
    try:
        docs = document_manager.get_all_documents()
        return jsonify({
            'success': True,
            'documents': docs
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/documents/<int:doc_id>', methods=['GET'])
def get_document_by_id(doc_id):
    """Get a single document by ID"""
    try:
        doc = document_manager.get_document(doc_id)
        if doc:
            return jsonify({
                'success': True,
                'document': doc
            })
        return jsonify({
            'success': False,
            'error': 'Document not found'
        }), 404
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/documents/folders', methods=['GET'])
def get_document_folders():
    """Get list of all document folders with file counts"""
    try:
        from rag_chatbot.database import db
        conn = db.get_connection()
        cursor = conn.cursor()
        
        # Get folders with counts
        cursor.execute("""
            SELECT 
                df.id,
                df.folder_name,
                df.folder_icon,
                df.display_order,
                COUNT(DISTINCT d.id) as company_count
            FROM document_folders df
            LEFT JOIN documents d ON d.folder = df.folder_name AND d.status = 'active'
            WHERE df.is_active = 1
            GROUP BY df.id, df.folder_name, df.folder_icon, df.display_order
            ORDER BY df.display_order
        """)
        
        folders = []
        for row in cursor.fetchall():
            folders.append({
                'id': row[0],
                'name': row[1],
                'icon': row[2],
                'order': row[3],
                'count': row[4]
            })
        
        conn.close()
        
        return jsonify({
            'success': True,
            'folders': folders
        })
    except Exception as e:
        print(f"Error getting folders: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/user-documents/folders', methods=['GET'])
def get_user_document_folders():
    """Get list of folders containing user's personal documents"""
    try:
        from rag_chatbot.database import db
        
        # Get user info from session
        token = request.cookies.get('session_token')
        if not token:
            return jsonify({'success': False, 'error': 'Authentication required'}), 401
        
        is_valid, user_info = auth_manager.validate_session(token)
        if not is_valid:
            return jsonify({'success': False, 'error': 'Invalid session'}), 401
        
        user_id = user_info.get('id')
        
        conn = db.get_connection()
        cursor = conn.cursor()
        
        # Get folders directly from user_documents table (NOT from document_folders)
        # Personal folders are stored in user_documents.folder column
        cursor.execute("""
            SELECT 
                folder,
                COUNT(*) as doc_count
            FROM user_documents
            WHERE uploaded_by = ?
            AND folder IS NOT NULL
            AND folder != ''
            AND status = 'approved'
            GROUP BY folder
            ORDER BY folder
        """, (user_id,))
        
        folders = []
        for row in cursor.fetchall():
            folders.append({
                'id': None,  # Personal folders don't have IDs in document_folders
                'name': row[0],
                'icon': 'folder',  # Default icon
                'order': 0,
                'count': row[1]
            })
        
        conn.close()
        
        return jsonify({
            'success': True,
            'folders': folders
        })
    except Exception as e:
        print(f"Error getting user folders: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/user-documents/my-folders', methods=['GET'])
def get_my_upload_folders():
    """Get list of folders the current user has uploaded to (for upload dropdown)"""
    try:
        from rag_chatbot.database import db
        
        # Get user info from session
        token = request.cookies.get('session_token')
        if not token:
            return jsonify({'success': False, 'error': 'Authentication required'}), 401
        
        is_valid, user_info = auth_manager.validate_session(token)
        if not is_valid:
            return jsonify({'success': False, 'error': 'Invalid session'}), 401
        
        user_id = user_info.get('id')
        
        conn = db.get_connection()
        cursor = conn.cursor()
        
        # Get all folders the user has uploaded to (including pending)
        cursor.execute("""
            SELECT 
                folder,
                COUNT(*) as doc_count
            FROM user_documents
            WHERE uploaded_by = ?
            AND folder IS NOT NULL
            AND folder != ''
            GROUP BY folder
            ORDER BY folder
        """, (user_id,))
        
        folders = []
        for row in cursor.fetchall():
            folders.append({
                'name': row[0],
                'count': row[1]
            })
        
        conn.close()
        
        return jsonify({
            'success': True,
            'folders': folders
        })
    except Exception as e:
        print(f"Error getting my folders: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/documents/by-folder/<folder_name>', methods=['GET'])
def get_documents_by_folder(folder_name):
    """Get documents in a specific folder, sorted by usage (hottest first)"""
    try:
        from rag_chatbot.database import db
        from urllib.parse import unquote
        
        folder_name = unquote(folder_name)
        conn = db.get_connection()
        cursor = conn.cursor()
        
        # Get user info for tracking
        token = request.cookies.get('session_token')
        user_id = None
        if token:
            is_valid, user_info = auth_manager.validate_session(token)
            if is_valid:
                user_id = user_info.get('id')
        
        # Get documents with usage count, sorted by hottest first
        cursor.execute("""
            SELECT 
                d.id,
                d.filename,
                d.original_filename,
                d.file_type,
                d.file_size,
                d.upload_date,
                d.uploaded_by,
                d.metadata,
                d.folder,
                COALESCE(usage.usage_count, 0) as usage_count
            FROM documents d
            LEFT JOIN (
                SELECT document_id, COUNT(*) as usage_count
                FROM document_usage
                WHERE document_type = 'company'
                GROUP BY document_id
            ) usage ON d.id = usage.document_id
            WHERE d.status = 'active' AND d.folder = ?
            ORDER BY usage_count DESC, d.upload_date DESC
        """, (folder_name,))
        
        documents = []
        for row in cursor.fetchall():
            metadata = json.loads(row[7]) if row[7] else {}
            documents.append({
                'id': row[0],
                'filename': row[1],
                'original_filename': row[2],
                'file_type': row[3],
                'file_size': row[4],
                'upload_date': row[5],
                'uploaded_by': row[6],
                'description': metadata.get('description', ''),
                'folder': row[8],
                'usage_count': row[9]
            })
        
        conn.close()
        
        return jsonify({
            'success': True,
            'folder': folder_name,
            'documents': documents
        })
    except Exception as e:
        print(f"Error getting documents by folder: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/user-documents/by-folder/<folder_name>', methods=['GET'])
def get_user_documents_by_folder(folder_name):
    """Get user's personal documents in a specific folder, sorted by usage"""
    try:
        from rag_chatbot.database import db
        from urllib.parse import unquote
        
        folder_name = unquote(folder_name)
        
        # Get user info from session
        token = request.cookies.get('session_token')
        if not token:
            return jsonify({'success': False, 'error': 'Authentication required'}), 401
        
        is_valid, user_info = auth_manager.validate_session(token)
        if not is_valid:
            return jsonify({'success': False, 'error': 'Invalid session'}), 401
        
        user_id = user_info.get('id')
        
        conn = db.get_connection()
        cursor = conn.cursor()
        
        # Get user's documents with usage count, sorted by hottest first
        cursor.execute("""
            SELECT 
                ud.id,
                ud.filename,
                ud.original_filename,
                ud.file_type,
                ud.file_size,
                ud.created_at,
                ud.description,
                ud.folder,
                ud.status,
                COALESCE(usage.usage_count, 0) as usage_count
            FROM user_documents ud
            LEFT JOIN (
                SELECT document_id, COUNT(*) as usage_count
                FROM document_usage
                WHERE document_type = 'personal'
                GROUP BY document_id
            ) usage ON ud.id = usage.document_id
            WHERE ud.uploaded_by = ? AND ud.status = 'approved' AND ud.folder = ?
            ORDER BY usage_count DESC, ud.created_at DESC
        """, (user_id, folder_name))
        
        documents = []
        for row in cursor.fetchall():
            documents.append({
                'id': row[0],
                'filename': row[1],
                'original_filename': row[2],
                'file_type': row[3],
                'file_size': row[4],
                'upload_date': row[5],
                'description': row[6] or '',
                'folder': row[7],
                'status': row[8],
                'usage_count': row[9]
            })
        
        conn.close()
        
        return jsonify({
            'success': True,
            'folder': folder_name,
            'documents': documents
        })
    except Exception as e:
        print(f"Error getting user documents by folder: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/stats', methods=['GET'])
def get_stats():
    """Get system statistics (user-specific if logged in)"""
    try:
        docs = document_manager.get_all_documents()
        
        # Get user info from session token
        token = request.cookies.get('session_token')
        user_chat_count = 0
        if token:
            is_valid, user_info = auth_manager.validate_session(token)
            if is_valid:
                user_id = user_info.get('id')
                # Use JSON storage for user count
                user_chat_count = chat_storage.get_user_chat_count(user_id)
        
        # Get total questions from chat history (for all users)
        total_chat_count = chat_history_manager.get_chat_count()
        
        return jsonify({
            'success': True,
            'stats': {
                'total_documents': len(docs),
                'total_questions': total_chat_count,
                'user_questions': user_chat_count
            }
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/chat/history', methods=['GET'])
def get_chat_history():
    """Get user's chat history from JSON storage"""
    try:
        # Get user info from session token
        token = request.cookies.get('session_token')
        if not token:
            return jsonify({
                'success': False,
                'error': 'Authentication required'
            }), 401
        
        is_valid, user_info = auth_manager.validate_session(token)
        if not is_valid:
            return jsonify({
                'success': False,
                'error': 'Invalid session'
            }), 401
        
        user_id = user_info.get('id')
        limit = request.args.get('limit', type=int)  # Optional limit parameter
        
        # Get history from JSON storage
        history = chat_storage.get_user_history(user_id, limit=limit)
        
        return jsonify({
            'success': True,
            'history': history,
            'count': len(history)
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/chat/clear', methods=['POST'])
def clear_chat_history():
    """Clear user's chat history"""
    try:
        # Get user info from session token
        token = request.cookies.get('session_token')
        if not token:
            return jsonify({
                'success': False,
                'error': 'Authentication required'
            }), 401
        
        is_valid, user_info = auth_manager.validate_session(token)
        if not is_valid:
            return jsonify({
                'success': False,
                'error': 'Invalid session'
            }), 401
        
        user_id = user_info.get('id')
        
        # Clear history
        chat_storage.clear_user_history(user_id)
        
        return jsonify({
            'success': True,
            'message': 'Chat history cleared'
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/chat/welcome-summary', methods=['GET'])
@require_auth(optional=True)
def get_welcome_summary():
    """
    Get pre-generated welcome summary from cache.
    Summaries are generated by the background scheduler at 12 AM and 12 PM.
    Falls back to real-time generation if no cached summary exists.
    """
    try:
        from rag_chatbot.database import user_role_manager, db, role_summary_manager

        import re
        import html as _html

        def _strip_html(value: str) -> str:
            if not value:
                return ''
            text = re.sub(r'<\s*br\s*/?>', '\n', value, flags=re.IGNORECASE)
            text = re.sub(r'</p\s*>', '\n', text, flags=re.IGNORECASE)
            text = re.sub(r'<[^>]+>', ' ', text)
            text = _html.unescape(text)
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
        
        # Get user role
        user_id = request.user.get('id') if request.user else None
        
        if not user_id:
            return jsonify({
                'success': False,
                'error': 'Authentication required'
            }), 401
        
        user_role_info = user_role_manager.get_user_role(user_id)
        
        if not user_role_info:
            return jsonify({
                'success': False,
                'error': 'Please set your technical role first'
            }), 400
        
        role_type = user_role_info['role_type']
        role_name = user_role_info.get('role_name', role_type)
        
        # Try to get cached summary
        cached_summary = role_summary_manager.get_summary(role_type)
        
        if cached_summary:
            # Use cached summary
            # Get pending uploads count for current user
            conn = db.get_connection()
            cursor = conn.cursor()
            
            pending_uploads = 0
            token = request.cookies.get('session_token')
            if token:
                is_valid, user_info = auth_manager.validate_session(token)
                if is_valid:
                    uid = user_info.get('id')
                    cursor.execute("""
                        SELECT COUNT(*) FROM user_documents
                        WHERE uploaded_by = ? AND status = 'pending'
                    """, (uid,))
                    pending_uploads = cursor.fetchone()[0]
            
            # Add pending uploads to stats
            stats = cached_summary.get('stats', {})
            stats['pending_uploads'] = pending_uploads

            # Refresh hot news summaries from DB if we have newer intro-only LLM summaries.
            # This prevents older cached payloads from showing truncated summaries.
            hot_news_payload = cached_summary.get('hot_news', [])
            try:
                hot_ids = [item.get('id') for item in hot_news_payload if isinstance(item, dict) and item.get('id')]
                hot_ids = [int(x) for x in hot_ids]
                if hot_ids:
                    placeholders = ','.join(['?'] * len(hot_ids))
                    cursor.execute(
                        f"SELECT id, intro_llm_summary FROM technical_articles WHERE id IN ({placeholders})",
                        tuple(hot_ids),
                    )
                    intro_map = {row[0]: (row[1] or '').strip() for row in cursor.fetchall()}
                    for item in hot_news_payload:
                        if not isinstance(item, dict):
                            continue
                        news_id = item.get('id')
                        if news_id in intro_map and intro_map[news_id]:
                            item['summary'] = intro_map[news_id]
            except Exception as refresh_err:
                print(f"[WARN] Failed to refresh cached hot_news intro summaries: {refresh_err}")

            # Filter cached new_docs against current DB state to avoid showing deleted documents.
            new_docs_payload = cached_summary.get('new_docs', [])
            try:
                doc_ids = []
                for item in (new_docs_payload or []):
                    if isinstance(item, dict) and item.get('id') is not None:
                        try:
                            doc_ids.append(int(item.get('id')))
                        except Exception:
                            continue
                if doc_ids:
                    placeholders = ','.join(['?'] * len(doc_ids))
                    cursor.execute(
                        f"SELECT id FROM documents WHERE status = 'active' AND id IN ({placeholders})",
                        tuple(doc_ids),
                    )
                    active_ids = {row[0] for row in cursor.fetchall()}
                    new_docs_payload = [
                        item for item in (new_docs_payload or [])
                        if isinstance(item, dict)
                        and item.get('id') is not None
                        and int(item.get('id')) in active_ids
                    ]
            except Exception as doc_filter_err:
                print(f"[WARN] Failed to filter cached new_docs: {doc_filter_err}")
            
            return jsonify({
                'success': True,
                'summary': cached_summary.get('summary_text', ''),
                'hot_news': hot_news_payload,
                'new_docs': new_docs_payload,
                'stats': stats,
                'cached': True,
                'generated_at': cached_summary.get('generated_at', '')
            })
        
        # No cached summary - generate on-the-fly (fallback)
        
        # Gather data for summary
        conn = db.get_connection()
        cursor = conn.cursor()
        
        # Get hottest news (last 7 days, sorted by total views)
        cursor.execute("""
            SELECT id, title, summary, intro_llm_summary, content, (view_count + online_view_count) as total_views, 
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
            SELECT 
                d.id, d.original_filename, d.upload_date, d.metadata,
                COALESCE(usage.usage_count, 0) as usage_count
            FROM documents d
            LEFT JOIN (
                SELECT document_id, COUNT(*) as usage_count
                FROM document_usage
                WHERE document_type = 'company'
                GROUP BY document_id
            ) usage ON d.id = usage.document_id
                        WHERE d.status = 'active'
                            AND d.upload_date >= date('now', '-7 days')
            ORDER BY d.upload_date DESC
            LIMIT 3
        """)
        new_docs = cursor.fetchall()
        
        # Get user-uploaded documents awaiting approval
        token = request.cookies.get('session_token')
        pending_uploads = 0
        if token:
            is_valid, user_info = auth_manager.validate_session(token)
            if is_valid:
                user_id = user_info.get('id')
                cursor.execute("""
                    SELECT COUNT(*) FROM user_documents
                    WHERE uploaded_by = ? AND status = 'pending'
                """, (user_id,))
                pending_uploads = cursor.fetchone()[0]
        
        # Build context for AI summary
        context_parts = []
        
        # Prepare structured data for frontend
        hot_news_list = []
        if hot_news:
            context_parts.append("**Tin tức nổi bật tuần này:**")
            for news_id, title, summary, intro_llm_summary, content, views, pub_date, url in hot_news:
                context_parts.append(f"- {title} ({views} lượt xem)")

                final_summary = (intro_llm_summary or '').strip()
                if not final_summary:
                    paragraphs = _first_paragraphs(content or '', max_paragraphs=3)
                    intro_text = "\n\n".join(paragraphs).strip()
                    if not intro_text and summary:
                        intro_text = _strip_html(summary)

                    if intro_text and pipeline and pipeline.get_model_name():
                        try:
                            llm = pipeline._default_model
                            prompt = f"""Bạn là trợ lý AI.

Hãy tóm tắt bài viết sau bằng tiếng Việt, CHỈ dựa trên tiêu đề và đoạn giới thiệu.

Yêu cầu:
- 2–3 câu
- Câu phải đầy đủ, không cắt cụt
- Không bịa thêm thông tin ngoài nội dung cung cấp
- Không dùng bullet

TIÊU ĐỀ: {title}

GIỚI THIỆU:
{intro_text}
"""
                            result = llm.complete(prompt)
                            final_summary = getattr(result, 'text', str(result)).strip()
                            if final_summary:
                                # Persist for reuse across users
                                try:
                                    conn2 = db.get_connection()
                                    cur2 = conn2.cursor()
                                    cur2.execute(
                                        "UPDATE technical_articles SET intro_llm_summary = ?, intro_llm_summary_updated_at = ? WHERE id = ?",
                                        (final_summary, int(time.time()), news_id),
                                    )
                                    conn2.commit()
                                    conn2.close()
                                except Exception as persist_err:
                                    print(f"[WARN] Failed to persist intro summary: {persist_err}")
                        except Exception as llm_err:
                            print(f"[WARN] LLM intro summary failed: {llm_err}")

                if not final_summary:
                    final_summary = build_article_summary(title, content, fallback_summary=summary)

                hot_news_list.append({
                    'id': news_id,
                    'title': title,
                    'summary': final_summary,
                    'views': views,
                    'url': url
                })
        
        # Prepare new documents data
        new_docs_list = []
        if new_docs:
            context_parts.append("\n**Tài liệu mới được thêm:**")
            for doc_id, filename, upload_date, metadata, usage_count in new_docs:
                # Try to parse metadata for description
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
                    'description': description,
                    'usage_count': usage_count
                })
        
        # Add pending uploads info
        if pending_uploads > 0:
            context_parts.append(f"\n**Bạn có {pending_uploads} tài liệu đang chờ phê duyệt**")
        
        # Generate simple summary without LLM (to avoid rate limits)
        summary_text = f"Chào mừng bạn trở lại! "
        if hot_news_list:
            summary_text += f"Tuần này có {len(hot_news_list)} tin tức nổi bật"
            if hot_news_list[0].get('title'):
                summary_text += f": {hot_news_list[0]['title']}"
                if len(hot_news_list) > 1:
                    summary_text += f" và {len(hot_news_list)-1} tin khác"
            summary_text += ". "
        if new_docs_list:
            summary_text += f"Có {len(new_docs_list)} tài liệu mới được thêm vào hệ thống. "
        summary_text += "Hãy khám phá ngay để cập nhật kiến thức mới nhất!"
        
        return jsonify({
            'success': True,
            'summary': summary_text,
            'hot_news': hot_news_list,
            'new_docs': new_docs_list,
            'stats': {
                'hot_news_count': len(hot_news),
                'new_docs_count': len(new_docs),
                'pending_uploads': pending_uploads
            },
            'cached': False
        })
        
    except Exception as e:
        print(f"Error generating welcome summary: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/chat/test-summary', methods=['POST'])
@require_auth(optional=True)
def test_generate_summary():
    """Force generate a new welcome summary for testing purposes (no LLM call - uses cached data)"""
    try:
        from rag_chatbot.workers.summary_scheduler import force_generate_summary
        
        role_type = 'developer'
        token = request.cookies.get('session_token')
        if token:
            is_valid, user_info = auth_manager.validate_session(token)
            if is_valid:
                role_type = user_info.get('role', 'developer')
        
        # Force generate new summary
        result = force_generate_summary(pipeline, role_type)
        
        return jsonify({
            'success': True,
            'message': 'Summary generated',
            'summary_text': result.get('summary', ''),
            'hot_news_count': len(result.get('hot_news', [])),
            'new_docs_count': len(result.get('new_docs', []))
        })
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/query', methods=['POST'])
def query():
    """Handle chat query with streaming response"""
    try:
        data = request.json or {}
        message = data.get('message', '').strip()
        session_id = data.get('session_id', str(uuid.uuid4()))
        chat_history = data.get('chat_history', [])
        selected_documents = data.get('selected_documents') or []
        selected_filenames = normalize_selected_filenames(selected_documents)
        
        # Get user info from session token
        token = request.cookies.get('session_token')
        user_id = None
        if token:
            is_valid, user_info = auth_manager.validate_session(token)
            if is_valid:
                user_id = user_info.get('id')
        
        if not message:
            return jsonify({
                'success': False,
                'error': 'Message cannot be empty'
            }), 400

        news_answer = get_news_article_answer(message)
        if news_answer:
            def stream_news_answer():
                final_answer = news_answer['answer']
                sources = news_answer['sources']
                record_chat_interaction(session_id, message, final_answer, sources, user_id)
                for chunk in chunk_text(final_answer):
                    yield f"data: {json.dumps({'type': 'token', 'content': chunk})}\n\n"
                yield f"data: {json.dumps({'type': 'done', 'sources': sources, 'session_id': session_id})}\n\n"
            return Response(stream_with_context(stream_news_answer()), mimetype='text/event-stream')
        
        # Check if model is initialized
        if not pipeline.get_model_name():
            return jsonify({
                'success': False,
                'error': 'System is initializing, please wait...'
            }), 503
        
        # Initialize documents if not already done
        if pipeline._query_engine is None:
            print("Loading documents for the first time...")
            pipeline._initialize_existing_documents()
            print("Documents loaded!")
        
        def generate():
            """Generator function for streaming response"""
            import time
            start_time = time.time()
            
            try:
                print(f"[DEBUG] Starting query processing at {start_time}")
                print(f"[DEBUG] Selected documents from request: {selected_filenames}")
                
                # Smart document detection and optimization
                optimized_message = message
                optimized_selected = selected_filenames
                
                # Check if query mentions a specific document
                if selected_filenames:
                    specific_doc = extract_document_from_query(message, selected_filenames)
                    if specific_doc:
                        print(f"[OPTIMIZE] Detected query about specific document: {specific_doc}")
                        print(f"[OPTIMIZE] Narrowing from {len(selected_filenames)} docs to 1 to save tokens")
                        optimized_selected = [specific_doc]
                
                # Translate to Vietnamese if needed for Vietnamese responses
                translated_message, was_translated = translate_query_to_vietnamese(message)
                if was_translated:
                    print(f"[OPTIMIZE] Translated query to Vietnamese: {translated_message}")
                    optimized_message = translated_message
                elif should_use_vietnamese_response(message):
                    # Query is already in Vietnamese, ensure Vietnamese response
                    print(f"[OPTIMIZE] Query is in Vietnamese, will respond in Vietnamese")
                
                # Convert chat history to expected format and limit to last 4 exchanges (8 messages)
                # This saves tokens by not sending entire conversation history
                formatted_history = []
                history_limit = 4  # Only keep last 4 Q&A pairs to save tokens
                recent_history = chat_history[-history_limit:] if len(chat_history) > history_limit else chat_history
                
                for item in recent_history:
                    if len(item) == 2:
                        formatted_history.append([item[0], item[1]])
                
                if len(chat_history) > history_limit:
                    print(f"[DEBUG] Truncated chat history from {len(chat_history)} to {len(formatted_history)} exchanges to save tokens")
                
                print(f"[DEBUG] Getting response from pipeline...")
                # Get response from pipeline - use "QA" mode like old Gradio UI
                response = pipeline.query(
                    "QA",
                    optimized_message,
                    formatted_history,
                    selected_files=optimized_selected or None,
                )
                
                print(f"[DEBUG] Response type: {type(response)}")
                print(f"[DEBUG] Has response_gen: {hasattr(response, 'response_gen')}")
                print(f"[DEBUG] Has response: {hasattr(response, 'response')}")
                
                # Check if we have a non-streaming response first
                if hasattr(response, 'response') and response.response:
                    print(f"[DEBUG] Non-streaming response available: {len(response.response)} chars")
                    # Send the whole response as tokens
                    full_text = response.response
                    for i in range(0, len(full_text), 10):
                        chunk = full_text[i:i+10]
                        yield f"data: {json.dumps({'type': 'token', 'content': chunk})}\n\n"
                    answer_text = [full_text]
                    token_count = len(full_text) // 10
                elif hasattr(response, 'response_gen'):
                    print(f"[DEBUG] response_gen type: {type(response.response_gen)}")
                    print(f"[DEBUG] Starting to stream tokens...")
                    # Stream answer as it's generated
                    answer_text = []
                    token_count = 0
                    
                    try:
                        for text in response.response_gen:
                            answer_text.append(text)
                            token_count += 1
                            
                            # Send partial answer as JSON
                            yield f"data: {json.dumps({'type': 'token', 'content': text})}\n\n"
                        
                        print(f"[DEBUG] Streamed {token_count} tokens in {time.time() - start_time:.2f}s")
                    except Exception as gen_error:
                        print(f"[ERROR] Error during token generation: {str(gen_error)}")
                        print(f"[ERROR] Error type: {type(gen_error).__name__}")
                        import traceback
                        traceback.print_exc()
                        friendly_msg, _ = format_llm_error_message(str(gen_error))
                        yield f"data: {json.dumps({'type': 'error', 'error': friendly_msg})}\n\n"
                        return
                else:
                    print(f"[ERROR] No response or response_gen available!")
                    answer_text = ["Error: No response available from LLM"]
                    token_count = 0
                
                final_answer = "".join(answer_text)
                
                # Extract sources (best match only for streaming UI)
                sources = select_relevant_sources(
                    final_answer,
                    getattr(response, 'source_nodes', []),
                    max_sources=1
                )
                
                record_chat_interaction(session_id, message, final_answer, sources, user_id)
                
                # Send completion with sources
                yield f"data: {json.dumps({'type': 'done', 'sources': sources, 'session_id': session_id})}\n\n"
                
            except ValueError as e:
                yield f"data: {json.dumps({'type': 'error', 'error': str(e)})}\n\n"
                return
            except Exception as e:
                error_msg = str(e)
                if "No documents loaded" in error_msg:
                    error_msg = "No documents available yet. Please contact your administrator to upload company documents first."
                else:
                    error_msg, _ = format_llm_error_message(error_msg)
                
                yield f"data: {json.dumps({'type': 'error', 'error': error_msg})}\n\n"
        
        return Response(stream_with_context(generate()), mimetype='text/event-stream')
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/chat', methods=['POST'])
def chat():
    """Handle chat query and return a JSON response (non-streaming)."""
    try:
        data = request.json or {}
        message = data.get('message', '').strip()
        session_id = data.get('session_id') or str(uuid.uuid4())
        chat_history = data.get('chat_history', [])
        selected_documents = data.get('selected_documents') or []
        selected_filenames = normalize_selected_filenames(selected_documents)

        token = request.cookies.get('session_token')
        user_id = None
        if token:
            is_valid, user_info = auth_manager.validate_session(token)
            if is_valid:
                user_id = user_info.get('id')

        if not message:
            return jsonify({
                'success': False,
                'error': 'Message cannot be empty'
            }), 400

        if not pipeline.get_model_name():
            return jsonify({
                'success': False,
                'error': 'System is initializing, please wait...'
            }), 503

        if pipeline._query_engine is None:
            print("Loading documents for the first time (JSON chat)...")
            pipeline._initialize_existing_documents()
            print("Documents loaded!")

        # Smart document detection and optimization
        optimized_message = message
        optimized_selected = selected_filenames
        
        # Check if query mentions a specific document
        if selected_filenames:
            specific_doc = extract_document_from_query(message, selected_filenames)
            if specific_doc:
                print(f"[OPTIMIZE] Detected query about specific document: {specific_doc}")
                print(f"[OPTIMIZE] Narrowing from {len(selected_filenames)} docs to 1 to save tokens")
                optimized_selected = [specific_doc]
        
        # Translate to Vietnamese if needed for Vietnamese responses
        translated_message, was_translated = translate_query_to_vietnamese(message)
        if was_translated:
            print(f"[OPTIMIZE] Translated query to Vietnamese: {translated_message}")
            optimized_message = translated_message
        elif should_use_vietnamese_response(message):
            # Query is already in Vietnamese, ensure Vietnamese response
            print(f"[OPTIMIZE] Query is in Vietnamese, will respond in Vietnamese")

        # Limit chat history to last 4 exchanges to save tokens
        history_limit = 4
        recent_history = chat_history[-history_limit:] if len(chat_history) > history_limit else chat_history
        
        formatted_history = []
        for item in recent_history:
            if isinstance(item, (list, tuple)) and len(item) == 2:
                formatted_history.append([item[0], item[1]])
        
        if len(chat_history) > history_limit:
            print(f"[DEBUG] Truncated chat history from {len(chat_history)} to {len(formatted_history)} exchanges to save tokens")

        news_answer = get_news_article_answer(message)
        if news_answer:
            final_answer = news_answer['answer']
            sources = news_answer['sources']
            record_chat_interaction(session_id, message, final_answer, sources, user_id)
            return jsonify({
                'success': True,
                'response': final_answer,
                'sources': sources,
                'session_id': session_id
            })

        # MCP integration (explicit opt-in): users can prefix a message with `/mcp` to
        # route retrieval through the MCP server, while keeping the default chatbot
        # behavior unchanged.
        if (message or '').lower().startswith('/mcp'):
            try:
                raw = (message or '')[4:].lstrip(' :\t')
                if not raw:
                    return jsonify({'success': False, 'error': 'Usage: /mcp <your question>'}), 400

                # Do not mix document-scoping with MCP until explicitly designed.
                if optimized_selected:
                    return jsonify({
                        'success': False,
                        'error': 'MCP mode currently does not support selected documents. Remove selections and try again.',
                    }), 400

                import asyncio
                from rag_chatbot.mcp_client import call_mcp_tool

                async def _mcp_answer() -> dict:
                    search = await call_mcp_tool('search_chunks', {'query': raw, 'top_k': 6})
                    results = (search or {}).get('results') or []
                    if not results:
                        return {
                            'success': True,
                            'response': 'No relevant internal documents were found for this question.',
                            'sources': [],
                            'session_id': session_id,
                            'mcp': True,
                        }

                    context_lines = []
                    sources_out = []
                    for idx, r in enumerate(results, start=1):
                        filename = r.get('filename')
                        page = r.get('page')
                        sources_out.append({'filename': filename, 'page': page, 'score': r.get('score')})
                        context_lines.append(f"[{idx}] {filename} (page {page})\n{r.get('text','')}")

                    prompt = (
                        "You are an internal knowledge assistant. Answer the user's question using ONLY the provided sources. "
                        "If the sources are insufficient, say what is missing.\n\n"
                        f"Question: {raw}\n\n"
                        "Sources:\n" + "\n\n".join(context_lines) + "\n\n"
                        "Write a concise, factual answer."
                    )

                    llm = getattr(pipeline, '_default_model', None)
                    if not llm:
                        return {'success': False, 'error': 'LLM not initialized'}

                    result = llm.complete(prompt)
                    text = getattr(result, 'text', '') if result is not None else ''
                    answer = (text or '').strip() or "I'm sorry, I couldn't generate a response this time."
                    return {
                        'success': True,
                        'response': answer,
                        'sources': sources_out,
                        'session_id': session_id,
                        'mcp': True,
                    }

                out = asyncio.run(_mcp_answer())
                if out.get('success') is True and out.get('response') is not None:
                    record_chat_interaction(session_id, message, out.get('response') or '', out.get('sources') or [], user_id)
                return jsonify(out)
            except Exception as mcp_exc:
                print(f"[MCP_CHAT] MCP mode failed: {mcp_exc}")
                return jsonify({'success': False, 'error': f"MCP mode failed: {mcp_exc}"}), 502

        def is_template_question(text: str) -> bool:
            lowered = (text or '').lower()
            return (
                'nói về nội dung gì' in lowered
                or 'giải thích thuật ngữ' in lowered
                or 'tóm tắt bài viết' in lowered
            )

        cached_template_answer = None
        cached_template_sources = None
        template_cache_key = None
        if is_template_question(optimized_message):
            from rag_chatbot.database import db

            ttl_seconds = int(os.environ.get('TEMPLATE_ANSWER_CACHE_TTL_SECONDS', '604800'))  # 7 days
            now = int(time.time())

            normalized_message = re.sub(r'\s+', ' ', optimized_message.strip().lower())
            normalized_docs = ','.join(sorted(optimized_selected)) if optimized_selected else ''
            model_name = pipeline.get_model_name() or ''
            key_material = f"v1|model:{model_name}|msg:{normalized_message}|docs:{normalized_docs}"
            template_cache_key = hashlib.sha256(key_material.encode('utf-8')).hexdigest()

            conn = db.get_connection()
            cursor = conn.cursor()
            cursor.execute(
                "SELECT answer, sources, created_at FROM template_answer_cache WHERE cache_key = ?",
                (template_cache_key,)
            )
            row = cursor.fetchone()
            if row:
                answer_text, sources_json, created_at = row
                if created_at and int(created_at) >= (now - ttl_seconds):
                    cached_template_answer = answer_text
                    cached_template_sources = json.loads(sources_json) if sources_json else []
                else:
                    cursor.execute("DELETE FROM template_answer_cache WHERE cache_key = ?", (template_cache_key,))
                    conn.commit()
            conn.close()

        if cached_template_answer is not None:
            record_chat_interaction(session_id, message, cached_template_answer, cached_template_sources, user_id)
            return jsonify({
                'success': True,
                'response': cached_template_answer,
                'sources': cached_template_sources,
                'session_id': session_id,
                'cached': True,
                'cache_type': 'template'
            })

        response = pipeline.query(
            "QA",
            optimized_message,
            formatted_history,
            selected_files=optimized_selected or None,
        )

        final_answer = ""
        if hasattr(response, 'response') and response.response:
            final_answer = response.response
        elif hasattr(response, 'response_gen'):
            chunks = []
            try:
                for text in response.response_gen:
                    chunks.append(text)
            except Exception as gen_error:
                print(f"[ERROR] JSON chat failed while streaming tokens: {gen_error}")
                import traceback
                traceback.print_exc()
                friendly_msg, status_code = format_llm_error_message(str(gen_error))
                return jsonify({
                    'success': False,
                    'error': friendly_msg
                }), status_code
            final_answer = ''.join(chunks)
        else:
            final_answer = "I'm sorry, I couldn't generate a response this time."

        sources = select_relevant_sources(
            final_answer,
            getattr(response, 'source_nodes', []),
            max_sources=2
        )

        # Save template answers to cache for cross-user reuse
        if template_cache_key and is_template_question(optimized_message):
            try:
                from rag_chatbot.database import db

                ttl_seconds = int(os.environ.get('TEMPLATE_ANSWER_CACHE_TTL_SECONDS', '604800'))
                now = int(time.time())
                conn = db.get_connection()
                cursor = conn.cursor()
                cursor.execute(
                    "INSERT OR REPLACE INTO template_answer_cache (cache_key, answer, sources, created_at) VALUES (?, ?, ?, ?)",
                    (template_cache_key, final_answer, json.dumps(sources or [], ensure_ascii=False), now)
                )
                cursor.execute("DELETE FROM template_answer_cache WHERE created_at < ?", (now - ttl_seconds,))
                conn.commit()
                conn.close()
            except Exception as cache_err:
                print(f"[WARN] Failed to cache template answer: {cache_err}")

        # Track document usage in chat
        if user_id and sources:
            try:
                from rag_chatbot.database import db
                conn = db.get_connection()
                cursor = conn.cursor()
                
                for source in sources:
                    filename = source.get('filename', '')
                    if filename:
                        # Find document ID by filename
                        cursor.execute("SELECT id FROM documents WHERE filename = ? OR original_filename = ?", 
                                     (filename, filename))
                        row = cursor.fetchone()
                        if row:
                            cursor.execute("""
                                INSERT INTO document_usage (document_id, document_type, user_id, action_type)
                                VALUES (?, 'company', ?, 'chat')
                            """, (row[0], user_id))
                        else:
                            # Check user_documents
                            cursor.execute("SELECT id FROM user_documents WHERE filename = ? OR original_filename = ?",
                                         (filename, filename))
                            row = cursor.fetchone()
                            if row:
                                cursor.execute("""
                                    INSERT INTO document_usage (document_id, document_type, user_id, action_type)
                                    VALUES (?, 'personal', ?, 'chat')
                                """, (row[0], user_id))
                
                conn.commit()
                conn.close()
            except Exception as track_err:
                print(f"[WARN] Failed to track document usage: {track_err}")

        record_chat_interaction(session_id, message, final_answer, sources, user_id)

        return jsonify({
            'success': True,
            'response': final_answer,
            'sources': sources,
            'session_id': session_id
        })

    except ValueError as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 400
    except Exception as e:
        error_msg = str(e)
        status_code = 500
        if "No documents loaded" in error_msg:
            error_msg = "No documents available yet. Please contact your administrator to upload company documents first."
            status_code = 503
        else:
            error_msg, status_code = format_llm_error_message(error_msg)

        return jsonify({
            'success': False,
            'error': error_msg
        }), status_code


# @app.route('/api/report', methods=['POST'])
# def submit_report():
#     """Submit a user report about incorrect/missing information"""
#     try:
#         data = request.json
#         session_id = data.get('session_id')
#         report_type = data.get('report_type', 'incorrect')
#         details = data.get('details', '')
        
#         # Get last response from session
#         last_response = None
#         if session_id and session_id in sessions:
#             last_response = sessions[session_id].get('last_response')
        
#         if not last_response:
#             return jsonify({
#                 'success': False,
#                 'error': 'No recent conversation found for this report'
#             }), 400
        
#         # Create report
#         report_id = report_manager.create_report(
#             question=last_response['question'],
#             answer=last_response['answer'],
#             report_type=report_type,
#             report_reason=report_type,  # Use report_type as reason
#             user_comment=details  # Details go into user_comment
#         )
        
#         return jsonify({
#             'success': True,
#             'report_id': report_id,
#             'message': 'Report submitted successfully. Thank you for your feedback!'
#         })
        
#     except Exception as e:
#         return jsonify({
#             'success': False,
#             'error': str(e)
#         }), 500

@app.route('/api/report', methods=['POST'])
def submit_report():
    """Submit a user report about incorrect/missing information"""
    try:
        data = request.json
        
        # Get data from frontend - support both field names
        question = data.get('question', '')
        answer = data.get('answer', '')
        report_type = data.get('issue_type') or data.get('report_type', 'incorrect')
        user_comment = data.get('comment') or data.get('details', '')
        session_id = data.get('session_id')

        # If no question/answer provided, try to get from session
        if not question or not answer:
            if session_id and session_id in sessions:
                last_response = sessions[session_id].get('last_response')
                if last_response:
                    question = question or last_response.get('question', '(Unknown question)')
                    answer = answer or last_response.get('answer', '(Unknown answer)')

        # Create report with all the data
        report_id = report_manager.create_report(
            question=question or '(No question provided)',
            answer=answer or '(No answer provided)',
            report_type=report_type,
            report_reason=report_type,
            user_comment=user_comment
        )

        return jsonify({
            'success': True,
            'report_id': report_id,
            'message': 'Report submitted successfully. Thank you for your feedback!'
        })

    except Exception as e:
        print(f"[ERROR] Report submission failed: {str(e)}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

# @app.route('/api/download/<int:doc_id>', methods=['GET'])
# def download_document(doc_id):
#     """Download a document file"""
#     try:
#         doc = document_manager.get_document(doc_id)
#         if not doc:
#             return jsonify({
#                 'success': False,
#                 'error': 'Document not found'
#             }), 404
        
#         file_path = doc['file_path']
#         if not os.path.exists(file_path):
#             return jsonify({
#                 'success': False,
#                 'error': 'File not found on disk'
#             }), 404
        
#         directory = os.path.dirname(file_path)
#         filename = os.path.basename(file_path)
        
#         return send_from_directory(directory, filename, as_attachment=True)
        
#     except Exception as e:
#         return jsonify({
#             'success': False,
#             'error': str(e)
#         }), 500

@app.route('/api/download/<int:doc_id>', methods=['GET'])
def download_document(doc_id):
    """Download a document file"""
    try:
        doc = document_manager.get_document(doc_id)
        if not doc:
            return jsonify({
                'success': False,
                'error': 'Document not found'
            }), 404

        filename = doc.get('filename') or doc.get('original_filename')
        if not filename:
            return jsonify({
                'success': False,
                'error': 'Missing filename in database'
            }), 500

        file_path = os.path.join(DATA_DIR, filename)

        if not os.path.exists(file_path):
            return jsonify({
                'success': False,
                'error': f'File not found on disk: {file_path}'
            }), 404
        
        # Track document usage
        token = request.cookies.get('session_token')
        user_id = None
        if token:
            is_valid, user_info = auth_manager.validate_session(token)
            if is_valid:
                user_id = user_info.get('id')
                
                # Log usage in database
                from rag_chatbot.database import db
                conn = db.get_connection()
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO document_usage (document_id, document_type, user_id, action_type)
                    VALUES (?, 'company', ?, 'download')
                """, (doc_id, user_id))
                conn.commit()
                conn.close()
        
        directory = os.path.dirname(file_path)
        filename = os.path.basename(file_path)
        return send_from_directory(directory, filename, as_attachment=True)

    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500



@app.route('/api/clear-chat', methods=['POST'])
def clear_chat():
    """Clear chat history for a session"""
    try:
        data = request.json
        session_id = data.get('session_id')
        
        if session_id and session_id in sessions:
            sessions[session_id] = {}
        
        # Clear pipeline conversation
        pipeline.clear_conversation()
        
        return jsonify({
            'success': True,
            'message': 'Chat history cleared'
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/news/<role_type>', methods=['GET'])
def get_news_for_role(role_type):
    """Get news articles for a specific role"""
    try:
        from rag_chatbot.database import news_manager
        
        limit = request.args.get('limit', 20, type=int)
        sort_by = request.args.get('sort', 'date')  # 'date' or 'interaction'
        
        articles = news_manager.get_articles_by_role(role_type, limit=limit, sort_by=sort_by)
        
        return jsonify({
            'success': True,
            'articles': articles,
            'count': len(articles)
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/news/fetch', methods=['POST'])
@require_auth()
def fetch_news():
    """Manually trigger news fetch for user's role"""
    try:
        from rag_chatbot.database import user_role_manager
        from rag_chatbot.workers.news_fetcher import NewsFetcher
        
        user_id = request.user.get('id')
        user_role_info = user_role_manager.get_user_role(user_id)
        
        if not user_role_info:
            return jsonify({
                'success': False,
                'error': 'Please set your technical role first'
            }), 400
        
        role_type = user_role_info['role_type']
        
        # Fetch news
        fetcher = NewsFetcher(pipeline)
        count = fetcher.fetch_news_for_role(role_type, fetch_content=True)
        
        # Embed articles
        if count > 0:
            fetcher.embed_articles(role_type, limit=count)
        
        # Update online view counts after fetching
        from rag_chatbot.workers.news_fetcher import update_online_view_counts
        update_online_view_counts()
        
        return jsonify({
            'success': True,
            'message': f'Fetched {count} new articles',
            'count': count
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/news/update-views', methods=['POST'])
@require_auth(optional=True)
def update_news_views():
    """Manually update online view counts for news articles"""
    try:
        from rag_chatbot.workers.news_fetcher import update_online_view_counts
        count = update_online_view_counts()
        
        return jsonify({
            'success': True,
            'message': f'Updated online views for {count} articles',
            'count': count
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/news/summarize/<int:article_id>', methods=['POST'])
@require_auth(optional=True)
def summarize_article(article_id):
    """Return a detailed, AI-style summary for a specific article."""
    try:
        from rag_chatbot.database import news_manager
        from rag_chatbot.workers.news_fetcher import NewsFetcher

        data = request.json or {}
        session_id = data.get('session_id') or str(uuid.uuid4())
        question = data.get('question') or f'Summarize article {article_id}'

        article = news_manager.get_article_by_id(article_id)
        if not article:
            return jsonify({
                'success': False,
                'error': 'Article not found'
            }), 404

        # Increment summary interaction count
        news_manager.increment_summary_count(article_id)

        print(f'[INFO] Summarize request for article ID {article_id}: {article.get("title", "Unknown")[:80]}')

        # Always try to fetch fresh content for better summaries
        content = ''
        if article.get('url'):
            print(f'[INFO] Fetching live article from: {article["url"]}')
            try:
                fetcher = NewsFetcher()
                fetched = fetcher.fetch_article_content(article['url'])
                
                if fetched:
                    word_count = len(fetched.split())
                    print(f'[INFO] Fetched content: {len(fetched)} chars, {word_count} words')
                    
                    if word_count > 80 and not is_placeholder_snippet(fetched):
                        content = fetched
                        news_manager.update_article_content(article_id, fetched)
                        print('[INFO] Stored fresh fetched content in DB')
                    else:
                        print(f'[WARN] Fetched content invalid ({word_count} words) or placeholder')
                else:
                    print('[WARN] fetch_article_content returned empty')
            except Exception as fetch_err:
                print(f'[ERROR] Content fetch failed: {fetch_err}')
                import traceback
                traceback.print_exc()
        
        # Fallback to stored content if fetch failed
        if not content:
            stored = article.get('content') or ''
            if stored and not is_placeholder_snippet(stored) and len(stored.split()) > 50:
                content = stored
                print(f'[INFO] Using stored content: {len(stored)} chars, {len(stored.split())} words')
            else:
                print('[WARN] Stored content also insufficient')

        print(f'[INFO] Final content for summarization: {len(content)} chars, {len(content.split())} words')

        if not content or len(content.split()) < 30:
            print('[ERROR] Insufficient content for meaningful summarization')
            return jsonify({
                'success': False,
                'error': 'Unable to fetch full article content. The article may be behind a paywall or the source may be blocking automated access.'
            }), 500

        # Try LLM first
        llm_summary = generate_llm_article_summary(article, content)
        if llm_summary and len(llm_summary.split()) > 20:
            summary_text = llm_summary
            print('[INFO] Using LLM summary')
        else:
            print('[WARN] LLM summary failed or too short, trying structured brief...')
            structured_brief = build_structured_brief(article, content)
            if structured_brief and len(structured_brief.split()) > 20:
                summary_text = structured_brief
                print('[INFO] Using structured brief')
            else:
                print('[WARN] Structured brief failed, using fallback summary...')
                summary_text = build_article_summary(article, content_override=content)
                print('[INFO] Using fallback summary')
        
        print(f'[INFO] Summary source: {"LLM" if llm_summary else "Structured" if structured_brief else "Fallback"}')
        if not summary_text.strip():
            return jsonify({
                'success': False,
                'error': 'Unable to summarize this article right now'
            }), 500

        source_name = article.get('source_name') or article.get('source') or 'Tech News'
        sources = [{
            'filename': f"{source_name} article",
            'page': article.get('published_date'),
            'score': 1.0,
            'link': article.get('url')
        }]

        user_id = None
        token = request.cookies.get('session_token')
        if token:
            is_valid, user_info = auth_manager.validate_session(token)
            if is_valid:
                user_id = user_info.get('id')

        record_chat_interaction(session_id, question, summary_text, sources, user_id)

        return jsonify({
            'success': True,
            'summary': summary_text,
            'session_id': session_id,
            'sources': sources,
            'article': {
                'id': article_id,
                'title': article.get('title'),
                'url': article.get('url'),
                'published_date': article.get('published_date'),
                'source_name': source_name
            }
        })

    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/news/explain/<int:article_id>', methods=['POST'])
@require_auth(optional=True)
def explain_article_terms(article_id):
    """Explain technical terms in an article to help readers understand."""
    try:
        from rag_chatbot.database import news_manager
        from rag_chatbot.workers.news_fetcher import NewsFetcher

        data = request.json or {}
        session_id = data.get('session_id') or str(uuid.uuid4())
        question = data.get('question') or f'Explain technical terms in article {article_id}'

        article = news_manager.get_article_by_id(article_id)
        if not article:
            return jsonify({
                'success': False,
                'error': 'Article not found'
            }), 404

        # Increment explain interaction count
        news_manager.increment_explain_count(article_id)

        print(f'[INFO] Explain request for article ID {article_id}: {article.get("title", "Unknown")[:80]}')

        # Fetch content if needed
        content = article.get('content') or ''
        if not content and article.get('url'):
            print(f'[INFO] Fetching content from: {article["url"]}')
            try:
                fetcher = NewsFetcher()
                fetched = fetcher.fetch_article_content(article['url'])
                if fetched:
                    content = fetched
                    news_manager.update_article_content(article_id, content)
                    print(f'[INFO] Stored fresh fetched content in DB')
            except Exception as fetch_err:
                print(f'[WARN] Failed to fetch content: {fetch_err}')

        if not content or len(content.split()) < 50:
            summary = article.get('summary') or ''
            if len(summary.split()) < 20:
                return jsonify({
                    'success': False,
                    'error': 'Not enough content to explain terms'
                }), 400
            content = summary

        print(f'[INFO] Explaining terms for article: {article.get("title", "Unknown")[:50]}...')
        print(f'[INFO] Content length for LLM: {len(content)} chars')

        # Create explanation prompt
        explain_prompt = f"""Hãy giải thích tất cả các thuật ngữ kỹ thuật trong bài viết sau để người đọc hiểu rõ nội dung:

Tiêu đề: {article.get('title')}

Nội dung:
{content[:10000]}

Hãy liệt kê và giải thích:
1. Các thuật ngữ kỹ thuật
2. Công nghệ/Framework được đề cập
3. Khái niệm quan trọng
4. Viết tắt (acronyms)

Giải thích bằng tiếng Việt, đơn giản dễ hiểu."""

        # Use the LLM directly (same as summarize endpoint)
        llm = pipeline._default_model
        if not llm:
            print('[WARN] LLM not initialized')
            return jsonify({
                'success': False,
                'error': 'LLM not available'
            }), 500

        print(f'[INFO] Calling LLM for term explanation...')
        try:
            result = llm.complete(explain_prompt)
            explanation = getattr(result, 'text', '') if result is not None else ''
            explanation = (explanation or '').strip()
        except Exception as llm_err:
            print(f'[ERROR] LLM call failed: {llm_err}')
            import traceback
            traceback.print_exc()
            return jsonify({
                'success': False,
                'error': f'LLM error: {str(llm_err)}'
            }), 500
        
        print(f'[INFO] LLM returned {len(explanation)} chars')

        if not explanation:
            return jsonify({
                'success': False,
                'error': 'LLM returned empty response'
            }), 500

        source_name = article.get('source_name') or article.get('source') or 'Tech News'
        sources = [{
            'filename': f"{source_name} article",
            'page': article.get('published_date'),
            'score': 1.0,
            'link': article.get('url')
        }]

        user_id = None
        token = request.cookies.get('session_token')
        if token:
            is_valid, user_info = auth_manager.validate_session(token)
            if is_valid:
                user_id = user_info.get('id')

        record_chat_interaction(session_id, question, explanation, sources, user_id)

        return jsonify({
            'success': True,
            'explanation': explanation,
            'session_id': session_id,
            'sources': sources
        })

    except Exception as e:
        print(f'[ERROR] Explain terms failed: {e}')
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/news/view/<int:article_id>', methods=['POST'])
def increment_article_view(article_id):
    """Increment view count when user reads an article (clicks link)."""
    try:
        from rag_chatbot.database import news_manager
        news_manager.increment_view_count(article_id)
        news_manager.increment_link_click_count(article_id)
        return jsonify({'success': True})
    except Exception as e:
        print(f'[ERROR] Failed to increment view: {e}')
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/user/role', methods=['GET', 'POST'])
def user_role():
    """Get or set user's technical role"""
    try:
        from rag_chatbot.database import user_role_manager
        
        # Try to get user from session, but don't require it
        user_id = None
        token = request.cookies.get('session_token')
        if token:
            is_valid, user_info = auth_manager.validate_session(token)
            if is_valid and user_info:
                user_id = user_info.get('id')
        
        if request.method == 'GET':
            if user_id:
                role_info = user_role_manager.get_user_role(user_id)
                if role_info:
                    return jsonify({
                        'success': True,
                        'role': role_info
                    })
            
            # Default fallback for users without a role set
            return jsonify({
                'success': True,
                'role': {
                    'role_type': 'security_engineer',
                    'department': 'Engineering'
                }
            })
        
        else:  # POST - requires authentication
            if not user_id:
                return jsonify({
                    'success': False,
                    'error': 'Authentication required'
                }), 401
                
            data = request.json
            role_type = data.get('role_type')
            department = data.get('department')
            
            if not role_type:
                return jsonify({
                    'success': False,
                    'error': 'role_type is required'
                }), 400
            
            user_role_manager.set_user_role(user_id, role_type, department)
            
            return jsonify({
                'success': True,
                'message': 'Role updated successfully'
            })
            
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/user-documents/upload', methods=['POST'])
@require_auth()
def upload_user_document():
    """Upload a document that is immediately available in the knowledge base."""
    try:
        from rag_chatbot.database import user_document_manager, user_role_manager, document_manager

        user_id = request.user.get('id')

        # Get user's role
        user_role_info = user_role_manager.get_user_role(user_id)
        if not user_role_info:
            return jsonify({
                'success': False,
                'error': 'Please set your technical role first'
            }), 400

        role_type = user_role_info['role_type']

        # Check if file was uploaded
        if 'file' not in request.files:
            return jsonify({
                'success': False,
                'error': 'No file uploaded'
            }), 400

        file = request.files['file']
        description = request.form.get('description', '')
        folder = request.form.get('folder', 'Chung')  # Get folder from form
        
        # NOTE: DO NOT call ensure_folder_exists() here!
        # Personal folders should NOT be added to document_folders table (company folders)
        # Personal folder names are stored directly in user_documents.folder column

        if file.filename == '':
            return jsonify({
                'success': False,
                'error': 'No file selected'
            }), 400

        allowed_extensions = ['.pdf', '.docx', '.txt', '.md', '.markdown']
        file_ext = os.path.splitext(file.filename)[1].lower()

        if file_ext not in allowed_extensions:
            return jsonify({
                'success': False,
                'error': f'File type not allowed. Allowed: {", ".join(allowed_extensions)}'
            }), 400

        os.makedirs(DATA_DIR, exist_ok=True)
        unique_filename = f"{uuid.uuid4()}_{file.filename}"
        file_path = os.path.join(DATA_DIR, unique_filename)
        file.save(file_path)

        file_size = os.path.getsize(file_path)

        # Store ONLY in user_documents table (personal documents, not company-wide)
        from rag_chatbot.database import db
        conn = db.get_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT INTO user_documents 
            (filename, original_filename, file_type, file_size, uploaded_by, role_type, description, status, approved_by, approved_at, folder)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'approved', ?, datetime('now'), ?)
        """, (
            unique_filename,
            file.filename,
            file_ext,
            file_size,
            user_id,
            role_type,
            description,
            user_id,
            folder
        ))
        user_doc_id = cursor.lastrowid
        
        conn.commit()
        conn.close()

        # Ingest immediately so the document is searchable
        try:
            pipeline.store_nodes(input_files=[file_path])
            pipeline.set_chat_mode()
        except Exception as ingest_error:
            print(f"[UPLOAD] Warning: document saved but ingestion failed: {ingest_error}")

        return jsonify({
            'success': True,
            'message': 'Personal document uploaded successfully',
            'user_document_id': user_doc_id
        })

    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/user-documents/my', methods=['GET'])
@require_auth()
def get_my_documents():
    """Get documents uploaded by current user"""
    try:
        from rag_chatbot.database import user_document_manager
        
        user_id = request.user.get('id')
        documents = user_document_manager.get_user_documents(user_id)
        
        return jsonify({
            'success': True,
            'documents': documents
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/user-documents/approved/<role_type>', methods=['GET'])
def get_approved_documents_for_role(role_type):
    """Get all approved documents for a specific role"""
    try:
        from rag_chatbot.database import user_document_manager
        
        documents = user_document_manager.get_approved_documents_by_role(role_type)
        
        return jsonify({
            'success': True,
            'documents': documents
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


# ==================== PINNED DOCUMENTS API ====================

@app.route('/api/pinned-documents', methods=['GET'])
def get_pinned_documents():
    """Get all pinned documents for the current user (including admin-pinned)"""
    try:
        from rag_chatbot.database import db
        
        token = request.cookies.get('session_token')
        if not token:
            return jsonify({'success': False, 'error': 'Authentication required'}), 401
        
        is_valid, user_info = auth_manager.validate_session(token)
        if not is_valid:
            return jsonify({'success': False, 'error': 'Invalid session'}), 401
        
        user_id = user_info.get('id')
        
        conn = db.get_connection()
        cursor = conn.cursor()
        
        pinned_docs = []
        
        # Get admin-pinned documents first (priority)
        cursor.execute("""
            SELECT 
                d.id, d.original_filename, d.file_type, d.folder, d.upload_date, d.metadata,
                COALESCE(usage.usage_count, 0) as usage_count
            FROM documents d
            LEFT JOIN (
                SELECT document_id, COUNT(*) as usage_count
                FROM document_usage
                WHERE document_type = 'company'
                GROUP BY document_id
            ) usage ON d.id = usage.document_id
            WHERE d.admin_pinned = 1 AND d.status = 'active'
            ORDER BY d.upload_date DESC
        """)
        
        for row in cursor.fetchall():
            metadata = json.loads(row[5]) if row[5] else {}
            pinned_docs.append({
                'pin_id': None,
                'document_id': row[0],
                'document_type': 'company',
                'pinned_at': row[4],
                'filename': row[1],
                'file_type': row[2],
                'folder': row[3],
                'created_at': row[4],
                'admin_pinned': True,
                'description': metadata.get('description', ''),
                'usage_count': row[6]
            })
        
        admin_pinned_ids = {doc['document_id'] for doc in pinned_docs}
        
        # Get user-pinned company documents (excluding admin-pinned)
        cursor.execute("""
            SELECT p.id, p.document_id, p.document_type, p.pinned_at,
                   d.original_filename, d.file_type, d.folder, d.upload_date, d.metadata,
                   COALESCE(usage.usage_count, 0) as usage_count
            FROM pinned_documents p
            JOIN documents d ON p.document_id = d.id
            LEFT JOIN (
                SELECT document_id, COUNT(*) as usage_count
                FROM document_usage
                WHERE document_type = 'company'
                GROUP BY document_id
            ) usage ON d.id = usage.document_id
            WHERE p.user_id = ? AND p.document_type = 'company'
            ORDER BY p.pinned_at DESC
        """, (user_id,))
        
        for row in cursor.fetchall():
            if row[1] not in admin_pinned_ids:
                metadata = json.loads(row[8]) if row[8] else {}
                pinned_docs.append({
                    'pin_id': row[0],
                    'document_id': row[1],
                    'document_type': row[2],
                    'pinned_at': row[3],
                    'filename': row[4],
                    'file_type': row[5],
                    'folder': row[6],
                    'created_at': row[7],
                    'admin_pinned': False,
                    'description': metadata.get('description', ''),
                    'usage_count': row[9]
                })
        
        # Get pinned personal documents
        cursor.execute("""
            SELECT p.id, p.document_id, p.document_type, p.pinned_at,
                   ud.original_filename, ud.file_type, ud.folder, ud.created_at, ud.description,
                   COALESCE(usage.usage_count, 0) as usage_count
            FROM pinned_documents p
            JOIN user_documents ud ON p.document_id = ud.id
            LEFT JOIN (
                SELECT document_id, COUNT(*) as usage_count
                FROM document_usage
                WHERE document_type = 'personal'
                GROUP BY document_id
            ) usage ON ud.id = usage.document_id
            WHERE p.user_id = ? AND p.document_type = 'personal'
            ORDER BY p.pinned_at DESC
        """, (user_id,))
        
        for row in cursor.fetchall():
            pinned_docs.append({
                'pin_id': row[0],
                'document_id': row[1],
                'document_type': row[2],
                'pinned_at': row[3],
                'filename': row[4],
                'file_type': row[5],
                'folder': row[6],
                'created_at': row[7],
                'admin_pinned': False,
                'description': row[8] or '',
                'usage_count': row[9]
            })
        
        conn.close()
        
        return jsonify({
            'success': True,
            'documents': pinned_docs
        })
    except Exception as e:
        print(f"Error getting pinned documents: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/documents/<int:doc_id>/pin', methods=['POST'])
def pin_document(doc_id):
    """Pin a company document"""
    try:
        from rag_chatbot.database import db
        
        token = request.cookies.get('session_token')
        if not token:
            return jsonify({'success': False, 'error': 'Authentication required'}), 401
        
        is_valid, user_info = auth_manager.validate_session(token)
        if not is_valid:
            return jsonify({'success': False, 'error': 'Invalid session'}), 401
        
        user_id = user_info.get('id')
        
        conn = db.get_connection()
        cursor = conn.cursor()
        
        # Check if document is admin-pinned
        cursor.execute("SELECT admin_pinned FROM documents WHERE id = ?", (doc_id,))
        row = cursor.fetchone()
        if row and row[0] == 1:
            conn.close()
            return jsonify({'success': False, 'error': 'Document is pinned by admin'})
        
        # Check if already pinned
        cursor.execute("""
            SELECT id FROM pinned_documents 
            WHERE user_id = ? AND document_id = ? AND document_type = 'company'
        """, (user_id, doc_id))
        
        if cursor.fetchone():
            conn.close()
            return jsonify({'success': False, 'error': 'Document already pinned'})
        
        # Add pin
        cursor.execute("""
            INSERT INTO pinned_documents (user_id, document_id, document_type)
            VALUES (?, ?, 'company')
        """, (user_id, doc_id))
        
        conn.commit()
        conn.close()
        
        return jsonify({'success': True, 'message': 'Document pinned'})
    except Exception as e:
        print(f"Error pinning document: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/documents/<int:doc_id>/unpin', methods=['POST'])
def unpin_document(doc_id):
    """Unpin a company document"""
    try:
        from rag_chatbot.database import db
        
        token = request.cookies.get('session_token')
        if not token:
            return jsonify({'success': False, 'error': 'Authentication required'}), 401
        
        is_valid, user_info = auth_manager.validate_session(token)
        if not is_valid:
            return jsonify({'success': False, 'error': 'Invalid session'}), 401
        
        user_id = user_info.get('id')
        
        conn = db.get_connection()
        cursor = conn.cursor()
        
        # Check if document is admin-pinned
        cursor.execute("SELECT admin_pinned FROM documents WHERE id = ?", (doc_id,))
        row = cursor.fetchone()
        if row and row[0] == 1:
            conn.close()
            return jsonify({'success': False, 'error': 'Cannot unpin document pinned by admin'})
        
        cursor.execute("""
            DELETE FROM pinned_documents 
            WHERE user_id = ? AND document_id = ? AND document_type = 'company'
        """, (user_id, doc_id))
        
        conn.commit()
        conn.close()
        
        return jsonify({'success': True, 'message': 'Document unpinned'})
    except Exception as e:
        print(f"Error unpinning document: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/user-documents/<int:doc_id>/pin', methods=['POST'])
def pin_user_document(doc_id):
    """Pin a personal document"""
    try:
        from rag_chatbot.database import db
        
        token = request.cookies.get('session_token')
        if not token:
            return jsonify({'success': False, 'error': 'Authentication required'}), 401
        
        is_valid, user_info = auth_manager.validate_session(token)
        if not is_valid:
            return jsonify({'success': False, 'error': 'Invalid session'}), 401
        
        user_id = user_info.get('id')
        
        conn = db.get_connection()
        cursor = conn.cursor()
        
        # Check if already pinned
        cursor.execute("""
            SELECT id FROM pinned_documents 
            WHERE user_id = ? AND document_id = ? AND document_type = 'personal'
        """, (user_id, doc_id))
        
        if cursor.fetchone():
            conn.close()
            return jsonify({'success': False, 'error': 'Document already pinned'})
        
        # Add pin
        cursor.execute("""
            INSERT INTO pinned_documents (user_id, document_id, document_type)
            VALUES (?, ?, 'personal')
        """, (user_id, doc_id))
        
        conn.commit()
        conn.close()
        
        return jsonify({'success': True, 'message': 'Document pinned'})
    except Exception as e:
        print(f"Error pinning document: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/user-documents/<int:doc_id>/unpin', methods=['POST'])
def unpin_user_document(doc_id):
    """Unpin a personal document"""
    try:
        from rag_chatbot.database import db
        
        token = request.cookies.get('session_token')
        if not token:
            return jsonify({'success': False, 'error': 'Authentication required'}), 401
        
        is_valid, user_info = auth_manager.validate_session(token)
        if not is_valid:
            return jsonify({'success': False, 'error': 'Invalid session'}), 401
        
        user_id = user_info.get('id')
        
        conn = db.get_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            DELETE FROM pinned_documents 
            WHERE user_id = ? AND document_id = ? AND document_type = 'personal'
        """, (user_id, doc_id))
        
        conn.commit()
        conn.close()
        
        return jsonify({'success': True, 'message': 'Document unpinned'})
    except Exception as e:
        print(f"Error unpinning document: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/documents/<int:doc_id>/pin-status', methods=['GET'])
def get_pin_status(doc_id):
    """Check if a company document is pinned by the current user"""
    try:
        from rag_chatbot.database import db
        
        token = request.cookies.get('session_token')
        if not token:
            return jsonify({'success': False, 'error': 'Authentication required'}), 401
        
        is_valid, user_info = auth_manager.validate_session(token)
        if not is_valid:
            return jsonify({'success': False, 'error': 'Invalid session'}), 401
        
        user_id = user_info.get('id')
        
        conn = db.get_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT id FROM pinned_documents 
            WHERE user_id = ? AND document_id = ? AND document_type = 'company'
        """, (user_id, doc_id))
        
        is_pinned = cursor.fetchone() is not None
        conn.close()
        
        return jsonify({'success': True, 'pinned': is_pinned})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/user-documents/<int:doc_id>/pin-status', methods=['GET'])
def get_user_doc_pin_status(doc_id):
    """Check if a personal document is pinned by the current user"""
    try:
        from rag_chatbot.database import db
        
        token = request.cookies.get('session_token')
        if not token:
            return jsonify({'success': False, 'error': 'Authentication required'}), 401
        
        is_valid, user_info = auth_manager.validate_session(token)
        if not is_valid:
            return jsonify({'success': False, 'error': 'Invalid session'}), 401
        
        user_id = user_info.get('id')
        
        conn = db.get_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT id FROM pinned_documents 
            WHERE user_id = ? AND document_id = ? AND document_type = 'personal'
        """, (user_id, doc_id))
        
        is_pinned = cursor.fetchone() is not None
        conn.close()
        
        return jsonify({'success': True, 'pinned': is_pinned})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# ==================== PERSONAL FOLDER MANAGEMENT API ====================

@app.route('/api/user-documents/folders/rename', methods=['POST'])
def rename_personal_folder():
    """Rename a personal folder (updates all documents in it)"""
    try:
        from rag_chatbot.database import db
        
        token = request.cookies.get('session_token')
        if not token:
            return jsonify({'success': False, 'error': 'Authentication required'}), 401
        
        is_valid, user_info = auth_manager.validate_session(token)
        if not is_valid:
            return jsonify({'success': False, 'error': 'Invalid session'}), 401
        
        user_id = user_info.get('id')
        data = request.get_json()
        old_name = data.get('old_name')
        new_name = data.get('new_name')
        
        if not old_name or not new_name:
            return jsonify({'success': False, 'error': 'Missing folder names'}), 400
        
        conn = db.get_connection()
        cursor = conn.cursor()
        
        # Update all documents in the folder
        cursor.execute("""
            UPDATE user_documents 
            SET folder = ?
            WHERE folder = ? AND uploaded_by = ?
        """, (new_name, old_name, user_id))
        
        updated_count = cursor.rowcount
        conn.commit()
        conn.close()
        
        return jsonify({
            'success': True,
            'message': f'Folder renamed. {updated_count} documents updated.'
        })
    except Exception as e:
        print(f"Error renaming folder: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/user-documents/folders/delete', methods=['POST'])
def delete_personal_folder():
    """Delete a personal folder and all documents in it"""
    try:
        from rag_chatbot.database import db
        
        token = request.cookies.get('session_token')
        if not token:
            return jsonify({'success': False, 'error': 'Authentication required'}), 401
        
        is_valid, user_info = auth_manager.validate_session(token)
        if not is_valid:
            return jsonify({'success': False, 'error': 'Invalid session'}), 401
        
        user_id = user_info.get('id')
        data = request.get_json()
        folder_name = data.get('folder_name')
        
        if not folder_name:
            return jsonify({'success': False, 'error': 'Missing folder name'}), 400
        
        conn = db.get_connection()
        cursor = conn.cursor()
        
        # Get all files to delete from disk
        cursor.execute("""
            SELECT filename FROM user_documents 
            WHERE folder = ? AND uploaded_by = ?
        """, (folder_name, user_id))
        
        files_to_delete = [row[0] for row in cursor.fetchall()]
        
        # Delete documents from database
        cursor.execute("""
            DELETE FROM user_documents 
            WHERE folder = ? AND uploaded_by = ?
        """, (folder_name, user_id))
        
        deleted_count = cursor.rowcount
        conn.commit()
        conn.close()
        
        # Delete physical files
        for filename in files_to_delete:
            try:
                file_path = os.path.join(DATA_DIR, filename)
                if os.path.exists(file_path):
                    os.remove(file_path)
            except Exception as e:
                print(f"Warning: Could not delete file {filename}: {e}")
        
        return jsonify({
            'success': True,
            'message': f'Folder deleted. {deleted_count} documents removed.'
        })
    except Exception as e:
        print(f"Error deleting folder: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/user-documents/<int:doc_id>/rename', methods=['POST'])
def rename_personal_document(doc_id):
    """Rename a personal document"""
    try:
        from rag_chatbot.database import db
        
        token = request.cookies.get('session_token')
        if not token:
            return jsonify({'success': False, 'error': 'Authentication required'}), 401
        
        is_valid, user_info = auth_manager.validate_session(token)
        if not is_valid:
            return jsonify({'success': False, 'error': 'Invalid session'}), 401
        
        user_id = user_info.get('id')
        data = request.get_json()
        new_name = data.get('new_name')
        
        if not new_name:
            return jsonify({'success': False, 'error': 'Missing new name'}), 400
        
        conn = db.get_connection()
        cursor = conn.cursor()
        
        # Verify ownership
        cursor.execute("""
            SELECT id FROM user_documents 
            WHERE id = ? AND uploaded_by = ?
        """, (doc_id, user_id))
        
        if not cursor.fetchone():
            conn.close()
            return jsonify({'success': False, 'error': 'Document not found or not authorized'}), 404
        
        # Update document name
        cursor.execute("""
            UPDATE user_documents 
            SET original_filename = ?
            WHERE id = ? AND uploaded_by = ?
        """, (new_name, doc_id, user_id))
        
        conn.commit()
        conn.close()
        
        return jsonify({
            'success': True,
            'message': 'Document renamed successfully'
        })
    except Exception as e:
        print(f"Error renaming document: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/internal/restart', methods=['POST'])
@require_internal_service_token
def internal_restart():
    """Internal endpoint for triggering restart from admin server"""
    import threading
    import time
    
    def delayed_shutdown():
        time.sleep(1)
        os._exit(0)
    
    threading.Thread(target=delayed_shutdown, daemon=True).start()
    
    return jsonify({
        'success': True,
        'message': 'User server is restarting...'
    })


@app.route('/api/agent/chat', methods=['POST'])
@require_auth(optional=False)
def agent_chat():
    """Agent-style endpoint (MCP-backed).

    Minimal demo behavior:
      - default: retrieve chunks (via MCP) and answer using LLM
    """
    try:
        data = request.get_json(silent=True) or {}
        message = (data.get('message') or '').strip()
        if not message:
            return jsonify({'success': False, 'error': 'Missing message'}), 400

        from rag_chatbot.mcp_client import call_mcp_tool

        lowered = message.lower()

        async def _run_agent() -> dict:
            # Simple, provider-agnostic heuristics (no native function-calling required).
            if any(k in lowered for k in ['list documents', 'list docs', 'danh sách tài liệu', 'danh sach tai lieu']):
                return await call_mcp_tool('list_documents', {})

            # Default: search chunks then ask LLM to answer grounded in those chunks.
            search = await call_mcp_tool('search_chunks', {'query': message, 'top_k': 6})
            results = (search or {}).get('results') or []
            if not results:
                return {
                    'success': True,
                    'answer': 'No relevant internal documents were found for this question.',
                    'sources': [],
                }

            # Build a compact context window for the LLM.
            context_lines = []
            sources = []
            for idx, r in enumerate(results, start=1):
                filename = r.get('filename')
                page = r.get('page')
                sources.append({'filename': filename, 'page': page, 'score': r.get('score')})
                context_lines.append(f"[{idx}] {filename} (page {page})\n{r.get('text','')}")

            prompt = (
                "You are an internal knowledge assistant. Answer the user's question using ONLY the provided sources. "
                "If the sources are insufficient, say what is missing.\n\n"
                f"Question: {message}\n\n"
                "Sources:\n" + "\n\n".join(context_lines) + "\n\n"
                "Write a concise, factual answer."
            )

            llm = getattr(pipeline, '_default_model', None)
            if not llm:
                return {'success': False, 'error': 'LLM not initialized'}

            result = llm.complete(prompt)
            text = getattr(result, 'text', '') if result is not None else ''
            answer = (text or '').strip()
            return {'success': True, 'answer': answer, 'sources': sources}

        output = asyncio.run(_run_agent())
        # Normalize output format for UI
        if 'answer' in output:
            return jsonify(output)
        return jsonify({'success': True, 'result': output})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/agent/doc-improve', methods=['POST'])
@require_auth(optional=False)
def agent_doc_improve():
    """Document Improvement Agent (MCP-backed).

    Audits a specific document and proposes missing sections / improvements.

    Request JSON:
      - document_type: 'company' | 'personal'
      - document_id: int
      - goal: str (optional, e.g. 'policy' | 'sop')
      - top_k: int (optional, default 3)
    """
    try:
        data = request.get_json(silent=True) or {}
        document_type = (data.get('document_type') or '').strip().lower()
        document_id = data.get('document_id')
        goal = (data.get('goal') or 'policy').strip()
        top_k = int(data.get('top_k') or 3)

        if document_type not in {'company', 'personal'}:
            return jsonify({'success': False, 'error': "document_type must be 'company' or 'personal'"}), 400
        if document_id is None:
            return jsonify({'success': False, 'error': 'Missing document_id'}), 400

        from rag_chatbot.mcp_client import call_mcp_tool
        from rag_chatbot.agents.doc_improve_agent import improve_document

        llm = getattr(pipeline, '_default_model', None)
        if not llm:
            return jsonify({'success': False, 'error': 'LLM not initialized'}), 503

        async def _run() -> dict:
            return await improve_document(
                document_type=document_type,
                document_id=int(document_id),
                goal=goal,
                call_mcp_tool=call_mcp_tool,
                llm=llm,
                top_k=top_k,
            )

        out = asyncio.run(_run())
        return jsonify(out)
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/internal/agent/doc-improve', methods=['POST'])
@require_internal_service_token
def internal_agent_doc_improve():
    """Internal-only version of Document Improvement Agent."""
    try:
        data = request.get_json(silent=True) or {}
        document_type = (data.get('document_type') or '').strip().lower()
        document_id = data.get('document_id')
        goal = (data.get('goal') or 'policy').strip()
        top_k = int(data.get('top_k') or 3)

        if document_type not in {'company', 'personal'}:
            return jsonify({'success': False, 'error': "document_type must be 'company' or 'personal'"}), 400
        if document_id is None:
            return jsonify({'success': False, 'error': 'Missing document_id'}), 400

        from rag_chatbot.mcp_client import call_mcp_tool
        from rag_chatbot.agents.doc_improve_agent import improve_document

        llm = getattr(pipeline, '_default_model', None)
        if not llm:
            return jsonify({'success': False, 'error': 'LLM not initialized'}), 503

        async def _run() -> dict:
            return await improve_document(
                document_type=document_type,
                document_id=int(document_id),
                goal=goal,
                call_mcp_tool=call_mcp_tool,
                llm=llm,
                top_k=top_k,
            )

        out = asyncio.run(_run())
        return jsonify(out)
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


