"""Structured logging configuration."""

import logging
import sys
from core.config import settings


def setup_logging():
    """Configure structured logging based on environment."""
    
    # Set log level
    log_level = getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)
    
    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)
    
    # Remove existing handlers
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)
    
    # Create console handler
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(log_level)
    
    # Set formatter based on LOG_JSON setting
    if settings.LOG_JSON:
        # JSON formatter for production/GCP
        import json
        import traceback
        from datetime import datetime
        
        class JSONFormatter(logging.Formatter):
            def format(self, record):
                log_entry = {
                    "timestamp": datetime.utcnow().isoformat() + "Z",
                    "level": record.levelname,
                    "logger": record.name,
                    "message": record.getMessage(),
                }
                
                # Add exception info if present
                if record.exc_info:
                    log_entry["exception"] = {
                        "type": record.exc_info[0].__name__ if record.exc_info[0] else None,
                        "message": str(record.exc_info[1]) if record.exc_info[1] else None,
                        "traceback": traceback.format_exception(*record.exc_info),
                    }
                
                # Add extra fields
                if hasattr(record, "extra"):
                    log_entry.update(record.extra)
                
                return json.dumps(log_entry)
        
        formatter = JSONFormatter()
    else:
        # Human-readable formatter for local development
        formatter = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        )
    
    handler.setFormatter(formatter)
    root_logger.addHandler(handler)
    
    # Set levels for noisy libraries
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)

