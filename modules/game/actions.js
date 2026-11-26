function assetRoot() {
  const lookup = document.querySelector('#item-lookup');
  return new URL(lookup?.dataset.assets ?? '../', document.baseURI);
}

export default class GameActions extends HTMLElement {
  connectedCallback() {
    if (this._mounted) return;
    this._mounted = true;

    const id = this.getAttribute('notist-id') ?? '';
    const name = this.getAttribute('notist-name') ?? '';
    const category = this.getAttribute('notist-category') ?? '';
    const marketable = this.getAttribute('notist-marketable') === 'true';
    const root = assetRoot();

    const actions = document.createElement('div');
    actions.className = 'item-actions';
    const feedback = document.createElement('small');
    feedback.setAttribute('role', 'status');

    const copy = document.createElement('button');
    copy.type = 'button';
    copy.title = '复制物品名称';
    copy.setAttribute('aria-label', copy.title);
    copy.innerHTML = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><rect x="8" y="8" width="13" height="13" rx="2"/><path d="M5 16H4a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1h11a1 1 0 0 1 1 1v1"/></svg>';
    let timer;
    copy.addEventListener('click', async () => {
      try {
        await navigator.clipboard.writeText(name);
        feedback.textContent = '已复制';
      } catch {
        feedback.textContent = '复制失败，请手动复制名称';
      }
      clearTimeout(timer);
      timer = setTimeout(() => { feedback.textContent = ''; }, 3000);
    });
    actions.append(copy);

    function external(label, href, asset) {
      const link = document.createElement('a');
      link.title = label;
      link.setAttribute('aria-label', label);
      link.href = href;
      link.target = '_blank';
      link.rel = 'noopener noreferrer';
      const icon = document.createElement('img');
      icon.src = new URL(asset, root).href;
      icon.width = icon.height = 18;
      icon.alt = '';
      link.append(icon);
      actions.append(link);
    }

    external('在灰机 Wiki 查看', `https://ff14.huijiwiki.com/wiki/${encodeURIComponent('物品:' + name)}`, 'huiji.webp');
    if (category === '47') {
      external('在鱼糕查看', `https://fish.ffmomola.com/#/wiki/fish/${id}`, 'fish.svg');
    }
    if (marketable) {
      const market = location.hostname === 'icexiv.github.io'
        ? 'https://icexiv.github.io/icexiv-market/' : 'https://market.icexiv.top/';
      external('在 IceXIV Market 查看', `${market}#/item/${id}`, 'market.svg');
    }
    external('在 Garland Tools 查看', `https://garlandtools.cn/db/#item/${id}`, 'garland.webp');
    actions.append(feedback);
    this.replaceChildren(actions);
  }
}
