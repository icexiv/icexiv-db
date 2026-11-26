const kit = document.querySelector('.portrait-kit');
if (kit?.querySelector('.portrait-open') && typeof HTMLDialogElement !== 'undefined') {
  import('./portrait-lightbox.js').then(({initPortraitLightbox}) => initPortraitLightbox(kit));
}
