# server/tools/connection.py
import os
import re
from urllib.parse import urlsplit, urlunsplit
from server.config import mcp, global_db
from mcp.server.fastmcp import Context
from server.logging_config import get_logger

logger = get_logger("pg-mcp.tools.connection")

# Auto-register default DSN from env so clients never need to handle credentials.
DEFAULT_DSN = os.environ.get("PG_DSN") or os.environ.get("DATABASE_URL")
DEFAULT_CONN_ID = global_db.register_connection(DEFAULT_DSN) if DEFAULT_DSN else None
if DEFAULT_CONN_ID:
    logger.info(f"Auto-registered default connection from env: {DEFAULT_CONN_ID}")

# 시스템/템플릿 DB는 선택 대상에서 제외 (list_databases·connect(database=) 공통).
_SYSTEM_DBS = {"postgres", "template0", "template1"}

# database= 로 받는 이름은 식별자 안전 문자만 허용 — URL 구분자(`/ ? # @ :` 공백 등) 차단해
# DSN path/query 주입을 막는다. 비정형 이름이 필요하면 full connection_string 경로를 쓴다.
_DB_NAME_RE = re.compile(r"^[A-Za-z0-9_-]+$")


def _validate_db_name(database: str) -> None:
    """database= 선택 가능 여부 검증: 시스템/템플릿 거부 + 식별자 안전성(주입 차단)."""
    if database.lower() in _SYSTEM_DBS:
        raise ValueError(f"'{database}' is a system/template database and not selectable")
    if not _DB_NAME_RE.match(database):
        raise ValueError(f"invalid database name: {database!r}")


def _dsn_with_db(dsn: str, dbname: str) -> str:
    """dsn 의 database(URL path)만 dbname 으로 교체하고 scheme/netloc/query(sslmode 등)는 보존한다.
    DEFAULT_DSN 의 기존 dbname 과 동일하게 넘기면 urlsplit/urlunsplit 왕복이 원문과 바이트 동일이라
    register_connection 결과 conn_id 가 DEFAULT_CONN_ID 와 일치한다(중복 풀 방지)."""
    parts = urlsplit(dsn)
    return urlunsplit(parts._replace(path=f"/{dbname}"))


def register_connection_tools():
    """Register the database connection tools with the MCP server."""
    logger.debug("Registering database connection tools")

    @mcp.tool()
    async def connect(connection_string: str = "", database: str = "", *, ctx: Context):
        """
        Return a connection ID for a PostgreSQL database.

        Resolution priority:
        - connection_string non-empty → used as-is (database is ignored)
        - else database non-empty      → swap dbname into the server's default DSN,
          reusing the server's credentials/certs (use list_databases to discover names)
        - else                         → server default DSN (PG_DSN / DATABASE_URL env)

        Args:
            connection_string: full PostgreSQL connection string (optional)
            database: database name to connect to via the server's default credentials (optional)
            ctx: Request context (injected by the framework)

        Returns:
            Dictionary containing the connection ID
        """
        db = mcp.state["db"]
        if connection_string:
            cs = connection_string
        elif database:
            _validate_db_name(database)
            if not DEFAULT_DSN:
                raise ValueError("database= requires PG_DSN/DATABASE_URL to be set on the server")
            cs = _dsn_with_db(DEFAULT_DSN, database)
        else:
            cs = DEFAULT_DSN
        if not cs:
            raise ValueError(
                "no connection_string/database given and no PG_DSN/DATABASE_URL env is set on the server"
            )
        conn_id = db.register_connection(cs)
        logger.info(f"Registered database connection with ID: {conn_id}")
        return {"conn_id": conn_id}

    @mcp.tool()
    async def list_databases(*, ctx: Context):
        """
        List selectable databases on the server, excluding system/template DBs.
        Returned names are usable directly with connect(database="<name>").
        New service databases appear automatically (dynamic catalog query).

        Returns:
            List of database names.
        """
        db = mcp.state["db"]
        if not DEFAULT_CONN_ID:
            raise ValueError("list_databases requires PG_DSN/DATABASE_URL to be set on the server")
        async with db.get_connection(DEFAULT_CONN_ID) as conn:
            rows = await conn.fetch(
                "SELECT datname FROM pg_database WHERE datistemplate = false ORDER BY datname"
            )
        return [r["datname"] for r in rows if r["datname"].lower() not in _SYSTEM_DBS]

    @mcp.tool()
    async def disconnect(conn_id: str, *, ctx: Context):
        """
        Close a specific database connection and remove it from the pool.
        
        Args:
            conn_id: Connection ID to disconnect (required)
            ctx: Request context (injected by the framework)
            
        Returns:
            Dictionary indicating success status
        """
        db = mcp.state["db"]

        if DEFAULT_CONN_ID and conn_id == DEFAULT_CONN_ID:
            logger.warning(f"Refusing to disconnect default connection: {conn_id}")
            return {"success": False, "error": "Cannot disconnect default connection"}

        if conn_id not in db._connection_map:
            logger.warning(f"Attempted to disconnect unknown connection ID: {conn_id}")
            return {"success": False, "error": "Unknown connection ID"}
        
        # Close the connection pool
        try:
            await db.close(conn_id)
            # Also remove from the connection mappings
            connection_string = db._connection_map.pop(conn_id, None)
            if connection_string in db._reverse_map:
                del db._reverse_map[connection_string]
            logger.info(f"Successfully disconnected database connection with ID: {conn_id}")
            return {"success": True}
        except Exception as e:
            logger.error(f"Error disconnecting connection {conn_id}: {e}")
            return {"success": False, "error": str(e)}