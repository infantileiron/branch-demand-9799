import json
from datetime import date

import pytest

DAY = '2026-11-15'


def send(client, headers, events):
    r = client.post('/events', json={'events': events}, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def event(order_no, version=1, branch='川北', day=DAY, cancelled=False, delivery_id=None, note=''):
    row = {
        'order_no': order_no,
        'version': version,
        'accepted_date': day,
        'branch': branch,
        'cancelled': cancelled,
        'note': note,
    }
    if delivery_id:
        row['delivery_id'] = delivery_id
    return row


def publish(client, headers):
    return client.post('/stream/publish', json={}, headers=headers)


def volumes(client, headers):
    return {(v['branch'], v['day']): v for v in client.get('/volumes', headers=headers).json()}


def test_event_validation_and_permissions(client, tokens):
    assert client.post('/events', json={'events': [event('X', branch='不存在')]}, headers=tokens['analyst']).status_code == 422
    assert client.post('/events', json={'events': [event('X', version=0)]}, headers=tokens['analyst']).status_code == 422
    bad = event('X')
    bad['extra'] = 1
    assert client.post('/events', json={'events': [bad]}, headers=tokens['analyst']).status_code == 422
    assert client.post('/events', json={'events': []}, headers=tokens['analyst']).status_code == 422
    assert client.post('/events', json={'events': [event('X')]}, headers=tokens['viewer']).status_code == 403
    assert client.post('/stream/publish', json={}, headers=tokens['viewer']).status_code == 403


def test_out_of_order_transfer_rebuilds_highest_version(client, tokens):
    h = tokens['analyst']
    send(client, h, [event('WO-A', version=2, branch='川南')])
    assert publish(client, h).json()['publication']['created'] == 1
    assert volumes(client, h)[('川南', DAY)]['volume'] == 1

    result = send(client, h, [event('WO-A', version=1, branch='川北')])['results'][0]
    assert result['status'] == 'applied'
    assert '不回退' in result['message']
    work_orders = client.get('/stream', headers=h).json()
    assert work_orders['last_seq'] == 2

    # 迟到旧版不改变归属：重发不新增日量。
    pub = publish(client, h).json()['publication']
    assert pub['created'] == 0
    after = volumes(client, h)
    assert ('川北', DAY) not in after
    assert after[('川南', DAY)]['volume'] == 1


def test_transfer_deducts_origin_and_cancel_zeroes(client, tokens):
    h = tokens['analyst']
    send(client, h, [event('WO-1'), event('WO-2')])
    assert publish(client, h).status_code == 200
    assert volumes(client, h)[('川北', DAY)]['volume'] == 2

    send(client, h, [event('WO-1', version=2, branch='川南')])
    pub = publish(client, h).json()['publication']
    assert pub['created'] == 1  # 川南新出现
    assert pub['updated'] == 1  # 川北 2→1，原网点被冲减
    after = volumes(client, h)
    assert after[('川北', DAY)]['volume'] == 1
    assert after[('川南', DAY)]['volume'] == 1

    send(client, h, [event('WO-2', version=2, cancelled=True)])
    pub = publish(client, h).json()['publication']
    assert pub['zeroed'] == 1
    after = volumes(client, h)
    assert after[('川北', DAY)]['volume'] == 0
    assert after[('川北', DAY)]['source'] == 'event'


def test_duplicate_delivery_does_not_increment(client, tokens):
    h = tokens['analyst']
    first = send(client, h, [event('WO-1', delivery_id='d-1')])
    assert first['counts'] == {'applied': 1}
    seq = first['stream']['last_seq']
    again = send(client, h, [event('WO-1', delivery_id='d-1')])
    assert again['counts'] == {'duplicate': 1}
    assert again['stream']['last_seq'] == seq
    same_content = send(client, h, [event('WO-1')])
    assert same_content['counts'] == {'duplicate': 1}
    publish(client, h)
    assert volumes(client, h)[('川北', DAY)]['volume'] == 1


def test_same_version_different_content_is_quarantined(client, tokens):
    h = tokens['analyst']
    send(client, h, [event('WO-1', branch='川北')])
    conflict = send(client, h, [event('WO-1', branch='西浦')])['results'][0]
    assert conflict['status'] == 'conflict'
    assert client.get('/stream/differences', headers=h).json()['can_publish'] is False

    blocked = publish(client, h)
    assert blocked.status_code == 409
    assert blocked.json()['detail']['blockers'][0]['type'] == 'work_order_conflict'
    # 被阻止的发布不写入半成品。
    assert ('西浦', DAY) not in volumes(client, h)

    conflicts = client.get('/conflicts', headers=h).json()
    assert conflicts['work_orders'][0]['status'] == 'pending'
    wid = conflicts['work_orders'][0]['id']
    assert client.post(f'/conflicts/work-orders/{wid}/resolve', json={'action': 'adopt_incoming'}, headers=h).status_code == 200
    assert client.post(f'/conflicts/work-orders/{wid}/resolve', json={'action': 'adopt_incoming'}, headers=h).status_code == 409

    assert publish(client, h).status_code == 200
    after = volumes(client, h)
    assert after[('西浦', DAY)]['volume'] == 1
    # 原归属从未发布过，因此不产生幽灵零量行。
    assert ('川北', DAY) not in after


def test_same_version_conflict_keep_existing(client, tokens):
    h = tokens['analyst']
    send(client, h, [event('WO-1', branch='川北')])
    send(client, h, [event('WO-1', branch='西浦')])
    wid = client.get('/conflicts', headers=h).json()['work_orders'][0]['id']
    r = client.post(f'/conflicts/work-orders/{wid}/resolve', json={'action': 'keep_existing', 'note': '原记录可信'}, headers=h)
    assert r.json()['status'] == 'rejected'
    assert publish(client, h).status_code == 200
    after = volumes(client, h)
    assert after[('川北', DAY)]['volume'] == 1
    assert ('西浦', DAY) not in after


def test_manual_volume_conflict_blocks_then_resolution(client, tokens):
    h = tokens['analyst']
    r = client.post('/volumes', json={'branch': '临港', 'day': DAY, 'volume': 7, 'note': '人工日结'}, headers=h)
    assert r.status_code == 200
    send(client, h, [event('WO-9', branch='临港')])
    blocked = publish(client, h)
    assert blocked.status_code == 409
    assert [b['type'] for b in blocked.json()['detail']['blockers']] == ['volume_conflict']
    # 人工值在核对前保持原样，事件不发布。
    assert volumes(client, h)[('临港', DAY)]['volume'] == 7

    kept = client.post(f'/conflicts/volumes/临港/{DAY}/resolve', json={'action': 'keep_manual'}, headers=h)
    assert kept.json()['status'] == 'manual_kept'
    pub = publish(client, h).json()['publication']
    assert pub['kept_manual'] == 1
    assert volumes(client, h)[('临港', DAY)]['volume'] == 7
    assert client.post(f'/conflicts/volumes/临港/{DAY}/resolve', json={'action': 'keep_manual'}, headers=h).status_code == 409


def test_manual_conflict_adopt_event(client, tokens):
    h = tokens['analyst']
    client.post('/volumes', json={'branch': '临港', 'day': DAY, 'volume': 7, 'note': '人工日结'}, headers=h)
    send(client, h, [event('WO-9', branch='临港')])
    assert publish(client, h).status_code == 409
    r = client.post(f'/conflicts/volumes/临港/{DAY}/resolve', json={'action': 'adopt_event'}, headers=h)
    assert r.json()['status'] == 'adopted'
    assert publish(client, h).status_code == 200
    assert volumes(client, h)[('临港', DAY)]['volume'] == 1


def test_full_replay_is_idempotent(client, tokens):
    h = tokens['analyst']
    send(client, h, [event('WO-1'), event('WO-2', branch='川南'), event('WO-3', branch='西浦')])
    assert publish(client, h).status_code == 200
    before = {k: v['volume'] for k, v in volumes(client, h).items()}
    for _ in range(3):
        assert publish(client, h).status_code == 200
    after = {k: v['volume'] for k, v in volumes(client, h).items()}
    assert before == after
    stream = client.get('/stream', headers=h).json()
    assert stream['can_publish'] is True
    assert stream['pending_events'] == 0


def test_forecast_snapshot_only_uses_effective_volumes(client, tokens):
    h = tokens['analyst']
    # 事件“处理中”（未发布）不应进入预测提交的快照。
    send(client, h, [event('WO-1', day='2026-11-15')])
    r = client.post('/runs', json={'name': '事件未发布快照', 'branch': '川北', 'backtest_days': 14, 'alpha': 0.6, 'beta': 0.2}, headers=h)
    assert r.status_code == 200
    snapshot = r.json()['result']['snapshot']
    assert all(row['day'] != '2026-11-15' for row in snapshot)
    assert r.json()['result']['snapshot_meta']['published_seq'] == 0

    publish(client, h)
    r2 = client.post('/runs', json={'name': '事件已发布快照', 'branch': '川北', 'backtest_days': 14, 'alpha': 0.6, 'beta': 0.2}, headers=h)
    assert r2.status_code == 200
    assert r2.json()['result']['snapshot_meta']['published_seq'] == 1
    # 旧预测历史保留其冻结快照，不因后续发布而改变。
    assert r.json()['result']['snapshot'] != r2.json()['result']['snapshot']


def test_forecast_run_keeps_history_after_late_volume(client, tokens, session):
    h = tokens['analyst']
    r = client.post('/runs', json={'name': '冻结版本', 'branch': '川南', 'backtest_days': 14, 'alpha': 0.6, 'beta': 0.2}, headers=h)
    run_id = r.json()['id']
    frozen = r.json()['result']['snapshot']
    client.post('/volumes', json={'branch': '川南', 'day': '2026-11-15', 'volume': 42, 'note': '补录'}, headers=h)
    detail = client.get(f'/runs/{run_id}', headers=h).json()
    assert detail['result']['snapshot'] == frozen
    assert len(detail['result']['snapshot']) == len(frozen)


def test_publish_failure_leaves_no_partial_state(client, tokens, monkeypatch):
    from src.services import events as event_service
    from src.config.database import Session
    from src.models.entities import DailyVolume, DailyPublication

    h = tokens['analyst']
    send(client, h, [event('WO-1'), event('WO-2', branch='川南')])
    before = {k: v['volume'] for k, v in volumes(client, h).items()}

    original = event_service.apply_publication
    calls = {'n': 0}

    def boom(s, publication, target, implied, cover, effective):
        # 先写一部分，再失败，验证整体回退。
        for i, (branch, day) in enumerate(sorted(cover)):
            s.add(DailyVolume(branch=branch, day=day, volume=999, note='半成品', source='event'))
            s.flush()
            calls['n'] += 1
            break
        raise RuntimeError('模拟写入中断')

    monkeypatch.setattr(event_service, 'apply_publication', boom)
    r = publish(client, h)
    assert r.status_code == 500
    monkeypatch.setattr(event_service, 'apply_publication', original)

    after = {k: v['volume'] for k, v in volumes(client, h).items()}
    assert after == before
    with Session() as s:
        assert s.query(DailyPublication).count() == 0
    stream = client.get('/stream', headers=h).json()
    assert stream['published_seq'] == 0
    assert stream['pending_events'] == 2
    # 恢复后可以正常发布。
    assert publish(client, h).status_code == 200
    assert volumes(client, h)[('川南', '2026-11-15')]['volume'] == 1


def test_receipt_failure_rolls_back_whole_batch(client, tokens, monkeypatch):
    from src.services import events as event_service

    h = tokens['analyst']
    original = event_service._ingest_one
    calls = {'n': 0}

    def flaky(s, item, actor, state):
        calls['n'] += 1
        if calls['n'] == 3:
            raise RuntimeError('模拟中途失败')
        return original(s, item, actor, state)

    monkeypatch.setattr(event_service, '_ingest_one', flaky)
    r = client.post('/events', json={'events': [event('WO-1'), event('WO-2'), event('WO-3')]}, headers=h)
    assert r.status_code == 500
    monkeypatch.setattr(event_service, '_ingest_one', original)
    stream = client.get('/stream', headers=h).json()
    assert stream['last_seq'] == 0
    assert stream['pending_events'] == 0
    assert client.get('/events', headers=h).json() == []


def test_late_event_after_publish_requires_new_publication(client, tokens):
    h = tokens['analyst']
    send(client, h, [event('WO-1')])
    publish(client, h)
    assert client.get('/stream', headers=h).json()['pending_events'] == 0
    send(client, h, [event('WO-2')])
    stream = client.get('/stream', headers=h).json()
    assert stream['pending_events'] == 1
    assert volumes(client, h)[('川北', DAY)]['volume'] == 1
    publish(client, h)
    assert volumes(client, h)[('川北', DAY)]['volume'] == 2


def test_accepted_date_change_moves_count(client, tokens):
    h = tokens['analyst']
    send(client, h, [event('WO-1', day='2026-11-15'), event('WO-2', day='2026-11-15')])
    publish(client, h)
    send(client, h, [event('WO-1', version=2, day='2026-11-16')])
    publish(client, h)
    after = volumes(client, h)
    assert after[('川北', '2026-11-15')]['volume'] == 1
    assert after[('川北', '2026-11-16')]['volume'] == 1


def test_manual_edit_after_adoption_requires_new_review(client, tokens):
    h = tokens['analyst']
    client.post('/volumes', json={'branch': '临港', 'day': DAY, 'volume': 7}, headers=h)
    send(client, h, [event('WO-9', branch='临港')])
    assert publish(client, h).status_code == 409
    client.post(f'/conflicts/volumes/临港/{DAY}/resolve', json={'action': 'adopt_event'}, headers=h)
    # 核对后人工又改了一个新值：旧结论失效，发布必须重新阻止。
    edited = client.get('/volumes', headers=h).json()
    vid = [v['id'] for v in edited if v['branch'] == '临港' and v['day'] == DAY][0]
    client.put(f'/volumes/{vid}', json={'branch': '临港', 'day': DAY, 'volume': 11, 'note': '再改'}, headers=h)
    blocked = publish(client, h)
    assert blocked.status_code == 409
    assert blocked.json()['detail']['blockers'][0]['type'] == 'volume_conflict'
    assert volumes(client, h)[('临港', DAY)]['volume'] == 11
    assert client.post(f'/conflicts/volumes/临港/{DAY}/resolve', json={'action': 'keep_manual'}, headers=h).status_code == 200
    assert publish(client, h).json()['publication']['kept_manual'] == 1
    assert volumes(client, h)[('临港', DAY)]['volume'] == 11


def test_manual_revision_of_event_volume_needs_review(client, tokens):
    h = tokens['analyst']
    send(client, h, [event('WO-1')])
    publish(client, h)
    row = volumes(client, h)[('川北', DAY)]
    assert row['source'] == 'event'
    r = client.put(f"/volumes/{row['id']}", json={'branch': '川北', 'day': DAY, 'volume': 5, 'note': '现场修订'}, headers=h)
    assert r.status_code == 200
    assert r.json()['source'] == 'manual'
    assert r.json()['event_notice']['event_volume'] == 1
    blocked = publish(client, h)
    assert blocked.status_code == 409
    assert volumes(client, h)[('川北', DAY)]['volume'] == 5


def test_conflict_rejected_does_not_stay_pending(client, tokens):
    h = tokens['analyst']
    send(client, h, [event('WO-1', branch='川北')])
    send(client, h, [event('WO-1', branch='西浦')])
    wid = client.get('/conflicts', headers=h).json()['work_orders'][0]['id']
    client.post(f'/conflicts/work-orders/{wid}/resolve', json={'action': 'keep_existing'}, headers=h)
    publish(client, h)
    stream = client.get('/stream', headers=h).json()
    assert stream['pending_events'] == 0
    assert stream['pending_work_order_conflicts'] == 0


def test_superseded_version_conflict_does_not_block(client, tokens):
    h = tokens['analyst']
    send(client, h, [event('WO-1', branch='川北')])
    send(client, h, [event('WO-1', branch='西浦')])          # v1 同版差异
    send(client, h, [event('WO-1', version=3, branch='东河')])  # 更高版本已生效
    plan = client.get('/stream/differences', headers=h).json()
    assert plan['can_publish'] is True
    assert plan['work_order_conflicts'][0]['status'] == 'pending'  # 仍留待查
    assert publish(client, h).status_code == 200
    after = volumes(client, h)
    assert after[('东河', DAY)]['volume'] == 1
    assert ('川北', DAY) not in after and ('西浦', DAY) not in after


def test_pending_watermarks_clear_after_publish(client, tokens):
    h = tokens['analyst']
    send(client, h, [event('WO-1'), event('WO-1', branch='西浦')])
    publish(client, h)          # 有冲突，应被阻止
    assert client.get('/stream', headers=h).json()['pending_events'] == 2
    wid = client.get('/conflicts', headers=h).json()['work_orders'][0]['id']
    client.post(f'/conflicts/work-orders/{wid}/resolve', json={'action': 'keep_existing'}, headers=h)
    publish(client, h)
    stream = client.get('/stream', headers=h).json()
    assert stream['pending_events'] == 0
    assert stream['last_seq'] == stream['published_seq'] == 2


def test_manual_edit_then_transfer_away_still_needs_review(client, tokens):
    h = tokens['analyst']
    send(client, h, [event('WO-1', branch='川北')])
    publish(client, h)
    row = volumes(client, h)[('川北', DAY)]
    client.put(f"/volumes/{row['id']}", json={'branch': '川北', 'day': DAY, 'volume': 40, 'note': '现场修订'}, headers=h)
    send(client, h, [event('WO-1', version=2, branch='川南')])
    blocked = publish(client, h)
    assert blocked.status_code == 409
    blocker = [b for b in blocked.json()['detail']['blockers'] if b['type'] == 'volume_conflict'][0]
    assert blocker['branch'] == '川北' and blocker['event_volume'] == 0
    assert volumes(client, h)[('川北', DAY)]['volume'] == 40


def test_volume_resolution_validates_branch_and_day(client, tokens):
    h = tokens['analyst']
    assert client.post('/conflicts/volumes/火星/2026-11-15/resolve', json={'action': 'keep_manual'}, headers=h).status_code == 422
    assert client.post('/conflicts/volumes/川北/not-a-day/resolve', json={'action': 'keep_manual'}, headers=h).status_code == 422
    assert client.post('/conflicts/volumes/川北/2026-11-15/resolve', json={'action': 'nope'}, headers=h).status_code == 422
