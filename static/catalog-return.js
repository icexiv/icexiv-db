// Only carry a catalog inside this deployment (including a Pages subpath).
const base = new URL('./', import.meta.url);
function route(href, pattern) {
  if (!href) return null;
  let url;
  try { url = new URL(href, base); } catch { return null; }
  return url.origin === base.origin && url.protocol === base.protocol && url.pathname.startsWith(base.pathname)
    && pattern.test(url.pathname.slice(base.pathname.length)) ? url : null;
}
const catalog = href => route(href, /^(?:index\.html|items\/(?:index\.html|page\/\d+\.html)?)?$/);
const item = href => route(href, /^items\/\d+\.html$/);
const back = document.querySelector('.back-link a');
const listing = document.querySelector('#catalog-page');
const nav = window.navigation;

// Stop at the first non-item: an unrelated older catalog is not our origin.
function previousCatalog() {
  const entries = nav?.entries() || [];
  for (let i = (nav?.currentEntry?.index ?? 0) - 1; i >= 0; i--) {
    if (!item(entries[i].url)) return catalog(entries[i].url) ? entries[i] : null;
  }
  return null;
}

const source = back && (catalog(new URL(location.href).searchParams.get('fromCatalog'))
  || catalog(document.referrer) || catalog(previousCatalog()?.url));
if (source) {
  back.href = source.href;
  back.addEventListener('click', event => {
    if (event.button || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    const entry = previousCatalog();
    if (entry?.url !== source.href) return;
    event.preventDefault();
    nav.traverseTo(entry.key).committed.catch(() => location.assign(source.href));
  });
}

// Resolve at activation, not render time: filters/layout can change in place.
// Carry only the original catalog URL, never a chain of nested detail URLs.
if (listing || source) {
  function carry(event) {
    const link = event.target.closest?.('a[href]');
    const target = item(link?.href);
    const from = listing ? catalog(location.href) : source;
    if (!target || !from || link.getAttribute('href').startsWith('#')) return;
    target.searchParams.set('fromCatalog', from.pathname + from.search + from.hash);
    link.href = target.href;
  }
  for (const type of ['click', 'auxclick', 'contextmenu']) document.addEventListener(type, carry, true);
}
