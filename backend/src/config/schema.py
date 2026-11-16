from sqlalchemy import inspect, text
from src.config.database import Base, engine


def ensure_schema():
    """ORM 建初表；对已存在的旧库补齐新增列（无在线迁移器，保持轻量）。"""
    Base.metadata.create_all(engine)
    additions = {
        'daily_volumes': {
            'source': "VARCHAR(20) NOT NULL DEFAULT 'manual'",
            'publication_id': 'INTEGER',
            'published_event_seq': 'INTEGER',
        },
    }
    with engine.begin() as conn:
        inspector = inspect(conn)
        tables = set(inspector.get_table_names())
        for table, columns in additions.items():
            if table not in tables:
                continue
            existing = {c['name'] for c in inspector.get_columns(table)}
            for name, ddl in columns.items():
                if name not in existing:
                    conn.execute(text(f'ALTER TABLE {table} ADD COLUMN {name} {ddl}'))
        # 预建单例水位行：并发接收/发布都靠它的行锁串行化。
        if 'event_stream_state' in tables:
            if conn.dialect.name == 'postgresql':
                conn.execute(text(
                    'INSERT INTO event_stream_state (id,last_seq,published_seq) '
                    'VALUES (1,0,0) ON CONFLICT (id) DO NOTHING'
                ))
            else:
                conn.execute(text(
                    'INSERT OR IGNORE INTO event_stream_state (id,last_seq,published_seq) '
                    'VALUES (1,0,0)'
                ))
