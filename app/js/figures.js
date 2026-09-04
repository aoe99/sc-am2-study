// Figure rendering, shared by every screen that shows one.
//
// It lives here rather than in the quiz screen because 午前 and 午後 both need
// it and 午後's screen is imported *by* 午前's: leaving it there would make the
// two modules import each other.

import * as data from './data.js';
import { el } from './ui.js';

export async function figure(path) {
  const wrap = el('div', { class: 'figure' });
  wrap.append(await figureImg(path));
  return wrap;
}

export async function figureImg(path) {
  const url = await data.figureUrl(path);
  if (!url) return el('p', { class: 'muted', text: '（図表を読み込めませんでした）' });
  return el('img', {
    src: url, alt: '図表',
    onclick: () => lightbox(url),
  });
}

function lightbox(url) {
  const box = el('div', { class: 'lightbox', onclick: () => box.remove() },
    el('img', { src: url, alt: '図表（拡大）' }));
  document.body.append(box);
}
