"""
Authentication and User Management Module
Handles user registration, login, and session management
"""

import os
import sqlite3
import hashlib
import secrets
from datetime import datetime, timedelta
from typing import Optional, Dict, Tuple
from pathlib import Path

from werkzeug.security import check_password_hash, generate_password_hash


class AuthManager:
    """Manages user authentication and sessions"""
    
    def __init__(self, db_path: str):
        """Initialize authentication manager"""
        self.db_path = db_path
        self.session_duration = timedelta(hours=24)  # Sessions valid for 24 hours
        # Basic brute-force protection (DB-backed, shared across processes).
        self.max_failed_logins = int(os.environ.get('AUTH_MAX_FAILED_LOGINS', '8'))
        self.lockout_minutes = int(os.environ.get('AUTH_LOCKOUT_MINUTES', '15'))
        self.window_minutes = int(os.environ.get('AUTH_WINDOW_MINUTES', '15'))
        self._init_database()
    
    def _init_database(self):
        """Initialize authentication tables"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Users table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                email TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                full_name TEXT,
                role TEXT NOT NULL DEFAULT 'user',
                is_active INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_login TIMESTAMP
            )
        """)
        
        # Sessions table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                session_token TEXT UNIQUE NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                expires_at TIMESTAMP NOT NULL,
                ip_address TEXT,
                user_agent TEXT,
                FOREIGN KEY (user_id) REFERENCES users (id)
            )
        """)

        # Login attempts table (for basic rate limiting / lockout)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS login_attempts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT,
                ip_address TEXT,
                attempted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                success INTEGER DEFAULT 0
            )
        """)
        
        # Create default admin user if not exists
        cursor.execute("SELECT COUNT(*) FROM users WHERE role = 'admin'")
        if cursor.fetchone()[0] == 0:
            default_password = os.environ.get('ADMIN_DEFAULT_PASSWORD', 'admin123')
            admin_password = self._hash_password(default_password)
            cursor.execute("""
                INSERT INTO users (username, email, password_hash, full_name, role)
                VALUES (?, ?, ?, ?, ?)
            """, ("admin", "admin@system.local", admin_password, "System Administrator", "admin"))
            print("✓ Default admin user created (username: admin)")
            if default_password == 'admin123':
                print("  Default password: admin123")
            else:
                print("  Default password set via ADMIN_DEFAULT_PASSWORD")
            print("⚠️  Please change the admin password after first login!")
        
        conn.commit()
        conn.close()
    
    def _hash_password(self, password: str) -> str:
        """Hash password using a modern adaptive hash (Werkzeug/PBKDF2)."""
        return generate_password_hash(password, method='pbkdf2:sha256', salt_length=16)

    def _is_legacy_sha256(self, stored_hash: str) -> bool:
        if not stored_hash:
            return False
        # Legacy format was raw sha256 hex.
        return len(stored_hash) == 64 and all(ch in '0123456789abcdef' for ch in stored_hash.lower())

    def _verify_password(self, stored_hash: str, password: str) -> Tuple[bool, bool]:
        """Return (is_valid, should_upgrade_hash)."""
        if not stored_hash:
            return False, False

        if self._is_legacy_sha256(stored_hash):
            candidate = hashlib.sha256(password.encode()).hexdigest()
            return candidate == stored_hash, True

        try:
            return check_password_hash(stored_hash, password), False
        except Exception:
            return False, False

    def _record_login_attempt(self, username: str, ip_address: Optional[str], success: bool):
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO login_attempts (username, ip_address, success) VALUES (?, ?, ?)",
                (username, ip_address, 1 if success else 0),
            )
            conn.commit()
            conn.close()
        except Exception:
            # Don't block auth on audit failures.
            pass

    def _is_locked_out(self, username: str, ip_address: Optional[str]) -> bool:
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT COUNT(*)
                FROM login_attempts
                WHERE success = 0
                  AND attempted_at >= datetime('now', ?)
                  AND (username = ? OR ip_address = ?)
                """,
                (f'-{self.window_minutes} minutes', username, ip_address or ''),
            )
            failures = cursor.fetchone()[0] or 0

            if failures < self.max_failed_logins:
                conn.close()
                return False

            # If too many failures, lock out for lockout_minutes since last failed attempt.
            cursor.execute(
                """
                SELECT attempted_at
                FROM login_attempts
                WHERE success = 0
                  AND (username = ? OR ip_address = ?)
                ORDER BY attempted_at DESC
                LIMIT 1
                """,
                (username, ip_address or ''),
            )
            row = cursor.fetchone()
            conn.close()
            if not row:
                return False
            last_failed = row[0]
            # SQLite returns 'YYYY-MM-DD HH:MM:SS' -> fromisoformat works.
            last_failed_dt = datetime.fromisoformat(last_failed)
            return datetime.now() < (last_failed_dt + timedelta(minutes=self.lockout_minutes))
        except Exception:
            return False
    
    def _generate_session_token(self) -> str:
        """Generate a secure random session token"""
        return secrets.token_urlsafe(32)
    
    def register_user(
        self,
        username: str,
        email: str,
        password: str,
        full_name: Optional[str] = None,
        role: str = "user",
        technical_role: Optional[str] = None
    ) -> Tuple[bool, str, Optional[int]]:
        """
        Register a new user
        Returns: (success, message, user_id)
        """
        try:
            # Validate input
            if not username or len(username) < 3:
                return False, "Username must be at least 3 characters long", None
            
            if not email or "@" not in email:
                return False, "Invalid email address", None
            
            if not password or len(password) < 6:
                return False, "Password must be at least 6 characters long", None
            
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # Check if username or email already exists
            cursor.execute(
                "SELECT username, email FROM users WHERE username = ? OR email = ?",
                (username, email)
            )
            existing = cursor.fetchone()
            
            if existing:
                conn.close()
                if existing[0] == username:
                    return False, "Username already exists", None
                else:
                    return False, "Email already registered", None
            
            # Hash password and create user
            password_hash = self._hash_password(password)
            cursor.execute("""
                INSERT INTO users (username, email, password_hash, full_name, role)
                VALUES (?, ?, ?, ?, ?)
            """, (username, email, password_hash, full_name, role))
            
            user_id = cursor.lastrowid
            conn.commit()
            conn.close()
            
            # Set technical role if provided
            if technical_role:
                from rag_chatbot.database import user_role_manager
                user_role_manager.set_user_role(user_id, technical_role)
            
            return True, "User registered successfully", user_id
            
        except Exception as e:
            return False, f"Registration failed: {str(e)}", None
    
    def login(
        self,
        username: str,
        password: str,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None
    ) -> Tuple[bool, str, Optional[str], Optional[Dict]]:
        """
        Authenticate user and create session
        Returns: (success, message, session_token, user_info)
        """
        try:
            if self._is_locked_out(username, ip_address):
                return False, "Too many failed login attempts. Please try again later.", None, None

            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            # Get user by username or email
            cursor.execute("""
                SELECT * FROM users 
                WHERE (username = ? OR email = ?) AND is_active = 1
            """, (username, username))
            
            user = cursor.fetchone()
            
            if not user:
                conn.close()
                self._record_login_attempt(username, ip_address, success=False)
                return False, "Invalid username or password", None, None
            
            # Verify password
            is_valid, should_upgrade = self._verify_password(user['password_hash'], password)
            if not is_valid:
                conn.close()
                self._record_login_attempt(username, ip_address, success=False)
                return False, "Invalid username or password", None, None

            # Opportunistically upgrade legacy hashes
            if should_upgrade:
                try:
                    new_hash = self._hash_password(password)
                    cursor.execute(
                        "UPDATE users SET password_hash = ? WHERE id = ?",
                        (new_hash, user['id']),
                    )
                except Exception:
                    pass
            
            # Create session
            session_token = self._generate_session_token()
            expires_at = datetime.now() + self.session_duration
            
            cursor.execute("""
                INSERT INTO sessions (user_id, session_token, expires_at, ip_address, user_agent)
                VALUES (?, ?, ?, ?, ?)
            """, (user['id'], session_token, expires_at, ip_address, user_agent))
            
            # Update last login
            cursor.execute("""
                UPDATE users SET last_login = CURRENT_TIMESTAMP WHERE id = ?
            """, (user['id'],))
            
            conn.commit()
            conn.close()

            self._record_login_attempt(username, ip_address, success=True)
            
            user_info = {
                'id': user['id'],
                'username': user['username'],
                'email': user['email'],
                'full_name': user['full_name'],
                'role': user['role']
            }
            
            return True, "Login successful", session_token, user_info
            
        except Exception as e:
            return False, f"Login failed: {str(e)}", None, None
    
    def validate_session(self, session_token: str) -> Tuple[bool, Optional[Dict]]:
        """
        Validate session token and return user info
        Returns: (is_valid, user_info)
        """
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT u.*, s.expires_at
                FROM sessions s
                JOIN users u ON s.user_id = u.id
                WHERE s.session_token = ? AND u.is_active = 1
            """, (session_token,))
            
            result = cursor.fetchone()
            conn.close()
            
            if not result:
                return False, None
            
            # Check if session expired
            expires_at = datetime.fromisoformat(result['expires_at'])
            if datetime.now() > expires_at:
                self.logout(session_token)
                return False, None
            
            user_info = {
                'id': result['id'],
                'username': result['username'],
                'email': result['email'],
                'full_name': result['full_name'],
                'role': result['role']
            }
            
            return True, user_info
            
        except Exception as e:
            print(f"Session validation error: {e}")
            return False, None
    
    def logout(self, session_token: str) -> bool:
        """Delete session (logout user)"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute("DELETE FROM sessions WHERE session_token = ?", (session_token,))
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            print(f"Logout error: {e}")
            return False
    
    def cleanup_expired_sessions(self):
        """Remove expired sessions from database"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute("DELETE FROM sessions WHERE expires_at < CURRENT_TIMESTAMP")
            deleted = cursor.rowcount
            conn.commit()
            conn.close()
            return deleted
        except Exception as e:
            print(f"Session cleanup error: {e}")
            return 0
    
    def change_password(self, user_id: int, old_password: str, new_password: str) -> Tuple[bool, str]:
        """Change user password"""
        try:
            if len(new_password) < 6:
                return False, "New password must be at least 6 characters long"
            
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # Verify old password
            cursor.execute("SELECT password_hash FROM users WHERE id = ?", (user_id,))
            result = cursor.fetchone()
            
            if not result:
                conn.close()
                return False, "User not found"
            
            old_hash = self._hash_password(old_password)
            if old_hash != result[0]:
                conn.close()
                return False, "Current password is incorrect"
            
            # Update password
            new_hash = self._hash_password(new_password)
            cursor.execute("UPDATE users SET password_hash = ? WHERE id = ?", (new_hash, user_id))
            conn.commit()
            conn.close()
            
            return True, "Password changed successfully"
            
        except Exception as e:
            return False, f"Password change failed: {str(e)}"
    
    def get_user_info(self, user_id: int) -> Optional[Dict]:
        """Get user information by ID"""
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))
            user = cursor.fetchone()
            conn.close()
            
            if user:
                return {
                    'id': user['id'],
                    'username': user['username'],
                    'email': user['email'],
                    'full_name': user['full_name'],
                    'role': user['role'],
                    'created_at': user['created_at'],
                    'last_login': user['last_login']
                }
            return None
            
        except Exception as e:
            print(f"Get user info error: {e}")
            return None
    
    def get_all_users(self) -> list:
        """Get all users (admin only)"""
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT id, username, email, full_name, role, is_active, created_at, last_login
                FROM users
                ORDER BY created_at DESC
            """)
            
            users = [dict(row) for row in cursor.fetchall()]
            conn.close()
            
            return users
            
        except Exception as e:
            print(f"Get all users error: {e}")
            return []
