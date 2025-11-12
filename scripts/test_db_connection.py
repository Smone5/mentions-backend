#!/usr/bin/env python3
"""
Test database connection and diagnose issues.

This script helps diagnose PostgreSQL connection issues, particularly
with Supabase database connections.

Usage:
    python scripts/test_db_connection.py
"""

import asyncio
import os
import socket
import sys
from urllib.parse import urlsplit

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.config import settings


def test_dns_resolution(hostname: str):
    """Test DNS resolution for a hostname."""
    print(f"\n{'='*80}")
    print(f"DNS Resolution Test for: {hostname}")
    print('='*80)
    
    try:
        # Try getaddrinfo (what Python uses)
        addr_info = socket.getaddrinfo(hostname, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
        print(f"✅ DNS resolves successfully via Python's getaddrinfo")
        
        ipv4 = []
        ipv6 = []
        for info in addr_info:
            family, socktype, proto, canonname, sockaddr = info
            ip = sockaddr[0]
            if family == socket.AF_INET:
                ipv4.append(ip)
            elif family == socket.AF_INET6:
                ipv6.append(ip)
        
        if ipv4:
            print(f"   IPv4 addresses: {', '.join(set(ipv4))}")
        if ipv6:
            print(f"   IPv6 addresses: {', '.join(set(ipv6))}")
        
        return True
        
    except socket.gaierror as e:
        print(f"❌ DNS resolution failed: {e}")
        print(f"\n   This means Python cannot resolve '{hostname}'")
        return False
    except Exception as e:
        print(f"❌ Unexpected error: {e}")
        return False


async def test_postgres_connection(conn_string: str):
    """Test PostgreSQL connection."""
    print(f"\n{'='*80}")
    print("PostgreSQL Connection Test")
    print('='*80)
    
    # Mask password in output
    masked = conn_string
    parts = urlsplit(conn_string)
    if parts.password:
        masked = conn_string.replace(parts.password, "****")
    
    print(f"Connection string: {masked}")
    
    try:
        import psycopg
        
        print("\nAttempting connection...")
        conn = await psycopg.AsyncConnection.connect(conn_string, connect_timeout=10)
        print("✅ Connection successful!")
        
        # Try a simple query
        print("\nTesting query execution...")
        cur = await conn.execute("SELECT version()")
        version = await cur.fetchone()
        print(f"✅ Query successful!")
        print(f"   PostgreSQL version: {version[0][:80]}...")
        
        await conn.close()
        print("\n✅ Connection test PASSED")
        return True
        
    except ImportError:
        print("❌ psycopg module not found. Install with: pip install psycopg")
        return False
    except asyncio.TimeoutError:
        print("❌ Connection timeout after 10 seconds")
        return False
    except Exception as e:
        print(f"❌ Connection failed: {str(e)[:200]}")
        return False


def print_supabase_help(hostname: str):
    """Print help for getting Supabase connection string."""
    if hostname and hostname.startswith("db.") and ".supabase.co" in hostname:
        project_ref = hostname[3:-12] if len(hostname) > 15 else "unknown"
        
        print(f"\n{'='*80}")
        print("⚠️  SUPABASE CONNECTION STRING INSTRUCTIONS")
        print('='*80)
        print(f"\nYour current hostname: {hostname}")
        print(f"Project reference: {project_ref}")
        print("\nTo get the correct connection string:")
        print("\n1. Go to: https://supabase.com/dashboard")
        print(f"2. Select your project: {project_ref}")
        print("3. Navigate to: Settings > Database")
        print("4. Under 'Connection string', select the 'URI' tab")
        print("5. Choose 'Session mode' (port 5432) for direct connection")
        print("   OR 'Transaction mode' (port 6543) for connection pooling")
        print("\n6. Copy the connection string and update your .env file:")
        print(f"\n   DB_CONN=postgresql://postgres:[YOUR_PASSWORD]@[hostname]:5432/postgres")
        print("\n7. Replace [YOUR_PASSWORD] with your actual database password")
        print("   (found in the same Supabase settings page)")
        print('='*80)


async def main():
    """Main diagnostic function."""
    print("\n" + "="*80)
    print("DATABASE CONNECTION DIAGNOSTIC TOOL")
    print("="*80)
    
    # Get connection string from environment
    try:
        conn_string = settings.DB_CONN
        if not conn_string or not conn_string.strip():
            print("\n❌ ERROR: DB_CONN environment variable is not set or is empty")
            print("\nPlease set DB_CONN in your .env file:")
            print("   DB_CONN=postgresql://postgres:[PASSWORD]@[hostname]:5432/postgres")
            return False
        
        parts = urlsplit(conn_string)
        hostname = parts.hostname
        
        if not hostname:
            print("\n❌ ERROR: Invalid connection string - no hostname found")
            print(f"   Connection string: {conn_string[:50]}...")
            return False
        
        print(f"\nDatabase hostname: {hostname}")
        print(f"Port: {parts.port or '(default)'}")
        print(f"Database: {parts.path or '(default)'}")
        
        # Test DNS resolution
        dns_ok = test_dns_resolution(hostname)
        
        # Test PostgreSQL connection
        conn_ok = await test_postgres_connection(conn_string)
        
        # Provide help if needed
        if not dns_ok or not conn_ok:
            print_supabase_help(hostname)
            return False
        
        print(f"\n{'='*80}")
        print("✅ ALL TESTS PASSED - Database connection is working!")
        print('='*80)
        return True
        
    except Exception as e:
        print(f"\n❌ Error loading configuration: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    try:
        result = asyncio.run(main())
        sys.exit(0 if result else 1)
    except KeyboardInterrupt:
        print("\n\nInterrupted by user")
        sys.exit(1)

