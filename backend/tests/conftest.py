import os

import mongomock
import pytest

os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ.setdefault("MONGODB_URI", "mongodb://localhost/test")
os.environ.setdefault("OFF_USER_AGENT", "CalorieCounter/test (ci@example.com)")


@pytest.fixture
def app(monkeypatch):
    from app import db as db_module

    # mongomock gives us real query/index semantics without an Atlas cluster,
    # so the sync tests exercise the actual unique-index conflict path.
    client = mongomock.MongoClient()
    database = client["test"]
    db_module._ensure_indexes(database)
    monkeypatch.setattr(db_module, "_db", database)

    from app import create_app
    from app.limiter import limiter

    application = create_app()
    application.config["TESTING"] = True

    # The limiter's in-memory storage is process-wide (module-level Limiter
    # instance), so counts from one test would otherwise carry into the next.
    # Reset it per test so each test starts with a clean budget.
    limiter.reset()

    return application


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def auth(client):
    """Register a user and return an Authorization header."""
    response = client.post("/api/auth/register",
                           json={"email": "n@example.com", "password": "hunter2hunter2"})
    assert response.status_code == 201, response.get_json()
    return {"Authorization": f"Bearer {response.get_json()['token']}"}
