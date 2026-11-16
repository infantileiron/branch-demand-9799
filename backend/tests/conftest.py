import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault('JWT_SECRET', 'test-secret')
os.environ.setdefault('REDIS_URL', 'redis://localhost:6399/0')
os.environ.setdefault('DATABASE_URL', 'sqlite+pysqlite:///' + tempfile.mktemp(suffix='.db'))

import pytest  # noqa: E402

from src.config.database import Base, Session, engine  # noqa: E402
from src.config.schema import ensure_schema  # noqa: E402


class FakeRedis:
    def __init__(self):
        self.queues = {}

    def rpush(self, name, *values):
        self.queues.setdefault(name, []).extend(values)
        return len(self.queues[name])

    def blpop(self, name, timeout=0):
        queue = self.queues.get(name) or []
        return (name, queue.pop(0)) if queue else None


@pytest.fixture(autouse=True)
def fake_redis(monkeypatch):
    import redis
    from src.routes import api as routes
    fake = FakeRedis()

    def from_url(*args, **kwargs):
        return fake

    monkeypatch.setattr(redis.Redis, 'from_url', staticmethod(from_url))
    monkeypatch.setattr(routes.redis.Redis, 'from_url', staticmethod(from_url))
    return fake


@pytest.fixture()
def client(monkeypatch):
    from src.main import app
    from fastapi.testclient import TestClient

    Base.metadata.drop_all(engine)
    ensure_schema()
    from scripts.seed_demo import seed
    seed()
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def tokens(client):
    def login(email):
        r = client.post('/auth/login', json={'email': email, 'password': 'Demo123!'})
        assert r.status_code == 200, r.text
        return {'Authorization': 'Bearer ' + r.json()['token']}

    return {
        'analyst': login('analyst@demo.local'),
        'admin': login('admin@demo.local'),
        'viewer': login('viewer@demo.local'),
    }


@pytest.fixture()
def session():
    with Session() as s:
        yield s
