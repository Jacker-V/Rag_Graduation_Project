"""
JSON-based chat history storage system
Each user's chat history is stored in a separate JSON file
"""
import json
import os
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional


class ChatStorage:
    """Manages chat history storage as JSON files per user"""
    
    def __init__(self, storage_dir: str = "data/chat_history"):
        """
        Initialize chat storage
        
        Args:
            storage_dir: Directory to store user chat history JSON files
        """
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        print(f"Chat storage initialized at: {self.storage_dir}")
    
    def _get_user_file(self, user_id: int) -> Path:
        """Get the JSON file path for a specific user"""
        return self.storage_dir / f"user_{user_id}_history.json"
    
    def save_chat(
        self,
        user_id: int,
        question: str,
        answer: str,
        sources: Optional[List[Dict]] = None,
        session_id: Optional[str] = None
    ) -> bool:
        """
        Save a chat interaction to user's JSON file
        
        Args:
            user_id: User ID
            question: User's question
            answer: System's answer
            sources: List of source documents
            session_id: Session identifier
            
        Returns:
            bool: True if saved successfully
        """
        try:
            file_path = self._get_user_file(user_id)
            
            # Load existing history
            history = []
            if file_path.exists():
                with open(file_path, 'r', encoding='utf-8') as f:
                    history = json.load(f)
            
            # Create new chat entry
            chat_entry = {
                'id': len(history) + 1,
                'session_id': session_id,
                'question': question,
                'answer': answer,
                'sources': sources or [],
                'timestamp': datetime.now().isoformat()
            }
            
            # Append and save
            history.append(chat_entry)
            
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(history, f, ensure_ascii=False, indent=2)
            
            print(f"✓ Saved chat for user {user_id} (total: {len(history)} messages)")
            return True
            
        except Exception as e:
            print(f"✗ Error saving chat for user {user_id}: {e}")
            return False
    
    def get_user_history(self, user_id: int, limit: Optional[int] = None) -> List[Dict]:
        """
        Get chat history for a specific user
        
        Args:
            user_id: User ID
            limit: Maximum number of recent chats to return (None for all)
            
        Returns:
            List of chat entries (most recent first)
        """
        try:
            file_path = self._get_user_file(user_id)
            
            if not file_path.exists():
                return []
            
            with open(file_path, 'r', encoding='utf-8') as f:
                history = json.load(f)
            
            # Return most recent first
            history.reverse()
            
            if limit:
                history = history[:limit]
            
            return history
            
        except Exception as e:
            print(f"✗ Error loading history for user {user_id}: {e}")
            return []
    
    def get_user_chat_count(self, user_id: int) -> int:
        """
        Get total number of chats for a user
        
        Args:
            user_id: User ID
            
        Returns:
            int: Number of chat interactions
        """
        try:
            file_path = self._get_user_file(user_id)
            
            if not file_path.exists():
                return 0
            
            with open(file_path, 'r', encoding='utf-8') as f:
                history = json.load(f)
            
            return len(history)
            
        except Exception as e:
            print(f"✗ Error counting chats for user {user_id}: {e}")
            return 0
    
    def clear_user_history(self, user_id: int) -> bool:
        """
        Clear all chat history for a user
        
        Args:
            user_id: User ID
            
        Returns:
            bool: True if cleared successfully
        """
        try:
            file_path = self._get_user_file(user_id)
            
            if file_path.exists():
                file_path.unlink()
                print(f"✓ Cleared history for user {user_id}")
            
            return True
            
        except Exception as e:
            print(f"✗ Error clearing history for user {user_id}: {e}")
            return False
    
    def get_session_history(self, user_id: int, session_id: str) -> List[Dict]:
        """
        Get chat history for a specific session
        
        Args:
            user_id: User ID
            session_id: Session identifier
            
        Returns:
            List of chat entries for the session
        """
        try:
            all_history = self.get_user_history(user_id)
            return [chat for chat in all_history if chat.get('session_id') == session_id]
            
        except Exception as e:
            print(f"✗ Error loading session history: {e}")
            return []
    
    def get_all_users(self) -> List[int]:
        """
        Get list of all user IDs that have chat history
        
        Returns:
            List of user IDs
        """
        try:
            user_ids = []
            for file_path in self.storage_dir.glob("user_*_history.json"):
                # Extract user_id from filename like "user_1_history.json"
                filename = file_path.stem  # Gets "user_1_history"
                user_id_str = filename.split('_')[1]  # Gets "1"
                user_ids.append(int(user_id_str))
            
            return sorted(user_ids)
            
        except Exception as e:
            print(f"✗ Error getting user list: {e}")
            return []
    
    def export_user_history(self, user_id: int, export_path: str) -> bool:
        """
        Export user's chat history to a different location
        
        Args:
            user_id: User ID
            export_path: Path to export the JSON file
            
        Returns:
            bool: True if exported successfully
        """
        try:
            file_path = self._get_user_file(user_id)
            
            if not file_path.exists():
                print(f"No history found for user {user_id}")
                return False
            
            import shutil
            shutil.copy2(file_path, export_path)
            print(f"✓ Exported history for user {user_id} to {export_path}")
            return True
            
        except Exception as e:
            print(f"✗ Error exporting history: {e}")
            return False


# Global instance
chat_storage = ChatStorage()
