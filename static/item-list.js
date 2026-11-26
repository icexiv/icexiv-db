export function element(tag, text, className) {
  const node = document.createElement(tag);
  if (text != null) node.textContent = text;
  if (className) node.className = className;
  return node;
}

export function cardElement({id, name, kind, patch, detail, icon, link}) {
  const card = element('div', null, 'item-card');
  const body = element('span', null, 'card-body');
  if (kind || patch) body.append(element('small', [kind, patch].filter(Boolean).join(' · '), 'card-kind'));
  body.append(element('small', `#${id}`, 'card-id'), element('strong', name));
  if (detail) body.append(element('small', detail));
  link.append(icon, body);
  card.append(link);
  return card;
}

export function itemCard(item) {
  const li = element('li');
  li.append(cardElement(item));
  return li;
}
