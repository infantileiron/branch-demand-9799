import hashlib
import json
from collections import defaultdict
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import select, text

from src.models.entities import (
    DailyPublication,
    DailyVolume,
    EventStreamState,
    VolumeConflict,
    WorkOrder,
    WorkOrderConflict,
    WorkOrderEvent,
)

EVENT_STATUSES = ('applied', 'conflict', 'rejected')


class PublishBlocked(Exception):
    """发布被待核对差异阻止；携带可序列化的差异详情。"""

    def __init__(self, payload):
        self.payload = payload
        super().__init__(payload.get('message', '发布被阻止'))


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def event_content(order_no, version, accepted_date, branch, cancelled):
    return {
        'order_no': order_no,
        'version': int(version),
        'accepted_date': accepted_date,
        'branch': branch,
        'cancelled': bool(cancelled),
    }


def content_hash(content):
    raw = json.dumps(content, sort_keys=True, ensure_ascii=False, separators=(',', ':'))
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()


def ensure_state(s):
    state = s.get(EventStreamState, 1)
    if state is None:
        state = EventStreamState(id=1, last_seq=0, published_seq=0)
        s.add(state)
        s.flush()
    return state


def lock_state(s):
    """发布与接收共用同一状态行锁，保证水位和归属处理互相可见。"""
    state = s.execute(
        select(EventStreamState).where(EventStreamState.id == 1).with_for_update()
    ).scalar_one_or_none()
    if state is None:
        # 启动时已预建；若旧库缺失则补建，唯一键保证并发下只有一行。
        s.execute(
            text(
                'INSERT INTO event_stream_state (id,last_seq,published_seq) '
                'VALUES (1,0,0) ON CONFLICT (id) DO NOTHING'
            )
            if s.bind.dialect.name == 'postgresql'
            else text(
                'INSERT OR IGNORE INTO event_stream_state (id,last_seq,published_seq) '
                'VALUES (1,0,0)'
            )
        )
        state = s.execute(
            select(EventStreamState).where(EventStreamState.id == 1).with_for_update()
        ).scalar_one()
    return state


def _content_of(event):
    return event_content(
        event.order_no, event.version, event.accepted_date, event.branch, event.cancelled
    )


def _refresh_work_order(s, order_no):
    """按已采用事件中的最高版本刷新归属缓存；迟到旧版不会回退。"""
    events = (
        s.query(WorkOrderEvent)
        .filter(WorkOrderEvent.order_no == order_no, WorkOrderEvent.status == 'applied')
        .all()
    )
    row = s.query(WorkOrder).filter_by(order_no=order_no).first()
    if not events:
        if row:
            s.delete(row)
        return None
    best = max(events, key=lambda e: (e.version, e.id))
    if row is None:
        row = WorkOrder(order_no=order_no)
        s.add(row)
    row.version = best.version
    row.accepted_date = best.accepted_date
    row.branch = best.branch
    row.cancelled = best.cancelled
    row.event_id = best.id
    row.updated = now_iso()
    return row


def _result(item, status, event_id=None, conflict_id=None, message=''):
    return {
        'order_no': item.order_no,
        'version': item.version,
        'accepted_date': item.accepted_date.isoformat(),
        'branch': item.branch,
        'cancelled': bool(item.cancelled),
        'status': status,
        'event_id': event_id,
        'conflict_id': conflict_id,
        'message': message,
    }


def _ingest_one(s, item, actor, state):
    order_no = item.order_no
    accepted = item.accepted_date.isoformat()
    content = event_content(order_no, item.version, accepted, item.branch, item.cancelled)
    digest = content_hash(content)
    delivery = item.delivery_id

    if delivery and s.query(WorkOrderEvent).filter_by(delivery_id=delivery).first():
        return _result(item, 'duplicate', message='投递ID已处理，重复投递未增量')

    same_version = (
        s.query(WorkOrderEvent)
        .filter(WorkOrderEvent.order_no == order_no, WorkOrderEvent.version == item.version)
        .all()
    )
    known = [e for e in same_version if e.status in ('applied', 'rejected')]
    if any(e.content_hash == digest for e in known):
        return _result(item, 'duplicate', message='同工单同版本同内容已存在，重复投递未增量')

    applied = sorted([e for e in same_version if e.status == 'applied'], key=lambda e: e.id)
    if applied:
        existing = applied[0]
        prior = (
            s.query(WorkOrderConflict)
            .filter_by(order_no=order_no, version=item.version, incoming_hash=digest)
            .first()
        )
        if prior:
            return _result(
                item, 'duplicate', conflict_id=prior.id,
                message='同一差异已在隔离区等待核对，重复投递未增量',
            )
        row = WorkOrderEvent(
            delivery_id=delivery, order_no=order_no, version=item.version,
            accepted_date=accepted, branch=item.branch, cancelled=bool(item.cancelled),
            content_hash=digest, status='conflict', note=item.note,
            actor=actor.email, received=now_iso(),
        )
        s.add(row)
        s.flush()
        conflict = WorkOrderConflict(
            order_no=order_no, version=item.version,
            existing_event_id=existing.id, incoming_event_id=row.id,
            incoming_hash=digest, existing_content=_content_of(existing),
            incoming_content=content, status='pending', note=item.note,
            created=now_iso(),
        )
        s.add(conflict)
        s.flush()
        row.conflict_id = conflict.id
        state.last_seq = max(state.last_seq or 0, row.id)
        return _result(
            item, 'conflict', event_id=row.id, conflict_id=conflict.id,
            message='同工单同版本内容不同，已隔离待核对，归属与日量均未改变',
        )

    higher = (
        s.query(WorkOrderEvent)
        .filter(
            WorkOrderEvent.order_no == order_no,
            WorkOrderEvent.version > item.version,
            WorkOrderEvent.status == 'applied',
        )
        .first()
    )
    row = WorkOrderEvent(
        delivery_id=delivery, order_no=order_no, version=item.version,
        accepted_date=accepted, branch=item.branch, cancelled=bool(item.cancelled),
        content_hash=digest, status='applied', note=item.note,
        actor=actor.email, received=now_iso(),
    )
    s.add(row)
    s.flush()
    _refresh_work_order(s, order_no)
    state.last_seq = max(state.last_seq or 0, row.id)
    message = '已接收并更新归属'
    if higher:
        message = f'迟到旧版本已记录；当前归属保持最高版本 v{higher.version}，不回退'
    return _result(item, 'applied', event_id=row.id, message=message)


def ingest_events(s, items, actor):
    """整批事件在一个事务内接收并更新归属，失败则全部回退。"""
    try:
        state = lock_state(s)
        results = [_ingest_one(s, item, actor, state) for item in items]
        s.commit()
    except HTTPException:
        s.rollback()
        raise
    except Exception:
        s.rollback()
        raise HTTPException(500, '事件接收失败，本批未生效，可安全重试')
    return results


def rebuild_rows(s, target_seq=None):
    """从事件日志全量重建：每单只取已采用事件中的最高版本。"""
    query = s.query(WorkOrderEvent).filter(WorkOrderEvent.status == 'applied')
    if target_seq is not None:
        query = query.filter(WorkOrderEvent.id <= target_seq)
    applied_events = query.all()
    events = applied_events
    best = {}
    for event in events:
        current = best.get(event.order_no)
        if current is None or (event.version, event.id) > (current.version, current.id):
            best[event.order_no] = event
    implied = defaultdict(int)
    effective = set()
    for event in best.values():
        key = (event.branch, event.accepted_date)
        effective.add(key)
        if not event.cancelled:
            implied[key] += 1
    cover = set(effective)
    # 事件曾经触及的网点日期都要纳入核对：转派/改受理日后原网点应被冲减为0，
    # 即使那一行后来被人工改成 manual，也不能悄悄留下旧值。
    for event in applied_events:
        cover.add((event.branch, event.accepted_date))
    # 以前发布过的事件日同样纳入重算。
    for row in s.query(DailyVolume).filter(DailyVolume.source == 'event').all():
        cover.add((row.branch, row.day))
    return implied, cover, effective, best


def _volume_rows(s):
    return {(r.branch, r.day): r for r in s.query(DailyVolume).all()}


def _volume_conflicts(s):
    return {(c.branch, c.day): c for c in s.query(VolumeConflict).all()}


def _is_adopted(row, conflict, event_volume):
    return bool(
        row is not None
        and row.source == 'manual'
        and conflict is not None
        and conflict.status == 'adopted'
        and conflict.manual_volume == row.volume
        and conflict.event_volume == event_volume
    )


def _is_kept_manual(row, conflict, event_volume):
    return bool(
        row is not None
        and row.source == 'manual'
        and conflict is not None
        and conflict.status == 'manual_kept'
        and conflict.manual_volume == row.volume
        and conflict.event_volume == event_volume
    )


def analyze(s, target_seq=None):
    """只读核对：给出事件重建结果、与现行日量的差异以及发布阻塞项。"""
    state = s.get(EventStreamState, 1)
    last_seq = (state.last_seq or 0) if state else 0
    published_seq = (state.published_seq or 0) if state else 0
    target = last_seq if target_seq is None else target_seq
    implied, cover, effective, best = rebuild_rows(s, target)
    rows = _volume_rows(s)
    conflicts = _volume_conflicts(s)
    differences = []
    blockers = []
    counts = defaultdict(int)
    for branch, day in sorted(cover):
        key = (branch, day)
        event_volume = implied.get(key, 0)
        row = rows.get(key)
        current = row.volume if row else None
        source = row.source if row else 'missing'
        conflict = conflicts.get(key)
        if row is None:
            if key not in effective:
                continue
            kind = 'new_zero' if event_volume == 0 else 'new'
            counts[kind] += 1
        elif _is_kept_manual(row, conflict, event_volume) and row.volume != event_volume:
            kind = 'manual_kept'
            counts[kind] += 1
        elif row.source == 'manual' and row.volume != event_volume:
            if _is_adopted(row, conflict, event_volume):
                kind = 'adopted_event'
                counts[kind] += 1
            else:
                kind = 'manual_conflict'
                counts[kind] += 1
                blockers.append({
                    'type': 'volume_conflict',
                    'branch': branch,
                    'day': day,
                    'manual_volume': row.volume,
                    'event_volume': event_volume,
                    'manual_publication_id': row.publication_id,
                    'message': f'{branch} {day} 人工日量{row.volume}与事件重建{event_volume}不一致',
                })
        elif row.volume != event_volume:
            kind = 'zeroed' if event_volume == 0 else 'changed'
            counts[kind] += 1
        else:
            continue
        differences.append({
            'branch': branch,
            'day': day,
            'event_volume': event_volume,
            'current_volume': current,
            'source': source,
            'kind': kind,
            'conflict_status': conflict.status if conflict else None,
            'conflict_id': conflict.id if conflict else None,
        })
    pending = (
        s.query(WorkOrderConflict)
        .filter(WorkOrderConflict.status == 'pending')
        .order_by(WorkOrderConflict.id)
        .all()
    )
    # 在待核对列表里顺带给出已有更高版本的情况，页面能区分“已过期差异”。
    superseded = {
        c.id for c in pending
        if best.get(c.order_no) is not None and best[c.order_no].version > c.version
    }
    # 更高版本已生效时，旧版本的同版差异不再影响重建结果，只保留在核对列表，不阻塞发布。
    for c in pending:
        best_event = best.get(c.order_no)
        if best_event is not None and best_event.version > c.version:
            continue
        blockers.append({
            'type': 'work_order_conflict',
            'conflict_id': c.id,
            'order_no': c.order_no,
            'version': c.version,
            'message': f'工单{c.order_no} v{c.version}同版异内容待核对',
        })
    pending_events = s.query(WorkOrderEvent).filter(
        WorkOrderEvent.published_seq.is_(None),
        WorkOrderEvent.status != 'rejected',
    ).count()
    return {
        'target_seq': target,
        'published_seq': published_seq,
        'pending_events': pending_events,
        'differences': differences,
        'counts': dict(counts),
        'blockers': blockers,
        'can_publish': not blockers,
        'work_order_conflicts': [
            {**dump_work_order_conflict(c), 'superseded': c.id in superseded}
            for c in pending
        ],
        'recent_publications': [
            dump_publication(p) for p in
            s.query(DailyPublication).order_by(DailyPublication.id.desc()).limit(5).all()
        ],
    }


def _sync_volume_conflicts(s, blockers):
    current = _volume_conflicts(s)
    created = now_iso()
    for blocker in blockers:
        key = (blocker['branch'], blocker['day'])
        conflict = current.get(key)
        if conflict is None:
            conflict = VolumeConflict(
                branch=blocker['branch'], day=blocker['day'],
                manual_volume=blocker['manual_volume'],
                event_volume=blocker['event_volume'],
                status='open', created=created,
            )
            s.add(conflict)
        else:
            conflict.manual_volume = blocker['manual_volume']
            conflict.event_volume = blocker['event_volume']
            if conflict.status != 'open':
                conflict.status = 'open'
                conflict.manual_volume = blocker['manual_volume']
                conflict.created = created
                conflict.resolved_by = ''
                conflict.resolved_at = ''
    s.flush()


def apply_publication(s, publication, target, implied, cover, effective):
    """把重建结果写入 DailyVolume。发布路径已排除未核对差异。"""
    rows = _volume_rows(s)
    conflicts = _volume_conflicts(s)
    stats = {'created': 0, 'updated': 0, 'zeroed': 0, 'kept_manual': 0, 'unchanged': 0}
    for branch, day in sorted(cover):
        key = (branch, day)
        event_volume = implied.get(key, 0)
        row = rows.get(key)
        if row is None:
            if key not in effective:
                continue
            row = DailyVolume(
                branch=branch, day=day, volume=event_volume,
                note='工单变更流自动重建', source='event',
                publication_id=publication.id, published_event_seq=target,
            )
            s.add(row)
            rows[key] = row
            stats['created'] += 1
            if event_volume == 0:
                stats['zeroed'] += 1
            continue
        conflict = conflicts.get(key)
        if row.source == 'manual':
            if row.volume == event_volume:
                stats['unchanged'] += 1
                continue
            if _is_kept_manual(row, conflict, event_volume):
                stats['kept_manual'] += 1
                continue
            # 采用事件值的核对结论只对当时那一份人工值有效；人工值再变就需要重新核对。
            if not _is_adopted(row, conflict, event_volume):
                raise RuntimeError(f'人工日量未核对：{branch} {day}')
        if row.volume != event_volume:
            stats['updated'] += 1
            if event_volume == 0:
                stats['zeroed'] += 1
        else:
            stats['unchanged'] += 1
        row.volume = event_volume
        row.source = 'event'
        row.publication_id = publication.id
        row.published_event_seq = target
    return stats


def publish(s, actor):
    """在状态行锁内按快照水位全量重建并原子发布。"""
    state = lock_state(s)
    target = state.last_seq or 0
    plan = analyze(s, target)
    if plan['blockers']:
        _sync_volume_conflicts(
            s, [b for b in plan['blockers'] if b['type'] == 'volume_conflict']
        )
        s.commit()
        raise PublishBlocked({
            'message': '存在待核对差异，已阻止发布，未写入任何日量',
            **plan,
        })
    implied, cover, effective, _ = rebuild_rows(s, target)
    publication = DailyPublication(
        published_seq=target, actor=actor.email, state='applied',
        created=now_iso(), stats={},
    )
    try:
        s.add(publication)
        s.flush()
        stats = apply_publication(s, publication, target, implied, cover, effective)
        # 发布后已无差异的待核对记录收口，避免页面显示过期冲突。
        rows = _volume_rows(s)
        for conflict in s.query(VolumeConflict).filter_by(status='open').all():
            row = rows.get((conflict.branch, conflict.day))
            if row is not None and row.volume == implied.get((conflict.branch, conflict.day), 0):
                conflict.status = 'matched'
                conflict.resolved_at = now_iso()
        stats.update({
            'publication_id': publication.id,
            'target_seq': target,
            'actor': actor.email,
            'created_at': publication.created,
        })
        publication.stats = stats
        # 本次发布覆盖到的日志（含已拒绝/已过期差异）一并记为已处理；
        # 仍在阻塞的待核对事件不可能走到这里。
        for event in s.query(WorkOrderEvent).filter(
            WorkOrderEvent.id <= target, WorkOrderEvent.published_seq.is_(None)
        ).all():
            event.published_seq = target
        state.published_seq = max(state.published_seq or 0, target)
        s.commit()
    except Exception:
        s.rollback()
        raise HTTPException(500, '日量发布失败，本次未生效')
    return stats


def stream_summary(s):
    state = s.get(EventStreamState, 1)
    plan = analyze(s)
    last = (state.last_seq or 0) if state else 0
    published = (state.published_seq or 0) if state else 0
    pending_applied = s.query(WorkOrderEvent).filter(
        WorkOrderEvent.published_seq.is_(None), WorkOrderEvent.status == 'applied'
    ).count()
    pending_notice = s.query(WorkOrderEvent).filter(
        WorkOrderEvent.published_seq.is_(None), WorkOrderEvent.status == 'conflict'
    ).count()
    last_publication = (
        s.query(DailyPublication).order_by(DailyPublication.id.desc()).first()
    )
    return {
        'last_seq': last,
        'published_seq': published,
        'pending_events': pending_applied + pending_notice,
        'pending_applied_events': pending_applied,
        'pending_notice': pending_notice,
        'last_publication_id': last_publication.id if last_publication else None,
        'last_published_at': last_publication.created if last_publication else None,
        'pending_work_order_conflicts': len(plan['work_order_conflicts']),
        'open_volume_conflicts': len([
            d for d in plan['differences'] if d['kind'] == 'manual_conflict'
        ]),
        'can_publish': plan['can_publish'],
        'blockers': plan['blockers'],
    }


def dump_row(row):
    return {c.name: getattr(row, c.name) for c in row.__table__.columns}


def dump_work_order_conflict(conflict):
    return {
        'id': conflict.id,
        'order_no': conflict.order_no,
        'version': conflict.version,
        'existing_event_id': conflict.existing_event_id,
        'incoming_event_id': conflict.incoming_event_id,
        'existing_content': conflict.existing_content,
        'incoming_content': conflict.incoming_content,
        'status': conflict.status,
        'note': conflict.note,
        'created': conflict.created,
        'resolved_by': conflict.resolved_by,
        'resolved_at': conflict.resolved_at,
    }


def dump_publication(publication):
    return {
        'id': publication.id,
        'published_seq': publication.published_seq,
        'actor': publication.actor,
        'state': publication.state,
        'created': publication.created,
        'stats': publication.stats,
    }


def resolve_work_order_conflict(s, conflict, action, note, actor):
    lock_state(s)
    if conflict.status != 'pending':
        raise HTTPException(409, '该工单差异已核对，不能重复处理')
    if action not in ('adopt_incoming', 'keep_existing'):
        raise HTTPException(422, '工单差异只能采用新内容或保留原内容')
    incoming = s.get(WorkOrderEvent, conflict.incoming_event_id)
    if not incoming:
        raise HTTPException(409, '隔离事件已不可用，请重新投递')
    if action == 'adopt_incoming':
        existing = s.get(WorkOrderEvent, conflict.existing_event_id)
        if existing and existing.status == 'applied':
            existing.status = 'rejected'
            existing.note = ((existing.note or '') + ' / 核对后由同版新内容替换').strip(' /')
        incoming.status = 'applied'
        # 只有可能改变重建结果的采用才需要重新发布；更高版本已生效时只是归档。
        higher = (
            s.query(WorkOrderEvent)
            .filter(
                WorkOrderEvent.order_no == conflict.order_no,
                WorkOrderEvent.version > conflict.version,
                WorkOrderEvent.status == 'applied',
            )
            .first()
        )
        if higher is None:
            incoming.published_seq = None
        conflict.status = 'adopted'
        message = '已采用隔离事件，归属按最高版本重算'
    else:
        incoming.status = 'rejected'
        conflict.status = 'rejected'
        message = '已保留原事件，隔离事件未生效'
    if note:
        conflict.note = note
    conflict.resolved_by = actor.email
    conflict.resolved_at = now_iso()
    row = _refresh_work_order(s, conflict.order_no)
    s.commit()
    return {
        'status': conflict.status,
        'message': message,
        'work_order': {
            'order_no': row.order_no, 'version': row.version, 'branch': row.branch,
            'accepted_date': row.accepted_date, 'cancelled': row.cancelled,
        } if row else None,
    }


def resolve_volume_conflict(s, branch, day, action, note, actor):
    if action not in ('adopt_event', 'keep_manual'):
        raise HTTPException(422, '日量差异只能采用事件结果或保留人工值')
    lock_state(s)
    implied, _, _, _ = rebuild_rows(s)
    event_volume = implied.get((branch, day), 0)
    row = s.query(DailyVolume).filter_by(branch=branch, day=day).first()
    if row is None or row.source != 'manual':
        raise HTTPException(409, '该网点日期没有人工日量可供核对')
    if row.volume == event_volume:
        raise HTTPException(409, '人工日量与事件重建已一致，无需核对')
    conflict = s.query(VolumeConflict).filter_by(branch=branch, day=day).first()
    if conflict is None:
        conflict = VolumeConflict(branch=branch, day=day, status='open', created=now_iso())
        s.add(conflict)
        s.flush()
    elif conflict.status in ('adopted', 'manual_kept'):
        # 若人工值或事件值已变化，上一轮核对结论失效，需要重新核对。
        if conflict.manual_volume != row.volume or conflict.event_volume != event_volume:
            conflict.status = 'open'
            conflict.resolved_by = ''
            conflict.resolved_at = ''
    if conflict.status != 'open':
        raise HTTPException(409, '该日量差异已核对，不能重复处理')
    # 先落 manual_kept/adopted 状态，保证发布时能看到核对结论。
    conflict.manual_volume = row.volume
    conflict.event_volume = event_volume
    conflict.status = 'manual_kept' if action == 'keep_manual' else 'adopted'
    s.flush()
    if note:
        conflict.note = note
    conflict.resolved_by = actor.email
    conflict.resolved_at = now_iso()
    s.commit()
    return {
        'status': conflict.status,
        'message': '已保留人工值，后续发布跳过该网点日期' if action == 'keep_manual'
        else '已采用事件重建值，下次发布生效',
        'branch': branch,
        'day': day,
        'manual_volume': conflict.manual_volume,
        'event_volume': event_volume,
    }


def has_event_coverage(s, branch, day):
    implied, cover, _, _ = rebuild_rows(s)
    return (branch, day) in cover, implied.get((branch, day), 0)
