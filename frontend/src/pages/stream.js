import {esc,num} from '../utils/html.js';
import {table} from '../components/common/table.js';
import {badge} from '../components/common/status.js';
import {BRANCHES} from '../constants/enums.js';

const KIND = {
  new: '新增事件日',
  new_zero: '新增零量日',
  zeroed: '冲减为0',
  changed: '事件值变化',
  manual_conflict: '人工/事件冲突',
  manual_kept: '保留人工值',
  adopted_event: '已核对采用事件',
};

export function streamSummary(state) {
  return `<div class="stream"><div><strong>${esc(state.last_seq)}</strong>已接收事件水位<p>发布水位 ${esc(state.published_seq)} · 待发布事件 ${esc(state.pending_events)}</p></div><div><strong>${esc(state.pending_work_order_conflicts)}</strong>工单差异待核对<p>${esc(state.open_volume_conflicts)} 个人工/事件日量冲突</p></div><div><strong>${esc(state.last_publication_id ?? '—')}</strong>最近发布号<p>${esc(state.last_published_at ?? '尚未发布')}</p></div><div>${badge(state.can_publish ? '可发布' : '发布已阻止')}</div></div>`;
}

export function diffTable(differences) {
  return table(['日期','网点','事件重建','现行日量','来源','差异类型','核对'],[...differences].reverse().map(d => [
    d.day,
    d.branch,
    d.event_volume,
    num(d.current_volume),
    d.source === 'event' ? '事件发布' : d.source === 'manual' ? '人工日结' : '未生效',
    KIND[d.kind] || d.kind,
    d.conflict_status || '—',
  ]));
}

function volumeActions(differences) {
  const open = differences.filter(d => d.kind === 'manual_conflict');
  if (!open.length) return '<p class="muted">没有待核对的网点日期。</p>';
  return open.map(d => `<article class="rec"><h3>${esc(d.branch)} · ${esc(d.day)} ${badge('待核对')}</h3>
    <p>人工日量 <strong>${esc(d.current_volume)}</strong> / 事件重建 <strong>${esc(d.event_volume)}</strong>。核对前发布会一直中止。</p>
    <label>核对说明<textarea name="note-vol-${esc(d.branch)}-${esc(d.day)}" rows="2"></textarea></label>
    <div class="actions"><button data-vol-adopt="${esc(d.branch)}|${esc(d.day)}">采用事件值</button><button data-vol-keep="${esc(d.branch)}|${esc(d.day)}">保留人工值</button></div></article>`).join('');
}

function workOrderConflicts(workOrders) {
  if (!workOrders.length) return '<p class="muted">暂无同版异内容工单。</p>';
  return workOrders.map(c => `<article class="rec"><h3>工单 ${esc(c.order_no)} · v${esc(c.version)} ${badge(c.status)} ${c.superseded ? badge('已有更高版本，不阻塞发布') : ''}</h3>
    <div class="compare"><div><p class="eyebrow">已采用</p><pre>${esc(JSON.stringify(c.existing_content))}</pre></div><div><p class="eyebrow">隔离待核对</p><pre>${esc(JSON.stringify(c.incoming_content))}</pre></div></div>
    ${c.status === 'pending' ? `<label>核对说明<textarea name="note-wo-${esc(c.id)}" rows="2"></textarea></label>
    <div class="actions"><button data-wo-adopt="${esc(c.id)}">采用隔离内容</button><button data-wo-keep="${esc(c.id)}">保留原内容</button></div>` : `<p class="muted">${esc(c.resolved_by)} · ${esc(c.resolved_at)}</p>`}</article>`).join('');
}

export function eventForm() {
  return `<aside class="side"><h2>送入工单事件</h2><form id="event">
    <label>投递ID（可选，用于幂等）<input name="delivery_id" placeholder="delivery-001"></label>
    <label>工单号<input name="order_no" required value="WO-20261116-001"></label>
    <label>版本<input name="version" type="number" min="1" required value="1"></label>
    <label>受理日<input name="accepted_date" type="date" required value="2026-11-15"></label>
    <label>归属网点<select name="branch">${BRANCHES.map(b => `<option value="${esc(b)}">${esc(b)}</option>`).join('')}</select></label>
    <label class="check"><input name="cancelled" type="checkbox"> 撤销该工单</label>
    <label>备注<input name="note" maxlength="500"></label>
    <button class="primary">接收事件</button>
    <p class="muted">批量可改用 POST /events 的 events 数组。</p>
  </form></aside>`;
}

export function render(state) {
  const s = state.stream || {differences: [], work_order_conflicts: [], recent_publications: []};
  return `<div class="split"><section class="panel"><div class="result-head"><h2>工单变更流</h2><span class="tag">事件接收 → 归属更新 → 日量发布</span></div>
    ${streamSummary(s)}
    <p class="notice">每条事件带工单号、版本、受理日、归属网点与撤销标记。重建按每单最高版本进行：转派冲减原网点，撤销归零；迟到旧版只记录不回退。重复投递与全量重跑不产生增量。接收与发布在同一事务内完成，异常不会留下半成品。</p>
    <div class="actions"><button id="publish-stream" class="primary">发布已接收事件</button><button id="refresh-stream">刷新差异</button><button id="replay-stream">按当前日志重放核对</button></div>
    <h3>事件与现行日量差异 / ${s.differences.length} 条</h3>
    <p class="muted">“保留人工值”的网点日期在后续发布中跳过；人工值与事件值再次变化时核对结论失效，需要重新核对。</p>
    ${diffTable(s.differences)}
    <h3>人工日量核对 / ${(s.differences||[]).filter(d=>d.kind==='manual_conflict').length} 项待核对</h3>
    ${volumeActions(s.differences)}
    <h3>同版异内容隔离区</h3>
    ${workOrderConflicts(s.work_order_conflicts)}
    <h3>最近发布</h3>
    ${table(['发布号','事件水位','操作人','时间','新建','更新','冲减','保留人工'],[...(s.recent_publications||[])].map(p => [p.id, p.published_seq, p.actor, p.created, p.stats?.created ?? 0, p.stats?.updated ?? 0, p.stats?.zeroed ?? 0, p.stats?.kept_manual ?? 0]))}
  </section>${eventForm()}</div>`;
}
