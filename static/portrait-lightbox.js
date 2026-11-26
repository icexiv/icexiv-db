export function initPortraitLightbox(kit) {
  const links = [...kit.querySelectorAll('a.portrait-open')];
  if (!links.length) return;
  const dialog = document.createElement('dialog');
  dialog.className = 'portrait-lightbox';
  dialog.setAttribute('aria-label', '肖像教材部件预览');
  dialog.innerHTML = `<header><strong>部件预览</strong><button type="button" autofocus>关闭</button></header>
    <img alt=""><p aria-live="polite"></p>
    <nav aria-label="切换部件"><button type="button">上一张</button><button type="button">下一张</button></nav>`;
  kit.append(dialog);
  const [close, prev, next] = dialog.querySelectorAll('button');
  const picture = dialog.querySelector('img');
  const caption = dialog.querySelector('p');
  let index = 0;
  function display(i) {
    index = (i + links.length) % links.length;
    const link = links[index];
    picture.src = link.href;
    caption.textContent = `${index + 1} / ${links.length}　${link.querySelector('img').alt}`;
  }
  dialog.querySelector('nav').hidden = links.length < 2;
  prev.onclick = () => display(index - 1);
  next.onclick = () => display(index + 1);
  close.onclick = () => dialog.close();
  dialog.addEventListener('click', event => {
    if (event.target !== dialog) return;
    const r = dialog.getBoundingClientRect();
    if (event.clientX < r.left || event.clientX > r.right || event.clientY < r.top || event.clientY > r.bottom) dialog.close();
  });
  dialog.addEventListener('keydown', event => {
    if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return;
    event.preventDefault();
    display(index + (event.key === 'ArrowLeft' ? -1 : 1));
  });
  for (const [i, link] of links.entries()) {
    link.setAttribute('aria-haspopup', 'dialog');
    link.addEventListener('click', event => {
      if (event.button || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
      event.preventDefault();
      display(i);
      link.focus({preventScroll: true}); // native dialog restores focus here on close
      dialog.showModal();
    });
  }
}
