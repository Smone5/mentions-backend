"""PostgreSQL checkpointer for LangGraph state persistence."""

import logging
import socket
from contextlib import asynccontextmanager
from typing import Optional
from urllib.parse import urlsplit, urlunsplit

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from core.database import get_db_connection_string

logger = logging.getLogger(__name__)

try:  # psycopg is an optional dependency in some environments
    from psycopg import OperationalError  # type: ignore
    from psycopg import AsyncConnection  # type: ignore
except ImportError:  # pragma: no cover - only triggered if psycopg isn't installed
    OperationalError = Exception  # type: ignore
    AsyncConnection = None  # type: ignore


class PoolerSafeAsyncPostgresSaver(AsyncPostgresSaver):
    """
    AsyncPostgresSaver that handles prepared statement conflicts for connection poolers.
    
    This is required for Supabase Transaction Pooler where connections are reused
    across different clients and prepared statements can conflict.
    """
    
    async def setup(self) -> None:
        """Setup without prepared statements for pooler compatibility."""
        # Ensure prepared statements are disabled on the connection
        # This should already be set before calling setup(), but we ensure it here
        self.conn.prepare_threshold = None  # None = never prepare
        
        # Run migrations normally - the connection-level setting applies to all cursors
        try:
            for migration in self.MIGRATIONS:
                async with self.conn.cursor() as cur:
                    try:
                        await cur.execute(migration)
                    except Exception as e:
                        # If table already exists, that's okay - skip this migration
                        if "already exists" in str(e):
                            logger.debug(f"Migration object already exists (this is okay): {e}")
                            continue
                        raise
            
            logger.debug("PostgreSQL checkpointer setup completed successfully")
        except Exception:
            # Re-raise any unexpected errors
            raise


_conn_string: Optional[str] = None
_initialized: bool = False


async def initialize_checkpointer() -> None:
    """
    Initialize the LangGraph checkpointer.
    
    Stores the configured PostgreSQL connection string. The actual connection
    is deferred until the first workflow run so the application can start even
    if the database is temporarily unavailable.
    """
    global _conn_string, _initialized
    
    conn_string = get_db_connection_string()
    if conn_string:
        conn_string = conn_string.strip()
    
    # Debug: Log the connection string (masked)
    if conn_string:
        from urllib.parse import urlsplit
        parts = urlsplit(conn_string)
        masked = f"{parts.scheme}://{parts.username}:****@{parts.hostname}:{parts.port}{parts.path}"
        logger.info(f"🔍 DEBUG: Loaded DB_CONN from environment: {masked}")
    else:
        logger.warning("🔍 DEBUG: DB_CONN is empty or not set")
    
    if not conn_string:
        _conn_string = None
        logger.warning(
            "LangGraph checkpointer: DB_CONN is empty. "
            "Falling back to in-memory checkpointing (no persistence)."
        )
    else:
        _conn_string = conn_string
        logger.info(
            "LangGraph checkpointer connection string stored (Postgres connection will be created on first use)"
        )
    
    _initialized = True


async def cleanup_checkpointer() -> None:
    """
    Cleanup the LangGraph checkpointer.
    
    This should be called at application shutdown.
    """
    global _conn_string, _initialized
    
    _conn_string = None
    _initialized = False
    logger.info("LangGraph checkpointer cleaned up")


def _replace_host(conn_string: str, new_host: str) -> str:
    """Return a new connection string with the hostname replaced."""
    parts = urlsplit(conn_string)
    if not parts.hostname:
        return conn_string
    
    netloc = parts.netloc
    auth = ""
    hostport = netloc
    
    if "@" in netloc:
        auth, hostport = netloc.rsplit("@", 1)
    
    host = hostport
    port = ""
    if ":" in hostport:
        host, port = hostport.split(":", 1)
    
    host = new_host
    hostport = host + (f":{port}" if port else "")
    netloc = f"{auth}@{hostport}" if auth else hostport
    
    return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))


def _test_dns_resolution(hostname: str) -> dict:
    """
    Test DNS resolution for a hostname and return diagnostic information.
    
    Returns:
        dict with keys: 'resolves', 'ipv4', 'ipv6', 'error'
    """
    result = {
        'resolves': False,
        'ipv4': [],
        'ipv6': [],
        'error': None
    }
    
    try:
        # Try to resolve the hostname
        addr_info = socket.getaddrinfo(hostname, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
        result['resolves'] = True
        
        for info in addr_info:
            family, socktype, proto, canonname, sockaddr = info
            ip = sockaddr[0]
            
            if family == socket.AF_INET:
                result['ipv4'].append(ip)
            elif family == socket.AF_INET6:
                result['ipv6'].append(ip)
        
    except socket.gaierror as e:
        result['error'] = str(e)
    except Exception as e:
        result['error'] = f"Unexpected error: {str(e)}"
    
    return result


def _convert_to_pooler(conn_string: str) -> Optional[str]:
    """
    Convert a Supabase direct connection string to pooler format.
    
    Note: This is deprecated as Supabase has changed their infrastructure.
    Users should get the correct connection string from their Supabase dashboard.
    
    Example:
        Input:  postgresql://postgres:pass@db.xxx.supabase.co:5432/postgres
        Output: None (pooler format no longer supported this way)
    """
    # Pooler conversion is disabled as Supabase infrastructure has changed
    # Users should use the connection string from their Supabase dashboard
    return None


@asynccontextmanager
async def _postgres_checkpointer(conn_string: str):
    """
    Attempt to use the PostgreSQL checkpointer with diagnostics and fallback strategies.
    
    Strategies:
    1. Try the provided connection string (with prepare_threshold=0 for poolers)
    2. If hostname is 'postgres', try 'localhost' (Docker environments)
    3. Provide detailed diagnostics if connection fails
    
    Note: prepare_threshold=0 disables prepared statements, which is required for
    Supabase Transaction pooler and other connection poolers.
    """
    original_host = urlsplit(conn_string).hostname
    
    # Check if using a pooler (port 6543 or hostname contains 'pooler')
    using_pooler = ':6543' in conn_string or 'pooler' in conn_string.lower()
    
    # Strategy 1: Try original connection string
    try:
        logger.debug(f"Attempting PostgreSQL connection to {original_host} (pooler: {using_pooler})")
        
        # For poolers, we need to disable prepared statements
        if using_pooler:
            from psycopg import AsyncConnection
            
            # Create connection for pooler
            conn = await AsyncConnection.connect(
                conn_string,
                autocommit=True
            )
            
            # CRITICAL: Set prepare_threshold to None (not 0!) IMMEDIATELY
            # None = never prepare, 0 = always prepare!
            conn.prepare_threshold = None
            
            try:
                # Use our custom PoolerSafeAsyncPostgresSaver that handles prepared statements safely
                checkpointer = PoolerSafeAsyncPostgresSaver(conn)
                await checkpointer.setup()
                logger.info(f"✅ PostgreSQL checkpointer connected successfully to {original_host} (pooler mode, prepared statements disabled)")
                yield checkpointer
            finally:
                await conn.close()
        else:
            # Non-pooler connection can use prepared statements
            async with AsyncPostgresSaver.from_conn_string(conn_string) as checkpointer:
                logger.info(f"✅ PostgreSQL checkpointer connected successfully to {original_host}")
                yield checkpointer
        return
    except OperationalError as exc:  # type: ignore[misc]
        error_msg = str(exc)
        logger.warning(f"Primary connection failed: {error_msg[:100]}")
        
        # Strategy 2: If hostname is 'postgres', try 'localhost' (Docker environments)
        if "[Errno 8]" in error_msg and original_host == "postgres":
            logger.info(
                "LangGraph checkpointer: hostname 'postgres' not resolvable. "
                "Retrying with 'localhost'..."
            )
            alt_conn = _replace_host(conn_string, "localhost")
            try:
                if using_pooler:
                    from psycopg import AsyncConnection
                    
                    # Create connection for localhost pooler
                    conn = await AsyncConnection.connect(
                        alt_conn,
                        autocommit=True
                    )
                    
                    # Disable prepared statements immediately
                    conn.prepare_threshold = None  # None = never prepare!
                    
                    try:
                        checkpointer = PoolerSafeAsyncPostgresSaver(conn)
                        await checkpointer.setup()
                        logger.info("✅ PostgreSQL checkpointer connected to localhost (pooler mode, prepared statements disabled)")
                        yield checkpointer
                    finally:
                        await conn.close()
                else:
                    async with AsyncPostgresSaver.from_conn_string(alt_conn) as checkpointer:
                        logger.info("✅ PostgreSQL checkpointer connected to localhost")
                        yield checkpointer
                return
            except Exception as localhost_exc:
                logger.warning(
                    f"LangGraph checkpointer: localhost retry failed: {str(localhost_exc)[:100]}"
                )
        
        # Provide detailed diagnostics for DNS issues
        if "[Errno 8]" in error_msg and original_host:
            dns_info = _test_dns_resolution(original_host)
            logger.error(
                f"❌ DNS Resolution Diagnostics for '{original_host}':\n"
                f"   Resolves: {dns_info['resolves']}\n"
                f"   IPv4 addresses: {dns_info['ipv4']}\n"
                f"   IPv6 addresses: {dns_info['ipv6']}\n"
                f"   Error: {dns_info['error']}"
            )
            
            if original_host.startswith("db.") and ".supabase.co" in original_host:
                project_ref = original_host[3:-12] if len(original_host) > 15 else "unknown"
                logger.error(
                    "\n" + "="*80 + "\n"
                    "⚠️  SUPABASE CONNECTION STRING ISSUE DETECTED\n"
                    "="*80 + "\n"
                    f"The hostname '{original_host}' cannot be resolved from Python.\n\n"
                    "SOLUTION: Update your DB_CONN environment variable with the correct connection string.\n\n"
                    "To get the correct connection string:\n"
                    "1. Go to your Supabase dashboard: https://supabase.com/dashboard\n"
                    f"2. Select your project: {project_ref}\n"
                    "3. Go to: Settings > Database > Connection string\n"
                    "4. Select 'URI' tab and copy the connection string\n"
                    "5. Use 'Session mode' (port 5432) for direct connection\n"
                    "   OR 'Transaction mode' (port 6543) for pooling\n\n"
                    "The connection string should look like:\n"
                    "  postgresql://postgres:[PASSWORD]@[hostname]:5432/postgres\n\n"
                    "Update your .env file with the correct DB_CONN value.\n"
                    "="*80
                )
        
        # All strategies failed
        logger.error(
            "LangGraph checkpointer: failed to connect to Postgres after trying all fallback strategies."
        )
        raise
    except Exception as exc:
        logger.exception(
            "LangGraph checkpointer: unexpected error creating Postgres checkpointer."
        )
        raise


def get_checkpointer():
    """
    Get a checkpointer context manager for LangGraph.
    
    Requires a valid PostgreSQL connection string and raises if checkpointing
    cannot be initialized.
    """
    if not _initialized:
        raise RuntimeError("Checkpointer not initialized. Call initialize_checkpointer() at startup.")
    
    if _conn_string is None:
        raise RuntimeError(
            "DB_CONN is not configured. Set the database connection string to enable LangGraph checkpointing."
        )
    
    return _postgres_checkpointer(_conn_string)

