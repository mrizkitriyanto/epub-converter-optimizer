import { h, t } from './core.js';

// ---------------------------------------------------------------- page map
// The book drawn as one square per source page: on Select (scanned or digital), on Convert (done,
// working, waiting, has a finding) and, as a strip of bars, in Review. A big book gets smaller
// squares, and past 1500 pages one square stands for a range of pages.

export function squareSize(pages) {
  return pages <= 600 ? 12 : 8;
}

export function pagesPerSquare(pages) {
  return pages <= 1500 ? 1 : Math.ceil(pages / 1500);
}

// Worst first: a grouped square shows the worst state of its pages.
const RANK = {
  convert: ['finding', 'now', 'todo', 'done'],
  select: ['scanned', 'digital'],
};

// `book` is the book event or the inspect answer: { pages, scanned: [n], blank: [n] }.
// `progress` is { done: Set of finished pages, current: page or null, complete: boolean }.
// `findings` are the pages of warning findings. Blank pages are never worked on: they count as
// done once a later page is done, or when the file is.
export function mapCells(book, progress, findings, mode) {
  const scanned = new Set(book.scanned || []);
  const blank = new Set(book.blank || []);
  const warned = new Set(findings);
  let highest = 0;
  for (const page of progress.done) highest = Math.max(highest, page);
  const stateOf = (n) => {
    if (mode === 'select') return scanned.has(n) ? 'scanned' : 'digital';
    if (warned.has(n)) return 'finding';
    if (progress.current === n) return 'now';
    if (progress.complete || progress.done.has(n) || (blank.has(n) && n < highest)) return 'done';
    return 'todo';
  };
  const suffixOf = (n) => {
    if (warned.has(n) && mode === 'convert') return t('pagemap_finding');
    if (blank.has(n)) return t('pagemap_blank');
    if (scanned.has(n) && mode === 'select') return t('pagemap_scanned');
    return '';
  };
  const rank = RANK[mode];
  const per = pagesPerSquare(book.pages);
  const cells = [];
  for (let first = 1; first <= book.pages; first += per) {
    const last = Math.min(book.pages, first + per - 1);
    let state = rank[rank.length - 1];
    for (let n = first; n <= last; n += 1) {
      const own = stateOf(n);
      if (rank.indexOf(own) < rank.indexOf(state)) state = own;
    }
    let label;
    if (per === 1) {
      const suffix = suffixOf(first);
      label = suffix ? `${t('pagemap_page', { n: first })}, ${suffix}` : t('pagemap_page', { n: first });
    } else {
      label = t('pagemap_pages', { first, last });
    }
    cells.push({ state, label });
  }
  return cells;
}

// The squares are made once for a count and then only change class and title, so a map of a
// thousand pages is not rebuilt on every page event.
export function renderPageMap(container, cells, size) {
  container.style.setProperty('--pm-size', `${size}px`);
  if (container.children.length !== cells.length) {
    container.replaceChildren(...cells.map(() => h('span', { class: 'pm-cell' })));
  }
  cells.forEach((cell, index) => {
    const square = container.children[index];
    const name = `pm-cell pm-${cell.state}`;
    if (square.className !== name) square.className = name;
    if (square.title !== cell.label) square.title = cell.label;
  });
}

// Review's strip: one bar per page, or per group of pages past 600 (or past what the width holds),
// so a bar stays visible.
export function stripBars(pages, findings, current, room = 600) {
  const per = pages <= 600 && pages <= room ? 1 : Math.ceil(pages / Math.min(600, room));
  const warned = new Set(findings);
  const bars = [];
  for (let first = 1; first <= pages; first += per) {
    const last = Math.min(pages, first + per - 1);
    let kind = 'plain';
    for (let n = first; n <= last; n += 1) {
      if (n === current) kind = 'current';
      else if (warned.has(n) && kind === 'plain') kind = 'finding';
    }
    bars.push({ kind, first, last });
  }
  return bars;
}

export function renderStrip(container, bars) {
  if (container.children.length !== bars.length) {
    container.replaceChildren(...bars.map(() => h('span', { class: 'strip-bar' })));
  }
  bars.forEach((bar, index) => {
    const name = `strip-bar strip-${bar.kind}`;
    const element = container.children[index];
    if (element.className !== name) element.className = name;
  });
}
