# server/tools/connection.py
import os
from server.config import mcp, global_db
from mcp.server.fastmcp import Context
from server.logging_config import get_logger

logger = get_logger("pg-mcp.tools.connection")

# Auto-register default DSN from env so clients never need to handle credentials.
DEFAULT_DSN = os.environ.get("PG_DSN") or os.environ.get("DATABASE_URL")
DEFAULT_CONN_ID = global_db.register_connection(DEFAULT_DSN) if DEFAULT_DSN else None
if DEFAULT_CONN_ID:
    logger.info(f"Auto-registered default connection from env: {DEFAULT_CONN_ID}")

def register_connection_tools():
    """Register the database connection tools with the MCP server."""
    logger.debug("Registering database connection tools")

    @mcp.tool()
    async def connect(connection_string: str = "", *, ctx: Context):
        """
        Return a connection ID for a PostgreSQL database.
        If connection_string is empty, uses the server's default DSN
        (PG_DSN / DATABASE_URL env), which is the only supported mode in this deployment.

        Args:
            connection_string: PostgreSQL connection string (optional; empty = use default)
            ctx: Request context (injected by the framework)

        Returns:
            Dictionary containing the connection ID
        """
        db = mcp.state["db"]
        cs = connection_string or DEFAULT_DSN
        if not cs:
            raise ValueError(
                "connection_string is empty and no PG_DSN/DATABASE_URL env is set on the server"
            )
        conn_id = db.register_connection(cs)
        logger.info(f"Registered database connection with ID: {conn_id}")
        return {"conn_id": conn_id}

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