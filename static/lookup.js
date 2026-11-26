// Global lookup is independent of the active catalog view and its presets.
import {iconUrl} from './assets.js';

const form = document.querySelector('#item-lookup');
const input = form.elements.q;
const popup = document.querySelector('#lookup-results');
const assets = new URL(form.dataset.assets, location.href);
const indexUrl = new URL(form.dataset.index, location.href);
form.action = new URL('items/index.html', assets).href;
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
async function suggest() {
  const query = input.value.trim().toLowerCase();
  const token = ++revision;
  if (!query) { close(); return; }
  try {
    const [index, {categories}] = await load();
    if (revision !== token) return;
    const groups = [[], []];
    const total = [0, 0];
    for (const [id, name, category, icon] of index) {
      const text = name.toLowerCase(), number = String(id);
      if (!text.includes(query) && !number.includes(query)) continue;
      const [kind, family] = categories[category] || ['其他', ''];
      const g = family.startsWith('装备') ? 0 : 1;
      total[g]++;
      const rank = text === query || number === query ? 0 : text.startsWith(query) ? 1 : 2;
      const list = groups[g];
      if (list.length === 5 && list[4].rank <= rank) continue;
      list.push({id, name, kind, icon, rank});
      list.sort((a,b) => a.rank - b.rank);
      if (list.length > 5) list.pop();
    }
    const fragment = document.createDocumentFragment();
    for (const [g, entries] of groups.entries()) {
      if (!entries.length) continue;
      const title = document.createElement('h2');
      title.textContent = `${g ? '其他物品' : '装备'} · ${total[g]}`;
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
    const count = total[0] + total[1];
    const more = document.createElement(count ? 'a' : 'p');
    if (count) {
      const url = new URL(form.action);
      url.searchParams.set('q',input.value.trim());
      more.href = url;
    }
    more.textContent = count ? `查看全部 ${count} 个结果 →` : '没有找到匹配的物品';
    fragment.append(more);
    popup.replaceChildren(fragment);
    popup.hidden = false;
  } catch {
    if (revision !== token) return;
    popup.textContent = '搜索建议暂不可用，可按回车打开物品目录。';
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
