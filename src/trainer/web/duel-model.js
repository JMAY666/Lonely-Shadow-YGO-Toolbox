(function(root) {
  'use strict';
  const counts = list => {const result = new Map(); for (const code of list) result.set(code, (result.get(code) || 0) + 1); return result;};
  function handError(deck, count, hand) {
    if (!Number.isInteger(count) || count < 1 || count > (deck?.main?.length || 0)) return '起手张数必须是正整数，且不能超过主卡组总张数';
    const selected = hand.filter(code => code !== null), pool = counts(deck.main);
    if (selected.some(code => !Number.isInteger(code) || !pool.has(code))) return '起手只能选择当前主卡组中的卡牌';
    if ([...counts(selected)].some(([code,n]) => n > pool.get(code))) return '同名卡超过主卡组实际投入数量';
    if (hand.length > count || selected.length > count) return '已超出本次起手张数';
    if (selected.length < count) return `还需选择 ${count - selected.length} 张卡牌`;
    return '';
  }
  function place(deck, count, hand, code, target = hand.indexOf(null)) {
    if (target < 0 || target >= count || !Number.isInteger(code) || !deck.main.includes(code)) return null;
    const next = hand.slice(); next[target] = code;
    if ((counts(next).get(code) || 0) > (counts(deck.main).get(code) || 0)) return null;
    return next;
  }
  function graph(routes) {
    const nodes = [], edges = [], byId = new Map();
    const add = (route, step, column, row) => {
      const node = {...step, key: route.id + '/' + step.id, route: route.id, label: route.label, column, row};
      nodes.push(node); byId.set(node.key, node); return node;
    };
    routes.forEach((route, row) => {
      const anchor = row ? byId.get('main/' + route.source.node_id) : null;
      if (row && !anchor) return;
      const steps = [...(!row ? [{id:'initial',number:0,title:'起手 / 分叉入口'}] : []), ...route.model.steps,
        {id:'final',number:null,title:row ? '妥协终场' : '主线终场'}];
      let previous = anchor;
      steps.forEach((step, index) => {
        const node = add(route, step, (anchor ? anchor.column + 1 : 0) + index, row);
        if (previous) edges.push({from:previous.key,to:node.key,branch:!!anchor && index === 0,
          label:anchor && index === 0 ? `${route.label} · ${route.source.timing || '分叉'}` : route.label});
        previous = node;
      });
    });
    return {nodes,edges,start:nodes.find(n => n.route === 'main' && n.id !== 'initial')?.key || nodes[0]?.key};
  }
  function navigate(graph, position, action) {
    const next = {...position}, outgoing = graph.edges.filter(e => e.from === position.key);
    if (action === 'up' || action === 'down') {
      next.choice = outgoing.length ? ((position.choice || 0) + (action === 'down' ? 1 : -1) + outgoing.length) % outgoing.length : 0;
    } else if (action === 'forward' && outgoing.length) {
      next.key = outgoing[(position.choice || 0) % outgoing.length].to; next.choice = 0;
    } else if (action === 'back') {
      const edge = graph.edges.find(e => e.to === position.key);
      if (edge) {next.key = edge.from; next.choice = graph.edges.filter(e => e.from === edge.from).findIndex(e => e.to === position.key);}
    }
    return next;
  }
  const model = {counts,handError,place,graph,navigate};
  if (typeof module !== 'undefined') module.exports = model;
  else root.DuelModel = model;
})(globalThis);
