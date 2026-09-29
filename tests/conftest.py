import os
import uuid

import pytest


@pytest.fixture
def pg():
    """A fresh, empty schema in a disposable test Postgres.

    Set TEST_DATABASE_URL (e.g. a local docker postgres). Never point this at
    the production database.
    """
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL not set")
    import psycopg

    schema = f"t_{uuid.uuid4().hex[:10]}"
    admin = psycopg.connect(url, autocommit=True)
    admin.execute(f"CREATE SCHEMA {schema}")
    conn = psycopg.connect(url, autocommit=False, options=f"-c search_path={schema}")
    try:
        yield conn
    finally:
        conn.close()
        admin.execute(f"DROP SCHEMA {schema} CASCADE")
        admin.close()
