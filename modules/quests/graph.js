// Quest dependency / series graph.  Coordinates are computed at build time;
// this element only draws them and adds prefetch on hover/focus.
const NODE_W = 158;
const NODE_H = 56;
let markerId = 0;

function el(tag, className) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  return node;
}

export default class QuestGraph extends HTMLElement {
  connectedCallback() {
    if (this._init) return;
    this._init = true;
    let data;
    try {
      data = JSON.parse(this.getAttribute('notist-data') || '');
    } catch {
      return;
    }
    if (!data?.nodes?.length) return;
    if (data.nodes.length <= 1 && !data.edges?.length) return;

    const byId = new Map();
    for (const node of data.nodes) byId.set(String(node.id), node);

    const wrap = el('div', 'quest-graph-wrap');
    const graph = el('div', 'quest-graph');
    graph.style.setProperty('--graph-w', `${data.width}px`);
    graph.style.setProperty('--graph-h', `${data.height}px`);
    graph.setAttribute('role', 'group');
    graph.setAttribute('aria-label', '任务关系图');

    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('viewBox', `0 0 ${data.width} ${data.height}`);
    svg.setAttribute('aria-hidden', 'true');
    const defs = document.createElementNS('http://www.w3.org/2000/svg', 'defs');
    const id = `quest-arrow-${++markerId}`;
    const marker = document.createElementNS('http://www.w3.org/2000/svg', 'marker');
    marker.setAttribute('id', id);
    marker.setAttribute('viewBox', '0 0 10 10');
    marker.setAttribute('refX', '8');
    marker.setAttribute('refY', '5');
    marker.setAttribute('markerWidth', '6');
    marker.setAttribute('markerHeight', '6');
    marker.setAttribute('orient', 'auto-start-reverse');
    const arrow = document.createElementNS('http://www.w3.org/2000/svg', 'path');
    arrow.setAttribute('d', 'M0 0 10 5 0 10z');
    arrow.setAttribute('fill', '#bdbdbd');
    marker.append(arrow);
    defs.append(marker);
    svg.append(defs);

    const seen = new Set();
    const prefetch = href => {
      if (!href || seen.has(href)) return;
      seen.add(href);
      const link = document.createElement('link');
      link.rel = 'prefetch';
      link.href = href;
      document.head.append(link);
    };

    for (const edge of data.edges || []) {
      const from = byId.get(String(edge[0]));
      const to = byId.get(String(edge[1]));
      if (!from || !to) continue;
      const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
      const sx = from.x + NODE_W / 2;
      const sy = from.y + NODE_H / 2;
      const tx = to.x + NODE_W / 2;
      const ty = to.y + NODE_H / 2;
      if (Math.abs(from.y - to.y) < 1) {
        path.setAttribute('d', `M${from.x + NODE_W} ${sy} H${to.x}`);
      } else {
        const down = to.y > from.y;
        const x1 = sx;
        const y1 = down ? from.y + NODE_H : from.y;
        const x2 = tx;
        const y2 = down ? to.y : to.y + NODE_H;
        const bend = Math.max(28, Math.abs(y2 - y1) / 2);
        path.setAttribute('d', `M${x1} ${y1} C${x1} ${y1 + (down ? bend : -bend)} ${x2} ${y2 - (down ? bend : -bend)} ${x2} ${y2}`);
      }
      path.setAttribute('class', `quest-edge quest-edge-${edge[2] || 'series'}`);
      path.setAttribute('marker-end', `url(#${id})`);
      svg.append(path);
    }

    for (const node of data.nodes) {
      const item = document.createElement(node.href ? 'a' : 'span');
      item.className = `quest-node quest-node-${node.role}`;
      item.style.left = `${node.x}px`;
      item.style.top = `${node.y}px`;
      if (node.href) {
        item.href = node.href;
        item.addEventListener('pointerenter', () => prefetch(node.href), {passive: true});
        item.addEventListener('focus', () => prefetch(node.href));
      }
      const meta = el('small');
      meta.textContent = node.id ? `#${node.id}${node.level ? ` · ${node.level}` : ''}` : '';
      const name = el('strong');
      name.textContent = node.name;
      item.append(meta, name);
      if (node.role === 'current') {
        const tag = el('span', 'quest-node-tag');
        tag.textContent = '当前';
        item.append(tag);
      }
      item.title = node.name;
      graph.append(item);
    }
    graph.prepend(svg);
    wrap.append(graph);
    this.replaceChildren(wrap);
    requestAnimationFrame(() => {
      const current = graph.querySelector('.quest-node-current');
      if (!current) return;
      wrap.scrollLeft = Math.max(0, current.offsetLeft + current.offsetWidth / 2 - wrap.clientWidth / 2);
    });
  }
}
