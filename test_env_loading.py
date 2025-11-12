#!/usr/bin/env python3
"""Test script to check what DB_CONN is being loaded from environment."""

import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))

from core.config import settings
from urllib.parse import urlsplit

# Show what DB_CONN was loaded
conn_string = settings.DB_CONN
parts = urlsplit(conn_string)

print("\n" + "="*80)
print("DB_CONN ENVIRONMENT VARIABLE TEST")
print("="*80)
print(f"\nFull connection string (masked):")
print(f"  {parts.scheme}://{parts.username}:****@{parts.hostname}:{parts.port}{parts.path}")
print(f"\nHostname: {parts.hostname}")
print(f"Port: {parts.port}")
print(f"Username: {parts.username}")
print(f"Database: {parts.path.lstrip('/')}")
print("\n" + "="*80)
print("\nIf this hostname is NOT the one you put in your .env file,")
print("then the .env file is not being read correctly.")
print("="*80 + "\n")

