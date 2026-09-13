'use strict';

function renderTrainingReport(r, options) {
  const id = r.id;
  const eventById = new Map(r.events.map(e => [e.id, e]));
  const groups = new Map();
  for (const a of r.actions) {
    if (a.chain_group) groups.set(a.chain_group, (groups.get(a.chain_group) || 0) + 1);
  }
  const list = options.raw ? r.events : r.actions;
  const timeline = list.map((a, index) => {
    if (options.raw) {
      return `<li id="event-${a.id}"><span class="ref">${a.id}</span>
        <span class="action-title">${escape(a.type)}</span><p>${escape(eventSummary(a))}</p>
        <details><summary>原始事件</summary><pre>${escape(JSON.stringify(a, null, 2))}</pre></details></li>`;
    }
    const events = a.evidence_refs.map(ref => eventById.get(ref)).filter(Boolean)
      .sort((x, y) => x.native_seq - y.native_seq || x.byte_offset - y.byte_offset);
    const chain = groups.get(a.chain_group) > 1
      ? `<p class="chain-order">第 ${a.chain_group} 组连锁 · 连锁 ${a.chain_link} · ${a.resolution_order ? `第 ${[...r.actions].filter(x => x.chain_group === a.chain_group && x.resolution_order && x.resolution_order < a.resolution_order).length + 1} 个结算` : '尚未结算'}</p>` : '';
    const execution = a.execution || [];
    return `<li id="action-${a.id}"><span class="ref">${String(index + 1).padStart(2, '0')} · +${Math.max(0, Math.floor((a.time_ms - r.started_ms) / 1000))}s</span>
      ${a.kind === 'effect' ? `<span class="action-title">发动${escape(a.cards?.map(c => c.name).filter(Boolean).join('、') || '卡片')}的效果</span><div class="effect-description"><small>效果文本</small><p class="effect-quote">${escape(a.effect_text || '本次记录未保存效果文本。')}</p></div>` : `<span class="action-title">${escape(a.summary)}</span>`}${chain}
      ${a.status_label ? `<p class="action-status">${escape(a.status_label)}</p>` : ''}
      ${execution.length ? `<div class="actual-execution"><small>实际结果</small><ol>${execution.map(step => `<li><span class="execution-role">${step.role === 'cost' ? '费用' : '处理'}</span>${highlightCardNames(step.text.replace(/^支付费用：/, ''), step.cards)}${step.message === 90 ? `<p>抽到：${highlightCardNames(step.cards.map(c => c.name).join('、'), step.cards)}</p>` : ''}</li>`).join('')}</ol></div>` : ''}
      ${a.observed_targets ? `<p>${escape(a.observed_targets)}</p>` : ''}
      <details><summary>查看依据 · ${events.length} 条原始事件</summary>
        ${a.trigger_summary ? `<p>${escape(a.trigger_summary)}</p>` : ''}
        ${a.association ? `<p>${escape(a.association)}。摘要只描述记录中已发生的结果。</p>` : ''}
        ${events.map(e => `<div class="evidence-event"><b>${e.id} · ${escape(e.type)}</b><p>${escape(eventSummary(e))}</p>
          <details><summary>事件字段</summary><pre>${escape(JSON.stringify(e, null, 2))}</pre></details></div>`).join('')}
      </details></li>`;
  }).join('');
  const own = r.final_state?.cards.filter(c => c.controller === 0) || [];
  const board = ['main_monster', 'extra_monster', 8, 2, 16, 32, 64, 1, 128].map(zone => {
    const cards = own.filter(c => zone === 'main_monster' ? c.location === 4 && c.sequence < 5 : zone === 'extra_monster' ? c.location === 4 && c.sequence >= 5 : c.location === zone).sort((a, b) => a.sequence - b.sequence);
    const monster = ['main_monster','extra_monster'].includes(zone);
    const label = zone === 'main_monster' ? '主怪兽区' : zone === 'extra_monster' ? '额外怪兽区' : zoneNames[zone];
    const images = monster || [8, 2].includes(zone);
    return `<div class="zone-row"><b>${label} <small>${cards.length}</small></b><div>
      ${images ? cardsHtml(cards) : `<p>${cards.length ? cards.map(c => `${escape(c.name)} #${c.instance_id}`).join('、') : '空'}</p>`}
      ${(monster || zone === 8) && cards.length ? `<p>${cards.map(c => `${escape(loc(c))} ${escape(c.name)} · ${positions(c.position)}`).join('<br>')}</p>` : ''}
      </div></div>`;
  }).join('');
  const deck = ['main', 'extra', 'side'].map(zone => `<b>${zoneNames[zone]}（${r.deck[zone].length}）</b><div class="report-deck">
    ${[...new Set(r.deck[zone])].map(c => `${escape(r.catalog[c]?.name || c)} [${c}] × ${r.deck[zone].filter(x => x === c).length}`).join('<br>')}</div>`).join('');
  return `<div class="eyebrow">TRAINING REPORT</div><h2>${escape(r.name)}</h2>
    <p>${dt(r.started_ms)} · ${duration(r.duration_ms)}</p>
    <span class="badge ${r.status === 'interrupted' ? 'warning' : ''}">${statusNames[r.status]}</span>
    <span class="badge ${!r.loaded_verified ? 'warning' : ''}">${r.loaded_verified ? '选定构筑与引擎载入一致' : '尚未确认构筑载入'}</span>
    <p>${escape(reasons[r.end_reason] || r.end_reason || '训练仍在进行')} · 空场占位，无 AI</p>
    ${r.warnings.length ? `<ul class="warnings">${[...new Set(r.warnings)].map(w => `<li>${escape(w)}</li>`).join('')}</ul>` : ''}
    <div class="stats">${Object.entries(r.statistics).map(([key, value]) => `<div class="stat"><strong>${value}</strong><span>${escape(key)}</span></div>`).join('')}</div>
    <small>${escape(r.statistics_note)}</small>
    <h3>初始手牌</h3>${r.initial_hand ? cardsHtml(r.initial_hand) : '<p>尚未采集到初始手牌。</p>'}
    <h3>展开步骤 <small>${r.actions.length} 步</small></h3>
    <p class="summary-hint">上方保留卡片完整效果文本，下方展示本次实际结果。</p>
    <div class="report-toolbar"><label><input type="checkbox" id="all-events" ${options.raw ? 'checked' : ''}>查看原始事件</label>
      <a href="/api/raw/${id}" target="_blank">原始记录 JSONL</a><a href="/api/ydk/${id}" target="_blank">构筑快照 YDK</a></div>
    <ol class="timeline">${timeline || '<li><p>暂无需要复盘的展开动作。</p></li>'}</ol>
    <h3>最终场面与各区域 <small>快照 ${r.final_state_ref || '未知'}</small></h3>
    ${r.final_state ? `<p>回合 ${r.final_state.turn} · 我方 LP ${r.final_state.lp[0]} / 占位方 LP ${r.final_state.lp[1]} · 未结束连锁 ${r.final_state.chain_depth}</p>
      ${board}<details><summary>查看占位方区域与完整状态</summary><pre>${escape(JSON.stringify(r.final_state, null, 2))}</pre></details>` : '<p>未采集到状态。</p>'}
    <details><summary>本次构筑快照 · 主 ${r.deck.main.length} / 额外 ${r.deck.extra.length} / 副 ${r.deck.side.length}</summary>${deck}</details>
    <div class="sources">训练标识：${id}<br>构筑 SHA-256：${r.deck_sha256}<br>
      来源：核心原始消息、cardid 与区域状态；效果文本来自本次构筑快照。<br>${escape(r.legality)}
      <details><summary>记录边界与数据来源</summary>${r.limitations.map(l => escape(l) + '<br>').join('')}${escape(JSON.stringify(r.sources))}</details></div>`;
}

function highlightCardNames(text, cards) {
  const names = [...new Set(cards.map(c => c.name).filter(Boolean))].sort((a,b) => b.length - a.length);
  if (!names.length) return escape(text);
  const regex = new RegExp('(' + names.map(name => name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('|') + ')', 'g');
  return String(text).split(regex).map(part => names.includes(part) ? `<strong>${escape(part)}</strong>` : escape(part)).join('');
}
