from sqlalchemy import (
 Boolean,
 Column,
 Float,
 ForeignKey,
 Index,
 Integer,
 JSON,
 String,
 Text,
 UniqueConstraint,
)
from src.config.database import Base


class User(Base):
    __tablename__ = 'users'
    id = Column(Integer, primary_key=True); email = Column(String(100), unique=True); password = Column(String(200)); role = Column(String(20))


class DailyVolume(Base):
    __tablename__ = 'daily_volumes'; __table_args__ = (UniqueConstraint('branch', 'day', name='uq_branch_day'),)
    id = Column(Integer, primary_key=True); branch = Column(String(30), nullable=False); day = Column(String(10), nullable=False); volume = Column(Integer, nullable=False); note = Column(Text, default='')
    # source=manual 表示人工日结；source=event 表示由工单变更流发布。只有本表的行才是“已生效日量”。
    source = Column(String(20), nullable=False, default='manual', server_default='manual')
    publication_id = Column(Integer, ForeignKey('daily_publications.id'))
    published_event_seq = Column(Integer)


class ForecastRun(Base):
    __tablename__ = 'forecast_runs'
    id = Column(Integer, primary_key=True); name = Column(String(100)); branch = Column(String(30)); backtest_days = Column(Integer); alpha = Column(Float); beta = Column(Float); state = Column(String(20), default='queued'); result = Column(JSON); error = Column(Text, default='')


class Staffing(Base):
    __tablename__ = 'staffings'
    id = Column(Integer, primary_key=True); run_id = Column(Integer, ForeignKey('forecast_runs.id')); capacity = Column(Integer); model = Column(String(30)); schedule = Column(JSON); note = Column(Text); status = Column(String(20), default='draft')


class Audit(Base):
    __tablename__ = 'audits'
    id = Column(Integer, primary_key=True); actor = Column(String(100)); action = Column(String(200)); created = Column(String(40))


class EventStreamState(Base):
    """单例行( id=1 )：last_seq 是事件日志水位，published_seq 是已发布水位。"""
    __tablename__ = 'event_stream_state'
    id = Column(Integer, primary_key=True)
    last_seq = Column(Integer, nullable=False, default=0)
    published_seq = Column(Integer, nullable=False, default=0)


class WorkOrderEvent(Base):
    """原始工单变更事件。每条投递都保留，status 决定它是否参与重建。"""
    __tablename__ = 'work_order_events'
    __table_args__ = (
        UniqueConstraint('delivery_id', name='uq_event_delivery'),
        Index('ix_event_order_version', 'order_no', 'version'),
        Index('ix_event_status', 'status'),
        Index('ix_event_accepted_date', 'accepted_date'),
    )
    id = Column(Integer, primary_key=True)
    delivery_id = Column(String(100))
    order_no = Column(String(64), nullable=False)
    version = Column(Integer, nullable=False)
    accepted_date = Column(String(10), nullable=False)
    branch = Column(String(30), nullable=False)
    cancelled = Column(Boolean, nullable=False, default=False)
    content_hash = Column(String(64), nullable=False)
    status = Column(String(20), nullable=False, default='applied')
    note = Column(Text, default='')
    actor = Column(String(100), default='')
    received = Column(String(40), default='')
    # 该事件被哪次发布纳入日量；为空表示已接收、尚未生效。
    published_seq = Column(Integer)
    conflict_id = Column(Integer)


class WorkOrder(Base):
    """由事件流维护的当前归属缓存；真正的重建仍以事件日志为准。"""
    __tablename__ = 'work_orders'
    id = Column(Integer, primary_key=True)
    order_no = Column(String(64), nullable=False, unique=True)
    version = Column(Integer, nullable=False)
    accepted_date = Column(String(10), nullable=False)
    branch = Column(String(30), nullable=False)
    cancelled = Column(Boolean, nullable=False, default=False)
    event_id = Column(Integer, ForeignKey('work_order_events.id'))
    updated = Column(String(40), default='')


class WorkOrderConflict(Base):
    """同工单同版本、内容不同的隔离区，必须人工核对后才能采用新内容。"""
    __tablename__ = 'work_order_conflicts'
    __table_args__ = (UniqueConstraint('order_no', 'version', 'incoming_hash', name='uq_work_order_conflict'),)
    id = Column(Integer, primary_key=True)
    order_no = Column(String(64), nullable=False)
    version = Column(Integer, nullable=False)
    existing_event_id = Column(Integer)
    incoming_event_id = Column(Integer)
    incoming_hash = Column(String(64), nullable=False)
    existing_content = Column(JSON)
    incoming_content = Column(JSON)
    status = Column(String(30), nullable=False, default='pending')
    note = Column(Text, default='')
    created = Column(String(40), default='')
    resolved_by = Column(String(100), default='')
    resolved_at = Column(String(40), default='')


class VolumeConflict(Base):
    """人工日量与事件流覆盖的网点日期差异。未核对前发布必须中止。"""
    __tablename__ = 'volume_conflicts'
    __table_args__ = (UniqueConstraint('branch', 'day', name='uq_volume_conflict_branch_day'),)
    id = Column(Integer, primary_key=True)
    branch = Column(String(30), nullable=False)
    day = Column(String(10), nullable=False)
    manual_volume = Column(Integer, nullable=False)
    event_volume = Column(Integer, nullable=False)
    status = Column(String(30), nullable=False, default='open')
    note = Column(Text, default='')
    created = Column(String(40), default='')
    resolved_by = Column(String(100), default='')
    resolved_at = Column(String(40), default='')


class DailyPublication(Base):
    """每次发布把事件日志截至 published_seq 的全量重建结果落到 DailyVolume。"""
    __tablename__ = 'daily_publications'
    id = Column(Integer, primary_key=True)
    published_seq = Column(Integer, nullable=False)
    actor = Column(String(100), default='')
    state = Column(String(20), nullable=False, default='applied')
    created = Column(String(40), default='')
    stats = Column(JSON)
