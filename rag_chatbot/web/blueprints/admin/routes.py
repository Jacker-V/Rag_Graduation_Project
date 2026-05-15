"""
Flask backend API for the Admin Interface
Serves the HTML UI and provides REST API endpoints for:
- Uploading and managing documents
- Viewing and resolving user reports
- System statistics
- User authentication
"""
import os
import json
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv(override=True)

from flask import Blueprint, request, jsonify, send_from_directory, redirect
from werkzeug.utils import secure_filename
from rag_chatbot.database import document_manager, report_manager
from pathlib import Path
from functools import wraps


def _user_internal_api_base() -> str:
    """Base URL for calling user-web from admin-web.

    - Local dev: http://localhost:7861/
    - Docker: http://knowledge-user:7861/
    - Override: USER_API_BASE_URL
    """

    explicit = os.environ.get('USER_API_BASE_URL', '').strip()
    if explicit:
        return explicit.rstrip('/') + '/'

    host = request.host.rsplit(':', 1)[0]
    if host in {'localhost', '127.0.0.1'}:
        return f"http://{host}:7861/"

    return 'http://knowledge-user:7861/'


def _parse_document_ref(ref: str) -> tuple[str, int] | None:
    ref = (ref or '').strip()
    if not ref:
        return None

    # Accept: company#1, personal#9
    if '#' in ref:
        left, right = ref.split('#', 1)
        document_type = left.strip().lower()
        try:
            document_id = int(right.strip())
        except ValueError:
            return None
        if document_type in {'company', 'personal'}:
            return document_type, document_id
        return None

    # Accept: company 1, personal 9
    parts = ref.split()
    if len(parts) == 2:
        document_type = parts[0].strip().lower()
        try:
            document_id = int(parts[1].strip())
        except ValueError:
            return None
        if document_type in {'company', 'personal'}:
            return document_type, document_id
    return None


def _env_truthy(name: str) -> bool:
    return os.environ.get(name, '').strip().lower() in {'1', 'true', 'yes'}


def _cookie_secure() -> bool:
    # request.is_secure will reflect X-Forwarded-Proto when ProxyFix is enabled.
    return request.is_secure


def _https_required_error_response():
    host = (request.host or '').split(':', 1)[0].strip()
    # Prefer configured public domain in proxy mode.
    if _env_truthy('BEHIND_PROXY'):
        host = (os.environ.get('ADMIN_DOMAIN') or host).strip() or host
    hint = f"Please access via https://{host}/login (do not use :7860/:7861)."
    return jsonify({'success': False, 'error': hint}), 400


def _cookie_domain() -> str | None:
    """Return a shared cookie domain for admin/user subdomains.

    In HTTPS deployment, admin and user live on different subdomains
    (e.g. knowledgeadmin.duckdns.org / knowledgeuser.duckdns.org).
    Without an explicit cookie domain, browsers will scope the cookie to
    the current host only, causing cross-subdomain redirects to lose the
    session and potentially loop between login pages.
    """

    admin_domain = (os.environ.get('ADMIN_DOMAIN', '') or '').strip().lower()
    user_domain = (os.environ.get('USER_DOMAIN', '') or '').strip().lower()
    if not admin_domain or not user_domain:
        return None

    # Don't set Domain for localhost/IPs.
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

    # Need at least a registrable-ish suffix (2+ labels).
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


def _public_user_url() -> str:
    explicit = os.environ.get('USER_PUBLIC_URL', '').strip()
    if explicit:
        return explicit.rstrip('/') + '/'

    if _env_truthy('BEHIND_PROXY'):
        domain = os.environ.get('USER_DOMAIN', '').strip()
        if domain:
            return f"{request.scheme}://{domain.rstrip('/')}/"

    host = request.host.rsplit(':', 1)[0]
    return f"http://{host}:7861/"

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
DATA_DIR = str(PROJECT_ROOT / 'data' / 'data')
DB_PATH = str(PROJECT_ROOT / 'data' / 'knowledge_base.db')

# Blueprint (keeps existing @app.route usage)
app = Blueprint('admin', __name__)

# Injected by app factory
pipeline = None
auth_manager = None


def init_dependencies(*, pipeline_instance, auth_manager_instance):
    global pipeline, auth_manager
    pipeline = pipeline_instance
    auth_manager = auth_manager_instance

# Allowed file extensions
ALLOWED_EXTENSIONS = {'.pdf', '.docx', '.txt', '.md', '.markdown'}

def allowed_file(filename):
    return Path(filename).suffix.lower() in ALLOWED_EXTENSIONS


def log_admin_activity(activity_type: str, description: str, admin_id: int = None, metadata: dict = None):
    """Log admin activity for recent activity display"""
    try:
        from rag_chatbot.database import db
        import json
        
        conn = db.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO admin_activity (activity_type, description, admin_id, metadata)
            VALUES (?, ?, ?, ?)
        """, (activity_type, description, admin_id, json.dumps(metadata) if metadata else None))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Error logging admin activity: {e}")


# Authentication decorator
def require_auth(role=None):
    """Decorator to require authentication and optionally check role"""
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
            
            if not token:
                return jsonify({'success': False, 'error': 'Authentication required'}), 401
            
            # Validate session
            is_valid, user_info = auth_manager.validate_session(token)
            
            if not is_valid:
                return jsonify({'success': False, 'error': 'Invalid or expired session'}), 401
            
            # Check role if specified
            if role and user_info['role'] != role:
                return jsonify({'success': False, 'error': 'Insufficient permissions'}), 403
            
            # Add user info to request
            request.user = user_info
            
            return f(*args, **kwargs)
        return decorated_function
    return decorator


@app.route('/')
def index():
    """Serve the admin interface (requires authentication)"""
    # Check if user is authenticated
    token = request.cookies.get('session_token')
    if not token:
        return redirect('/login')
    
    is_valid, user_info = auth_manager.validate_session(token)
    if not is_valid:
        return redirect('/login')
    
    # Check if user is admin
    if user_info['role'] != 'admin':
        return redirect(_public_user_url())
    
    # Send response with no-cache headers to prevent back button issues
    response = send_from_directory(UI_DIR, 'admin_index.html')
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response



@app.route('/admin')
def admin_page():
    """Serve the admin interface (requires admin authentication)"""
    # Check if user is authenticated
    token = request.cookies.get('session_token')
    if not token:
        return redirect('/login')
    
    is_valid, user_info = auth_manager.validate_session(token)
    if not is_valid:
        return redirect('/login')
    
    # Check if user is admin
    if user_info['role'] != 'admin':
        return jsonify({'error': 'Admin access required'}), 403
    
    # Send response with no-cache headers to prevent back button issues
    response = send_from_directory(UI_DIR, 'admin_index.html')
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response


@app.route('/login')
def login_page():
    """Serve the login page"""
    # If already logged in, redirect to appropriate page based on current server
    token = request.cookies.get('session_token')
    if token:
        is_valid, user_info = auth_manager.validate_session(token)
        if is_valid:
            if user_info['role'] == 'admin':
                # Admin already logged in on admin web, show admin interface
                return redirect('/admin')
            else:
                # Regular user should go to user web
                return redirect(_public_user_url())
    
    return send_from_directory(UI_DIR, 'login.html')


@app.route('/signup')
def signup_page():
    """Serve the signup page"""
    return send_from_directory(UI_DIR, 'signup.html')


@app.route('/<path:filename>')
def serve_file(filename):
    """Serve static files (CSS, JS)"""
    return send_from_directory(UI_DIR, filename)


# ============================================================
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
        
        success, message, user_id = auth_manager.register_user(
            username=username,
            email=email,
            password=password,
            full_name=full_name,
            role='user'  # Default role is user
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
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


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
            # In proxy deployments (separate subdomains), keep admin logins on admin domain.
            if _env_truthy('BEHIND_PROXY') and (user_info or {}).get('role') != 'admin':
                user_login = _public_user_url().rstrip('/') + '/login'
                return jsonify({
                    'success': False,
                    'error': f"Please log in on the user site: {user_login}",
                }), 403

            response = jsonify({
                'success': True,
                'message': message,
                'session_token': session_token,
                'user': user_info,
                # Let the client redirect without hardcoding ports/scheme.
                'redirect_url': (
                    '/admin'
                    if (user_info or {}).get('role') == 'admin'
                    else _public_user_url()
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


@app.route('/api/auth/me', methods=['GET'])
@require_auth()
def get_current_user():
    """Get current user information"""
    return jsonify({
        'success': True,
        'user': request.user
    })


# ============================================================
# Document Management API Endpoints
# ============================================================

@app.route('/api/documents/folders', methods=['GET'])
def get_folders():
    """Get list of all folders for dropdown"""
    try:
        from rag_chatbot.database import db
        conn = db.get_connection()
        cursor = conn.cursor()
        
        # Get all active folders + document counts (for folder management table).
        # We count only company documents from the `documents` table (admin-managed).
        cursor.execute("""
            SELECT
                f.id,
                f.folder_name,
                f.folder_icon,
                f.display_order,
                COUNT(d.id) AS doc_count
            FROM document_folders f
            LEFT JOIN documents d
                ON d.folder = f.folder_name
                AND d.status = 'active'
            WHERE f.is_active = 1
            GROUP BY f.id, f.folder_name, f.folder_icon, f.display_order
            ORDER BY f.display_order
        """)
        
        folders = []
        for row in cursor.fetchall():
            folders.append({
                'id': row[0],
                'name': row[1],
                'icon': row[2],
                'order': row[3],
                'count': int(row[4] or 0),
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


@app.route('/api/documents/folders/delete', methods=['POST'])
def delete_folder():
    """Delete a folder (documents will be moved to default folder)"""
    try:
        from rag_chatbot.database import db
        
        data = request.get_json()
        if not data or 'folder_name' not in data:
            return jsonify({
                'success': False,
                'error': 'folder_name is required'
            }), 400
        
        folder_name = data['folder_name']
        
        # Prevent deleting the default folder
        if folder_name == 'Chung':
            return jsonify({
                'success': False,
                'error': 'Cannot delete the default folder'
            }), 400
        
        conn = db.get_connection()
        cursor = conn.cursor()
        
        # Check if folder exists
        cursor.execute("SELECT id FROM document_folders WHERE folder_name = ?", (folder_name,))
        folder = cursor.fetchone()
        if not folder:
            conn.close()
            return jsonify({
                'success': False,
                'error': 'Folder not found'
            }), 404
        
        # Check if folder has documents
        cursor.execute("SELECT COUNT(*) FROM documents WHERE folder = ?", (folder_name,))
        doc_count = cursor.fetchone()[0]
        
        if doc_count > 0:
            # Move documents to default folder instead of blocking
            cursor.execute("UPDATE documents SET folder = 'Chung' WHERE folder = ?", (folder_name,))
            print(f"Moved {doc_count} documents from '{folder_name}' to 'Chung'")
        
        # Delete the folder
        cursor.execute("DELETE FROM document_folders WHERE folder_name = ?", (folder_name,))
        
        # Log the activity
        log_admin_activity('folder_deleted', f'Folder "{folder_name}" deleted, {doc_count} documents moved to Chung')
        
        conn.commit()
        conn.close()
        
        return jsonify({
            'success': True,
            'message': f'Folder "{folder_name}" deleted successfully',
            'documents_moved': doc_count
        })
    except Exception as e:
        print(f"Error deleting folder: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/documents/folders/rename', methods=['POST'])
def rename_folder():
    """Rename a folder"""
    try:
        from rag_chatbot.database import db
        
        data = request.get_json()
        if not data or 'old_name' not in data or 'new_name' not in data:
            return jsonify({
                'success': False,
                'error': 'old_name and new_name are required'
            }), 400
        
        old_name = data['old_name'].strip()
        new_name = data['new_name'].strip()
        
        if not new_name:
            return jsonify({
                'success': False,
                'error': 'New folder name cannot be empty'
            }), 400
        
        # Prevent renaming the default folder
        if old_name == 'Chung':
            return jsonify({
                'success': False,
                'error': 'Cannot rename the default folder'
            }), 400
        
        conn = db.get_connection()
        cursor = conn.cursor()
        
        # Check if old folder exists
        cursor.execute("SELECT id FROM document_folders WHERE folder_name = ?", (old_name,))
        folder = cursor.fetchone()
        if not folder:
            conn.close()
            return jsonify({
                'success': False,
                'error': 'Folder not found'
            }), 404
        
        # Check if new name already exists
        cursor.execute("SELECT id FROM document_folders WHERE folder_name = ?", (new_name,))
        existing = cursor.fetchone()
        if existing:
            conn.close()
            return jsonify({
                'success': False,
                'error': f'A folder named "{new_name}" already exists'
            }), 400
        
        # Rename the folder
        cursor.execute("UPDATE document_folders SET folder_name = ? WHERE folder_name = ?", (new_name, old_name))
        
        # Update documents in this folder
        cursor.execute("UPDATE documents SET folder = ? WHERE folder = ?", (new_name, old_name))
        updated_docs = cursor.rowcount
        
        # Log the activity
        log_admin_activity('folder_renamed', f'Folder "{old_name}" renamed to "{new_name}" ({updated_docs} documents updated)')
        
        conn.commit()
        conn.close()
        
        return jsonify({
            'success': True,
            'message': f'Folder renamed to "{new_name}"',
            'documents_updated': updated_docs
        })
    except Exception as e:
        print(f"Error renaming folder: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/documents', methods=['GET'])
def get_documents():
    """Get list of all documents"""
    try:
        folder = (request.args.get('folder') or '').strip()

        # Fast path: no folder filter.
        if not folder:
            docs = document_manager.get_all_documents()
            return jsonify(docs)

        # Folder filter: query directly to avoid loading everything into memory.
        from rag_chatbot.database import db
        import sqlite3

        conn = db.get_connection()
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT * FROM documents
            WHERE status = 'active' AND folder = ?
            ORDER BY upload_date DESC
            """,
            (folder,),
        )
        docs = [dict(row) for row in cursor.fetchall()]
        conn.close()

        return jsonify(docs)
    except Exception as e:
        return jsonify({
            'error': str(e)
        }), 500


@app.route('/api/upload', methods=['POST'])
def upload_documents():
    """Upload and process multiple documents"""
    try:
        if 'files' not in request.files:
            return jsonify({
                'success': False,
                'error': 'No files provided'
            }), 400
        
        files = request.files.getlist('files')
        descriptions = request.form.getlist('descriptions')
        folder = request.form.get('folder', 'Chung')  # Get folder from form

        if not descriptions or len(descriptions) != len(files):
            return jsonify({
                'success': False,
                'error': 'Each uploaded file must include a description'
            }), 400

        for desc in descriptions:
            if not isinstance(desc, str) or not desc.strip():
                return jsonify({
                    'success': False,
                    'error': 'Each uploaded file must include a non-empty description'
                }), 400
        
        # Ensure folder exists in database
        from rag_chatbot.database import ensure_folder_exists
        ensure_folder_exists(folder)
        
        if not files:
            return jsonify({
                'success': False,
                'error': 'No files selected'
            }), 400
        
        uploaded_count = 0
        uploaded_files = []
        skipped_files = []
        files_to_upload = []
        
        # Get all existing documents from database
        existing_docs = document_manager.get_all_documents()
        existing_filenames = [doc['filename'] for doc in existing_docs]
        
        # First pass: identify files to upload
        for file, desc in zip(files, descriptions):
            if file and file.filename and allowed_file(file.filename):
                original_filename = secure_filename(file.filename)
                
                # Check if file exists in database
                if original_filename in existing_filenames:
                    skipped_files.append(original_filename)
                    print(f"Skipping {original_filename} - already in database")
                    continue
                
                # Mark this file for upload (including orphaned files - we'll overwrite them)
                files_to_upload.append((file, desc.strip(), original_filename))
                
                # If file exists on disk but not in database, it's orphaned - we'll overwrite it
                file_path = os.path.join(DATA_DIR, original_filename)
                if os.path.exists(file_path):
                    print(f"Found orphaned file: {original_filename} - will overwrite")
        
        # Second pass: actually upload the files
        for file, description, original_filename in files_to_upload:
            filename = original_filename
            file_path = os.path.join(DATA_DIR, filename)
            
            try:
                # Check if file exists (orphaned file)
                is_orphaned = os.path.exists(file_path)
                
                if is_orphaned:
                    # For orphaned files, save to temp location first
                    import uuid
                    temp_filename = f"{uuid.uuid4().hex}_{filename}"
                    temp_path = os.path.join(DATA_DIR, temp_filename)
                    
                    file.save(temp_path)
                    print(f"Saved to temp: {temp_filename}")
                    
                    # Try to replace the orphaned file
                    try:
                        # On Windows, need to remove first if file is locked
                        if os.path.exists(file_path):
                            os.remove(file_path)
                        os.rename(temp_path, file_path)
                        print(f"Replaced orphaned file: {filename}")
                    except Exception as replace_error:
                        # If replace fails, just use the temp file
                        print(f"Could not replace orphaned file, using new name: {replace_error}")
                        file_path = temp_path
                        filename = temp_filename
                else:
                    # Normal save for new files
                    file.save(file_path)
                    print(f"Saved file: {filename}")
                
                # Get file info
                file_size = os.path.getsize(file_path)
                file_type = Path(filename).suffix.lower()
                metadata = json.dumps({'description': description}, ensure_ascii=False)
                
                # Add to database with folder
                from rag_chatbot.database import db
                conn = db.get_connection()
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO documents 
                    (filename, original_filename, file_type, file_size, uploaded_by, folder, metadata)
                    VALUES (?, ?, ?, ?, 'admin', ?, ?)
                """, (filename, original_filename, file_type, file_size, folder, metadata))
                conn.commit()
                conn.close()
                
                uploaded_files.append(file_path)
                uploaded_count += 1
                print(f"Successfully uploaded: {filename}")
                
            except Exception as e:
                print(f"Error uploading {filename}: {e}")
                skipped_files.append(filename)
                continue
        
        if uploaded_count > 0:
            # Log the upload activity
            log_admin_activity('document_uploaded', f'Uploaded {uploaded_count} document(s) to folder "{folder}"')
            
            # Process documents with RAG pipeline
            try:
                pipeline.store_nodes(input_files=uploaded_files)
                pipeline.set_chat_mode()
                
                message = f'Successfully uploaded and processed {uploaded_count} document(s)'
                if skipped_files:
                    message += f'. Skipped {len(skipped_files)} duplicate(s): {", ".join(skipped_files)}'
                
                return jsonify({
                    'success': True,
                    'uploaded': uploaded_count,
                    'skipped': len(skipped_files),
                    'message': message
                })
            except Exception as e:
                return jsonify({
                    'success': True,
                    'uploaded': uploaded_count,
                    'warning': f'Uploaded but processing failed: {str(e)}'
                })
        else:
            message = 'No new files uploaded'
            if skipped_files:
                message += f'. All {len(skipped_files)} file(s) already exist: {", ".join(skipped_files)}'
            
            return jsonify({
                'success': False,
                'error': message
            }), 400
            
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/documents/<int:doc_id>/rename', methods=['POST'])
def rename_document(doc_id):
    """Rename a document"""
    try:
        from rag_chatbot.database import db
        
        data = request.get_json()
        new_name = data.get('new_name', '').strip()
        
        if not new_name:
            return jsonify({
                'success': False,
                'error': 'New name is required'
            }), 400
        
        # Get document info
        doc = document_manager.get_document(doc_id)
        if not doc:
            return jsonify({
                'success': False,
                'error': 'Document not found'
            }), 404
        
        old_name = doc.get('original_filename', doc.get('filename', ''))
        
        # Update in database
        conn = db.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE documents SET original_filename = ? WHERE id = ?
        """, (new_name, doc_id))
        conn.commit()
        conn.close()
        
        # Log the activity
        log_admin_activity('document_renamed', f'Document renamed: {old_name} → {new_name}')
        
        return jsonify({
            'success': True,
            'message': f'Document renamed to {new_name}'
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/documents/<int:doc_id>', methods=['DELETE'])
def delete_document(doc_id):
    """Delete a document"""
    try:
        # Get document info
        doc = document_manager.get_document(doc_id)
        if not doc:
            return jsonify({
                'success': False,
                'error': 'Document not found'
            }), 404
        
        # Delete from database first
        success = document_manager.delete_document(doc_id)
        if not success:
            return jsonify({
                'success': False,
                'error': 'Failed to delete from database'
            }), 500
        
        # Reset the pipeline to release file handles
        pipeline.reset_documents()
        pipeline.reset_conversation()
        
        # Now we can safely delete the physical file
        file_path = os.path.join(DATA_DIR, doc['filename'])
        try:
            if os.path.exists(file_path):
                os.remove(file_path)
        except Exception as file_error:
            print(f"Warning: Could not delete physical file: {file_error}")
            # Continue anyway - database entry is already deleted
        
        # Rebuild RAG index with remaining documents
        remaining_docs = document_manager.get_all_documents()
        if remaining_docs:
            doc_paths = [os.path.join(DATA_DIR, d['filename']) for d in remaining_docs]
            pipeline.store_nodes(input_files=doc_paths)
            pipeline.set_chat_mode()
        
        # Log the deletion activity
        log_admin_activity('document_deleted', f'Document deleted: {doc["filename"]}')
        
        return jsonify({
            'success': True,
            'message': f'Document {doc["filename"]} deleted successfully'
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/reports', methods=['GET'])
def get_reports():
    """Get list of user reports"""
    try:
        status = request.args.get('status', 'all')
        
        if status == 'all':
            reports = report_manager.get_all_reports()
        else:
            reports = report_manager.get_all_reports(status=status.lower())
        
        return jsonify({
            'success': True,
            'reports': reports
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/reports/<int:report_id>', methods=['GET'])
def get_report(report_id):
    """Get details of a specific report"""
    try:
        report = report_manager.get_report(report_id)
        if not report:
            return jsonify({
                'success': False,
                'error': 'Report not found'
            }), 404
        
        return jsonify({
            'success': True,
            'report': report
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/reports/<int:report_id>/resolve', methods=['POST'])
def resolve_report(report_id):
    """
    Mark a report as resolved
    
    When users report incorrect/incomplete AI responses, admins can take these actions:
    1. Upload better documents: Add more comprehensive or updated documents
    2. Check document quality: Review if existing documents contain correct information
    3. Update/delete outdated docs: Remove or replace documents with incorrect info
    4. Re-index documents: Delete and re-upload documents if processed incorrectly
    5. Improve document format: Convert image-only PDFs to text-searchable format
    
    The resolution_notes field tracks what action was taken to fix the issue.
    """
    try:
        data = request.json
        resolution_notes = data.get('resolution_notes', '')
        
        success = report_manager.resolve_report(
            report_id=report_id,
            resolved_by='admin',
            resolution_notes=resolution_notes
        )
        
        if success:
            # Log the resolution
            log_admin_activity('report_resolved', f'Report #{report_id} resolved: {resolution_notes[:50]}...' if len(resolution_notes) > 50 else f'Report #{report_id} resolved: {resolution_notes}')
            
            return jsonify({
                'success': True,
                'message': f'Report #{report_id} resolved successfully'
            })
        else:
            return jsonify({
                'success': False,
                'error': 'Failed to resolve report'
            }), 500
            
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/stats', methods=['GET'])
def get_stats():
    """Get system statistics"""
    try:
        docs = document_manager.get_all_documents()
        
        # Calculate total storage, tolerating missing historical values
        def _coerce_size(value):
            try:
                return int(value or 0)
            except (TypeError, ValueError):
                return 0

        total_storage = sum(_coerce_size(doc.get('file_size')) for doc in docs)
        
        # Get last upload date
        last_upload = docs[0].get('upload_date') if docs else None
        
        # Get report statistics
        all_reports = report_manager.get_all_reports()
        pending_reports = report_manager.get_all_reports(status='pending')
        resolved_reports = report_manager.get_all_reports(status='resolved')
        
        return jsonify({
            'success': True,
            'stats': {
                'total_documents': len(docs),
                'total_storage': total_storage,
                'last_upload': last_upload,
                'total_reports': len(all_reports),
                'pending_reports': len(pending_reports),
                'resolved_reports': len(resolved_reports)
            }
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500




@app.route('/api/activity/recent', methods=['GET'])
def get_recent_activity():
    """Get recent system activity for admin dashboard"""
    try:
        from rag_chatbot.database import db
        import json
        
        conn = db.get_connection()
        cursor = conn.cursor()
        
        activities = []
        
        # Get recent admin activities from activity log
        try:
            cursor.execute("""
                SELECT activity_type, description, created_at, metadata
                FROM admin_activity
                ORDER BY created_at DESC
                LIMIT 10
            """)
            for row in cursor.fetchall():
                activities.append({
                    'type': row[0],
                    'description': row[1],
                    'timestamp': row[2],
                    'metadata': json.loads(row[3]) if row[3] else None,
                    'icon': get_activity_icon(row[0])
                })
        except Exception as e:
            print(f"Error getting admin activities: {e}")
        
        # Get recent document uploads
        try:
            cursor.execute("""
                SELECT 'document_uploaded' as type, 
                       'Document uploaded: ' || original_filename as description,
                       upload_date as timestamp
                FROM documents
                ORDER BY upload_date DESC
                LIMIT 5
            """)
            for row in cursor.fetchall():
                activities.append({
                    'type': row[0],
                    'description': row[1],
                    'timestamp': row[2],
                    'icon': 'fa-file-upload'
                })
        except Exception as e:
            print(f"Error getting document uploads: {e}")
        
        # Get recent reports
        try:
            cursor.execute("""
                SELECT 'report_submitted' as type,
                       'Report submitted: ' || COALESCE(report_type, 'general') as description,
                       report_date as timestamp,
                       status
                FROM user_reports
                ORDER BY report_date DESC
                LIMIT 5
            """)
            for row in cursor.fetchall():
                activities.append({
                    'type': row[0],
                    'description': row[1],
                    'timestamp': row[2],
                    'icon': 'fa-flag' if row[3] == 'pending' else 'fa-check-circle'
                })
        except Exception as e:
            print(f"Error getting reports: {e}")
        
        # Get recent news fetches
        try:
            cursor.execute("""
                SELECT 'news_fetched' as type,
                       'News article fetched: ' || SUBSTR(title, 1, 50) || '...' as description,
                       created_at as timestamp
                FROM technical_articles
                ORDER BY created_at DESC
                LIMIT 5
            """)
            for row in cursor.fetchall():
                activities.append({
                    'type': row[0],
                    'description': row[1],
                    'timestamp': row[2],
                    'icon': 'fa-newspaper'
                })
        except Exception as e:
            print(f"Error getting news fetches: {e}")
        
        conn.close()
        
        # Sort all activities by timestamp and take the most recent 15
        activities.sort(key=lambda x: x.get('timestamp') or '', reverse=True)
        activities = activities[:15]
        
        return jsonify({
            'success': True,
            'activities': activities
        })
    except Exception as e:
        print(f"Error getting recent activity: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


def get_activity_icon(activity_type: str) -> str:
    """Get Font Awesome icon for activity type"""
    icons = {
        'document_uploaded': 'fa-file-upload',
        'document_deleted': 'fa-file-times',
        'folder_created': 'fa-folder-plus',
        'folder_deleted': 'fa-folder-minus',
        'folder_renamed': 'fa-edit',
        'report_resolved': 'fa-check-circle',
        'report_submitted': 'fa-flag',
        'news_fetched': 'fa-newspaper',
        'news_refresh': 'fa-sync',
        'user_login': 'fa-sign-in-alt',
        'settings_changed': 'fa-cog'
    }
    return icons.get(activity_type, 'fa-info-circle')


@app.route('/api/news/init-sources', methods=['POST'])
@require_auth(role='admin')
def initialize_news_sources():
    """Initialize default news sources"""
    try:
        from rag_chatbot.workers.news_fetcher import init_default_sources
        
        init_default_sources()
        
        return jsonify({
            'success': True,
            'message': 'Default news sources initialized'
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/news/fetch-all', methods=['POST'])
@require_auth(role='admin')
def fetch_all_news():
    """Fetch news for all roles"""
    try:
        from rag_chatbot.workers.news_fetcher import NewsFetcher
        
        fetcher = NewsFetcher(pipeline)
        results = fetcher.fetch_all_roles(fetch_content=True)
        
        # Embed new articles
        for role_type, count in results.items():
            if count > 0:
                fetcher.embed_articles(role_type, limit=count)
        
        return jsonify({
            'success': True,
            'message': 'News fetched for all roles',
            'results': results
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


# ============================================
# Configuration API Endpoints
# ============================================

def read_env_file():
    """Read the .env file and return as dictionary"""
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env')
    config = {}
    if os.path.exists(env_path):
        with open(env_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    config[key.strip()] = value.strip()
    return config


def write_env_file(config):
    """Write configuration back to .env file, preserving comments"""
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env')
    
    # Read existing file to preserve comments and structure
    lines = []
    if os.path.exists(env_path):
        with open(env_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
    
    # Update values in existing lines
    updated_keys = set()
    new_lines = []
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith('#') and '=' in stripped:
            key = stripped.split('=', 1)[0].strip()
            if key in config:
                new_lines.append(f"{key}={config[key]}\n")
                updated_keys.add(key)
            else:
                new_lines.append(line)
        else:
            new_lines.append(line)
    
    # Add any new keys that weren't in the file
    for key, value in config.items():
        if key not in updated_keys:
            new_lines.append(f"{key}={value}\n")
    
    # Write back
    with open(env_path, 'w', encoding='utf-8') as f:
        f.writelines(new_lines)


@app.route('/api/config', methods=['GET'])
@require_auth(role='admin')
def get_configuration():
    """Get current system configuration"""
    try:
        config = read_env_file()
        
        # Mask sensitive values for display
        masked_config = config.copy()
        sensitive_keys = ['LLM_TOKEN', 'GEMINI_API_KEY', 'OPENROUTER_API_KEY', 'SECRET_KEY', 'ADMIN_PASSWORD']
        for key in sensitive_keys:
            if key in masked_config and masked_config[key]:
                # Show first 4 and last 4 characters
                val = masked_config[key]
                if len(val) > 10:
                    masked_config[key + '_MASKED'] = val[:4] + '...' + val[-4:]
                else:
                    masked_config[key + '_MASKED'] = '***'
        
        # Determine current provider
        use_gemini = config.get('USE_GEMINI', 'false').lower() in ('true', '1', 'yes')
        llm_provider = config.get('LLM_PROVIDER', 'github')
        
        current_provider = 'gemini' if use_gemini else llm_provider
        
        return jsonify({
            'success': True,
            'config': masked_config,
            'raw_config': config,  # Full values for form fields
            'current_provider': current_provider
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/config', methods=['POST'])
@require_auth(role='admin')
def save_configuration():
    """Save system configuration"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'error': 'No data provided'}), 400
        
        # Read current config
        current_config = read_env_file()
        
        # Update with new values (only update provided keys)
        for key, value in data.items():
            if value is not None and value != '':
                current_config[key] = str(value)
        
        # Write updated config
        write_env_file(current_config)
        
        # Also update os.environ for immediate effect (limited)
        for key, value in data.items():
            if value is not None:
                os.environ[key] = str(value)
        
        return jsonify({
            'success': True,
            'message': 'Configuration saved successfully. Server restart required for full effect.'
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/config/restart', methods=['POST'])
@require_auth(role='admin')
def restart_server():
    """Trigger server restart (graceful shutdown, requires external restart)"""
    try:
        import threading
        import time
        import requests
        token = os.environ.get('INTERNAL_SERVICE_TOKEN', '').strip()
        headers = {'Authorization': f'Bearer {token}'} if token else None
        
        def delayed_shutdown():
            # First, trigger user server restart
            try:
                requests.post('http://knowledge-user:7861/api/internal/restart', timeout=2, headers=headers)
            except:
                # Try localhost for non-Docker environments
                try:
                    requests.post('http://localhost:7861/api/internal/restart', timeout=2, headers=headers)
                except:
                    pass
            
            time.sleep(1)
            os._exit(0)  # Force exit, supervisor/systemd will restart
        
        threading.Thread(target=delayed_shutdown, daemon=True).start()
        
        return jsonify({
            'success': True,
            'message': 'Servers are restarting... Please refresh in a few seconds.'
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/admin/doc-improve', methods=['POST'])
@require_auth(role='admin')
def admin_doc_improve():
    """Admin helper: run Document Improvement Agent (MCP-backed) for a chosen document.

    Request JSON:
      - document_ref: "company#1" | "personal#9" (preferred)
        OR document_type + document_id
      - goal: optional (default: policy)
      - top_k: optional int (default: 3)

    Proxies to user-web internal endpoint: /api/internal/agent/doc-improve
    """
    try:
        data = request.get_json(silent=True) or {}

        document_type = (data.get('document_type') or '').strip().lower()
        document_id = data.get('document_id')
        document_ref = (data.get('document_ref') or '').strip()

        if document_ref and (not document_type or document_id is None):
            parsed = _parse_document_ref(document_ref)
            if not parsed:
                return jsonify({
                    'success': False,
                    'error': "Invalid document_ref. Use 'company#<id>' or 'personal#<id>' (e.g. personal#9)."
                }), 400
            document_type, document_id = parsed

        if document_type not in {'company', 'personal'}:
            return jsonify({'success': False, 'error': "document_type must be 'company' or 'personal'"}), 400
        if document_id is None:
            return jsonify({'success': False, 'error': 'Missing document_id'}), 400

        goal = (data.get('goal') or 'policy').strip() or 'policy'
        top_k = int(data.get('top_k') or 3)

        token = os.environ.get('INTERNAL_SERVICE_TOKEN', '').strip()
        if not token:
            return jsonify({'success': False, 'error': 'INTERNAL_SERVICE_TOKEN not configured'}), 503

        import requests

        base = _user_internal_api_base().rstrip('/')
        url = base + '/api/internal/agent/doc-improve'
        headers = {
            'Authorization': f'Bearer {token}',
            'Content-Type': 'application/json',
        }
        payload = {
            'document_type': document_type,
            'document_id': int(document_id),
            'goal': goal,
            'top_k': int(top_k),
        }

        resp = requests.post(url, json=payload, headers=headers, timeout=(5, 300))

        try:
            out = resp.json()
        except Exception:
            out = {'success': False, 'error': resp.text or 'Invalid response from user-web'}

        if resp.status_code >= 400:
            return jsonify(out), resp.status_code

        return jsonify(out)
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/config/test-llm', methods=['POST'])
@require_auth(role='admin')
def test_llm_connection():
    """Test LLM connection with current configuration"""
    try:
        data = request.get_json() or {}
        provider = data.get('provider', os.environ.get('LLM_PROVIDER', 'github'))
        
        if provider == 'github':
            from azure.ai.inference import ChatCompletionsClient
            from azure.ai.inference.models import UserMessage
            from azure.core.credentials import AzureKeyCredential
            
            token = data.get('token') or os.environ.get('LLM_TOKEN')
            endpoint = data.get('endpoint') or os.environ.get('LLM_ENDPOINT', 'https://models.github.ai/inference')
            model = data.get('model') or os.environ.get('LLM_MODEL', 'openai/gpt-4.1')
            
            client = ChatCompletionsClient(
                endpoint=endpoint,
                credential=AzureKeyCredential(token),
            )
            
            response = client.complete(
                messages=[UserMessage("Say 'Hello' in one word.")],
                max_tokens=10,
                model=model
            )
            
            return jsonify({
                'success': True,
                'message': f'GitHub Models connection successful! Model: {model}',
                'response': response.choices[0].message.content
            })
            
        elif provider == 'gemini':
            try:
                import google.generativeai as genai
            except ImportError:
                return jsonify({
                    'success': False,
                    'error': 'google-generativeai package not installed. Run: pip install google-generativeai'
                }), 400
            
            api_key = data.get('api_key') or os.environ.get('GEMINI_API_KEY')
            model_name = data.get('model') or os.environ.get('GEMINI_MODEL', 'gemini-2.5-flash')
            
            genai.configure(api_key=api_key)
            model = genai.GenerativeModel(model_name)
            response = model.generate_content("Say 'Hello' in one word.")
            
            return jsonify({
                'success': True,
                'message': f'Gemini connection successful! Model: {model_name}',
                'response': response.text
            })
            
        else:
            return jsonify({
                'success': False,
                'error': f'Provider "{provider}" test not implemented'
            }), 400
            
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/documents/<int:doc_id>/admin-pin', methods=['POST'])
@require_auth(role='admin')
def admin_pin_document(doc_id):
    """Pin a document by admin - all users will see it as pinned"""
    try:
        from rag_chatbot.database import db
        
        conn = db.get_connection()
        cursor = conn.cursor()
        
        cursor.execute("UPDATE documents SET admin_pinned = 1 WHERE id = ?", (doc_id,))
        conn.commit()
        conn.close()
        
        log_admin_activity('pin_document', f'Admin pinned document ID {doc_id}', request.user.get('id'))
        
        return jsonify({'success': True, 'message': 'Document pinned by admin'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/documents/<int:doc_id>/admin-unpin', methods=['POST'])
@require_auth(role='admin')
def admin_unpin_document(doc_id):
    """Unpin a document by admin"""
    try:
        from rag_chatbot.database import db
        
        conn = db.get_connection()
        cursor = conn.cursor()
        
        cursor.execute("UPDATE documents SET admin_pinned = 0 WHERE id = ?", (doc_id,))
        conn.commit()
        conn.close()
        
        log_admin_activity('unpin_document', f'Admin unpinned document ID {doc_id}', request.user.get('id'))
        
        return jsonify({'success': True, 'message': 'Document unpinned by admin'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


