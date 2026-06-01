# server/config.py
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator
from server.database import Database
from server.logging_config import configure_logging, get_logger

# Initialize logging with our custom configuration
logger = get_logger("instance")

global_db = Database()
logger.info("Global database manager initialized")

@asynccontextmanager
async def app_lifespan(app: FastMCP) -> AsyncIterator[dict]:
    """Manage application lifecycle."""
    mcp.state = {"db": global_db}
    logger.info("Application startup - using global database manager")
    
    try:
        yield {"db": global_db}
    finally:
        # Don't close connections on individual session end
        pass

# Create the MCP instance
# Streamable HTTP 트랜스포트의 DNS rebinding 보호(Host/Origin 화이트리스트)를 비활성화한다.
# 기본값은 localhost 만 허용해 LAN IP 로 접속하는 클라이언트가 421(Misdirected Request)을 받는다.
# 본 서버는 사설 LAN 내부에서만 접근 가능하고 외부는 라우터 NAT 로 차단되므로
# Host 화이트리스트 검증을 끈다 (운영자 위협 모델 수용).
mcp = FastMCP(
    "pg-mcp-server",
    debug=True,
    lifespan=app_lifespan,
    dependencies=["asyncpg", "mcp"],
    transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
)