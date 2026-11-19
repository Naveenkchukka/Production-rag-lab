"""Create a bounded Postgres pool without opening sockets at import time."""

from psycopg.conninfo import make_conninfo
from psycopg_pool import ConnectionPool

from app.settings import Settings


def create_pool(settings: Settings) -> ConnectionPool:
    conninfo = make_conninfo(
        host=settings.rag_db_host,
        port=settings.rag_db_port,
        dbname=settings.rag_db_name,
        user=settings.rag_db_user,
        password=settings.rag_db_password.get_secret_value(),
        connect_timeout=5,
        application_name="harbordesk-api",
    )
    # The connection string is never logged; make_conninfo safely quotes values.
    return ConnectionPool(
        conninfo=conninfo,
        min_size=1,
        max_size=4,
        timeout=5,
        open=False,
        name="harbordesk-api",
    )
