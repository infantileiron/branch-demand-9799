"""发布与接收并发验证。

SQLite 没有行锁语义，本文件只在 PostgreSQL 下运行：
    DATABASE_URL=postgresql+psycopg://... pytest tests/test_concurrency.py
"""
import os
import random
import threading

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get('DATABASE_URL', '').startswith('sqlite'),
    reason='需要 PostgreSQL 行锁才能验证发布与接收并发',
)

DAY = '2026-11-15'
BRANCHES = ['川北', '川南', '东河', '西浦']


class Actor:
    email = 'analyst@demo.local'


def _events(worker):
    rows = []
    for i in range(30):
        for j in range(3):
            order = f'W{worker}-{(i * 3 + j) // 2}'
            rows.append({
                'delivery_id': f'd-{worker}-{i}-{j}',
                'order_no': order,
                'version': 1 + ((i * 3 + j) % 2),
                'accepted_date': DAY,
                'branch': random.Random(order).choice(BRANCHES),
            })
    return rows


def test_publish_concurrent_with_ingest_stays_consistent(client, tokens):
    from datetime import date

    from sqlalchemy import func

    from src.config.database import Session
    from src.models.entities import DailyPublication, DailyVolume, EventStreamState, WorkOrderEvent
    from src.schemas.business import WorkOrderEventInput
    from src.services import events

    errors = []
    stop = threading.Event()

    def ingest(worker):
        try:
            batch = [WorkOrderEventInput(**row) for row in _events(worker)]
            for i in range(0, len(batch), 3):
                with Session() as s:
                    events.ingest_events(s, batch[i:i + 3], Actor())
        except Exception as exc:  # pragma: no cover - 只在并发缺陷时触发
            errors.append(('ingest', repr(exc)))

    def publisher():
        try:
            while not stop.is_set():
                with Session() as s:
                    try:
                        events.publish(s, Actor())
                    except events.PublishBlocked:
                        pass
        except Exception as exc:  # pragma: no cover
            errors.append(('publish', repr(exc)))

    ingesters = [threading.Thread(target=ingest, args=(w,)) for w in range(4)]
    publishers = [threading.Thread(target=publisher) for _ in range(2)]
    for t in ingesters + publishers:
        t.start()
    for t in ingesters:
        t.join()
    stop.set()
    for t in publishers:
        t.join()
    assert errors == []

    with Session() as s:
        events.publish(s, Actor())
        implied, cover, effective, _ = events.rebuild_rows(s)
        rows = {(v.branch, v.day): v for v in s.query(DailyVolume).all()}
        for key in cover:
            assert rows[key].volume == implied.get(key, 0)
        for key in effective:
            assert key in rows
        state = s.get(EventStreamState, 1)
        assert state.published_seq == state.last_seq
        assert s.query(WorkOrderEvent).filter_by(published_seq=None).count() == 0
        deliveries = s.query(WorkOrderEvent.delivery_id, func.count()).group_by(
            WorkOrderEvent.delivery_id
        ).having(func.count() > 1).all()
        assert deliveries == []
        assert s.query(DailyPublication).count() >= 1
        # 每次发布都按同一日志全量重建，最终值只取决于事件日志。
        orders = s.query(WorkOrderEvent).count()
        assert orders == 4 * 30 * 3
