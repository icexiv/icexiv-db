// Global lookup is independent of the active catalog view and its presets.
// The header sets data-kind/action/data-index so the same script serves the
// item and quest catalogs.
import {iconUrl} from './assets.js';

const form = document.querySelector('#item-lookup');
const input = form.elements.q;
const popup = document.querySelector('#lookup-results');
const assets = new URL(form.dataset.assets, location.href);
const indexUrl = new URL(form.dataset.index, location.href);
const isQuest = form.dataset.kind === 'quest';
form.action = new URL(form.getAttribute('action') || (isQuest ? 'quests/index.html' : 'items/index.html'), location.href).href;
let pending, revision = 0;

function load() {
  if (!pending) pending = Promise.all([indexUrl, new URL('filters.json', indexUrl)].map(async url => {
    const response = await fetch(url);
    if (!response.ok) throw new Error();
    return response.json();
  })).catch(error => { pending = null; throw error; });
  return pending;
}

function close() {
  revision++;
  popup.hidden = true;
}

function moreLink(count, fragment) {
  const more = document.createElement(count ? 'a' : 'p');
  if (count) {
    const url = new URL(form.action);
    url.searchParams.set('q', input.value.trim());
    more.href = url;
  }
  more.textContent = count
    ? `查看全部 ${count} 个${isQuest ? '任务' : '结果'} →`
    : `没有找到匹配的${isQuest ? '任务' : '物品'}`;
  fragment.append(more);
}

async function suggest() {
  const query = input.value.trim().toLowerCase();
  const token = ++revision;
  if (!query) { close(); return; }
  try {
    const [index, {categories}] = await load();
    if (revision !== token) return;
    const fragment = document.createDocumentFragment();

    if (isQuest) {
      const entries = [];
      for (const row of index) {
        const [id, name] = row;
        const text = name.toLowerCase(), number = String(id);
        if (!text.includes(query) && !number.includes(query)) continue;
        const rank = text === query || number === query ? 0 : text.startsWith(query) ? 1 : 2;
        entries.push({id, name, rank, level: row[5],
          kind: categories[String(row[3])]?.[0] || '未分类'});
      }
      entries.sort((a, b) => a.rank - b.rank || a.level - b.level || a.name.localeCompare(b.name, 'zh-CN'));
      if (entries.length) {
        const title = document.createElement('h2');
        title.textContent = `任务 · ${entries.length}`;
        fragment.append(title);
      }
      for (const {id, name, kind, level} of entries.slice(0, 10)) {
        const link = document.createElement('a');
        link.href = new URL(`quests/${id}.html`, assets);
        const label = document.createElement('span');
        label.textContent = name;
        const meta = document.createElement('small');
        meta.textContent = `${kind} · ${level} 级`;
        link.append(label, meta);
        fragment.append(link);
      }
      moreLink(entries.length, fragment);
    } else {
      const groups = [[], []];
      const total = [0, 0];
      for (const [id, name, category, icon] of index) {
        const text = name.toLowerCase(), number = String(id);
        if (!text.includes(query) && !number.includes(query)) continue;
        const [kind, family] = categories[category] || ['其他', ''];
        const group = family.startsWith('装备') ? 0 : 1;
        total[group]++;
        const rank = text === query || number === query ? 0 : text.startsWith(query) ? 1 : 2;
        const list = groups[group];
        if (list.length === 5 && list[4].rank <= rank) continue;
        list.push({id, name, kind, icon, rank});
        list.sort((a, b) => a.rank - b.rank);
        if (list.length > 5) list.pop();
      }
      for (const [group, entries] of groups.entries()) {
        if (!entries.length) continue;
        const title = document.createElement('h2');
        title.textContent = `${group ? '其他物品' : '装备'} · ${total[group]}`;
        fragment.append(title);
        for (const {id, name, kind, icon} of entries) {
          const link = document.createElement('a');
          link.href = new URL(`items/${id}.html`, assets);
          const image = document.createElement('img');
          image.src = iconUrl(icon, assets);
          image.alt = '';
          const label = document.createElement('span');
          label.textContent = name;
          const category = document.createElement('small');
          category.textContent = kind;
          link.append(image, label, category);
          fragment.append(link);
        }
      }
      moreLink(total[0] + total[1], fragment);
    }
    popup.replaceChildren(fragment);
    popup.hidden = false;
  } catch {
    if (revision !== token) return;
    popup.textContent = `搜索建议暂不可用，可按回车打开${isQuest ? '任务' : '物品'}目录。`;
    popup.hidden = false;
  }
}

input.addEventListener('input', event => { if (!event.isComposing) suggest(); });
input.addEventListener('compositionend', suggest);
input.addEventListener('focus', suggest);
form.addEventListener('focusout', event => { if (!form.contains(event.relatedTarget)) close(); });
document.addEventListener('pointerdown', event => { if (!form.contains(event.target)) close(); });
document.addEventListener('keydown', event => {
  if (event.isComposing || event.altKey || event.shiftKey || !(event.ctrlKey || event.metaKey) || event.key.toLowerCase() !== 'k') return;
  event.preventDefault();
  input.focus();
});
form.addEventListener('keydown', event => {
  if (event.isComposing) return;
  if (event.key === 'Escape') { event.preventDefault(); input.focus(); close(); return; }
  if (popup.hidden) return;
  if (!['ArrowDown','ArrowUp'].includes(event.key)) return;
  const links = [...popup.querySelectorAll('a')];
  if (!links.length) return;
  event.preventDefault();
  const current = links.indexOf(document.activeElement);
  links[current < 0 ? (event.key === 'ArrowDown' ? 0 : links.length - 1)
    : (current + (event.key === 'ArrowDown' ? 1 : -1) + links.length) % links.length].focus();
});
