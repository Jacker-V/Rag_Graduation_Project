"""
Smart document query detection and optimization
"""
import re
from typing import Optional, Tuple


def extract_document_from_query(query: str, available_docs: list[str]) -> Optional[str]:
    """
    Extract specific document mentioned in query for smart filtering.
    
    Examples:
        "What is CTM.docx about?" -> "CTM.docx"
        "Summarize report.pdf" -> "report.pdf"
        "Tóm tắt file ABC.txt" -> "ABC.txt"
    
    Returns:
        Document filename if found, None otherwise
    """
    if not query or not available_docs:
        return None
    
    query_lower = query.lower()
    
    # Common patterns for document queries
    patterns = [
        r'what\s+is\s+([^\s?]+?\.\w+)\s+about',
        r'summarize\s+([^\s?]+?\.\w+)',
        r'tell\s+me\s+about\s+([^\s?]+?\.\w+)',
        r'tóm\s+tắt\s+([^\s?]+?\.\w+)',
        r'([^\s?]+?\.\w+)\s+về\s+cái\s+gì',
        r'([^\s?]+?\.\w+)\s+nói\s+về\s+gì',
        r'file\s+([^\s?]+?\.\w+)',
        r'document\s+([^\s?]+?\.\w+)',
    ]
    
    for pattern in patterns:
        match = re.search(pattern, query_lower, re.IGNORECASE)
        if match:
            potential_doc = match.group(1)
            # Check if this document exists in available docs (case-insensitive)
            for doc in available_docs:
                if doc.lower() == potential_doc.lower():
                    return doc
    
    return None


def translate_query_to_vietnamese(query: str) -> Tuple[str, bool]:
    """
    Translate document summary queries to Vietnamese for Vietnamese responses.
    
    Returns:
        (translated_query, was_translated)
    """
    query_lower = query.lower().strip()
    
    # Patterns that should be translated to Vietnamese
    # Order matters - more specific patterns first
    patterns = [
        # Static patterns (no capture groups) - must come before generic patterns
        (r'^what\s+about\s+(?:this|that)\s+(?:document|doc|file).*$', 'Cho tôi biết tài liệu này nói về điều gì'),
        (r'^summarize\s+(?:this|that|the)\s+(?:document|doc|file).*$', 'Hãy tóm tắt tài liệu này'),
        # Patterns with capture groups
        (r'^what\s+is\s+(.+?)\s+about\??$', r'Tóm tắt nội dung chính của \1'),
        (r'^summarize\s+(.+?)$', r'Tóm tắt \1'),
        (r'^tell\s+me\s+about\s+(.+?)$', r'Cho tôi biết thông tin về \1'),
        (r'^describe\s+(.+?)$', r'Mô tả \1'),
        (r'^what\s+about\s+(.+?\.[^\s?]+)\??$', r'Cho tôi biết thông tin về \1'),
        (r'^what\s+about\s+document\s+(.+?)\??$', r'Cho tôi biết thông tin về \1'),
    ]
    
    for pattern, replacement in patterns:
        match = re.search(pattern, query_lower, re.IGNORECASE)
        if match:
            # Get the original case for document name
            original_match = re.search(pattern, query, re.IGNORECASE)
            doc_name = ''
            if original_match and original_match.lastindex:
                doc_name = original_match.group(1)

            if r'\1' in replacement:
                if not doc_name:
                    continue
                translated = replacement.replace(r'\1', doc_name)
            else:
                translated = replacement
            return translated, True
    
    return query, False


def should_use_vietnamese_response(query: str) -> bool:
    """
    Determine if response should be in Vietnamese based on query language.
    """
    vietnamese_indicators = [
        'tóm tắt', 'về cái gì', 'nói về', 'giải thích', 'cho tôi biết',
        'hãy', 'là gì', 'như thế nào', 'tại sao'
    ]
    
    query_lower = query.lower()
    return any(indicator in query_lower for indicator in vietnamese_indicators)
