"""Link validation service (Hard Rule #2)."""

import logging
import re

logger = logging.getLogger(__name__)

# Forbidden link patterns (Hard Rule #2: No links in replies)
LINK_PATTERNS = [
    r'https?://[^\s]+',           # http://example.com
    r'www\.[^\s]+',                # www.example.com
    r'\w+\.(com|net|org|io|co|ai|dev|app|tech|biz|info|me)[^\w]',  # example.com
    r'\w+\s+dot\s+\w+',            # example dot com
    r'link\s+in\s+(bio|profile)',  # link in bio
    r'dm\s+me\s+for',              # DM me for
    r'check\s+my\s+profile',       # check my profile
    r'see\s+my\s+bio',             # see my bio
]


def validate_no_links(text: str) -> tuple[bool, str]:
    """
    Check if text contains any link patterns.
    
    Enforces Hard Rule #2: No links in Reddit replies.
    
    Args:
        text: Text to validate
        
    Returns:
        (is_valid, reason) - True if no links found, False otherwise
    """
    if not text:
        return True, "OK"
    
    text_lower = text.lower()
    
    for pattern in LINK_PATTERNS:
        if re.search(pattern, text_lower):
            logger.warning(f"Link pattern detected: {pattern}")
            return False, f"Found forbidden link pattern: {pattern}"
    
    logger.info("Link validation passed")
    return True, "OK"

