"""Verifies the test harness itself works before any feature tests are added."""


def test_db_engine_creates_users_table(db_engine):
    from sqlalchemy import inspect
    inspector = inspect(db_engine)
    assert "users" in inspector.get_table_names()


def test_client_reaches_app(client):
    # Any cheap endpoint. If none exists, use /openapi.json which FastAPI always serves.
    response = client.get("/openapi.json")
    assert response.status_code == 200
