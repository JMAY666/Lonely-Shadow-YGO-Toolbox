'use strict';
// All saved-deck surfaces consume the same selection and vocabulary returned
// by the deck API. This view owns neither a second selection nor tag names.
function deckTagHtml(saved) {
  const ids = saved?.tag_selection?.tag_ids || [], primary = saved?.tag_selection?.primary_ids || [];
  return `<span class="shared-deck-tags">${saved?.tag_error ? escape(saved.tag_error) : ids.length ? ids.map(id => `<span class="deck-tag-chip ${primary.includes(id) ? 'primary' : 'secondary'}" data-tag-id="${escape(id)}">${primary.includes(id) ? '主' : '副'} · ${escape(saved.tag_names?.[id] || '未安装 TAG')}</span>`).join('') : '<small>尚未设置 Tag</small>'}</span>`;
}
