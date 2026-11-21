import { $, JSON_HEADERS, LIVE_DELAY_MS, URLS, VIEW_FOR_FIRMWARE, errorText, focusStage, formatDuration, formatSize, getJson, h, pageFailed, readAsDataUrl, request, route, setStage, setText, state, t, tn } from './core.js';
import { findingParts, isActive, isConverted, shownFraction, stagesFor } from './job.js';
import { renderStrip, stripBars } from './pagemap.js';

const STYLE_IDS = {
  font: 'font', font_size: 'style-font-size', font_weight: 'font-weight', line_height: 'line-height',
  margin_x: 'margin-x', margin_y: 'margin-y', paragraph_spacing: 'paragraph-spacing',
  first_line_indent: 'first-line-indent', align: 'align', hyphenate: 'hyphenate',
  focus_mode: 'focus-mode', focus_weight: 'focus-weight',
  lang: 'style-lang', mode: 'color-mode',
  dither: 'dither', dither_strength: 'dither-strength', negative: 'negative', bar_position: 'bar-position',
  bar_line: 'bar-line', bar_page: 'bar-page', bar_book_percent: 'bar-book-percent',
  bar_chapter_page: 'bar-chapter-page', bar_chapter_percent: 'bar-chapter-percent',
  bar_chapter_title: 'bar-chapter-title', bar_chapter_marks: 'bar-chapter-marks',
  bar_full_width: 'bar-full-width', bar_font_size: 'bar-font-size', bar_edge_margin: 'bar-edge-margin',
  bar_side_margin: 'bar-side-margin', orientation: 'orientation',
};
const STYLE_FLAGS = new Set([
  'hyphenate', 'focus_mode', 'dither', 'negative', 'bar_line', 'bar_page', 'bar_book_percent',
  'bar_chapter_page', 'bar_chapter_percent', 'bar_chapter_title', 'bar_chapter_marks', 'bar_full_width',
]);
const STYLE_NUMBERS = new Set([
  'font_size', 'font_weight', 'line_height', 'margin_x', 'margin_y', 'paragraph_spacing',
  'first_line_indent', 'focus_weight', 'dither_strength', 'bar_font_size',
  'bar_edge_margin', 'bar_side_margin', 'orientation',
]);
const STYLE_NAMES = new Map(Object.entries(STYLE_IDS).map(([name, id]) => [id, name]));

// ---------------------------------------------------------------- review

export function newReview(job) {
  const first = job.files.findIndex(isConverted);
  const outputs = job.files[Math.max(0, first)].outputs || {};
  const xtc = outputs.xtch ? 'xtch' : (outputs.xtc ? 'xtc' : null);
  return {
    jobId: job.id,
    fileIndex: Math.max(0, first),
    view: VIEW_FOR_FIRMWARE[job.options.firmware] || 'crosspoint',
    format: outputs.epub ? 'epub' : xtc,
    pages: null, // GET .../pages for the file and view
    page: 1, // the device page shown, from 1
    loadedFile: null, // the file whose panes are loaded
    pagesSeq: 0,
    sourceShown: null, // the source page shown, from 1
    showing: 'main', // main: the page as converted; live: a page drawn with the new settings
    selected: null, // the finding that was clicked
    pendingAnchor: null, // where to open the pages once they load: after Apply, or a page map square
    panelOpen: false,
    applying: false,
    live: { style: { ...job.options.style }, size: job.options.size },
    reviewed: new Set(),
    fonts: [],
    controller: new AbortController(), // for the requests of the panes of this file
    liveTimer: null,
    liveAbort: null,
  };
}

export function abortReview(review) {
  clearTimeout(review.liveTimer);
  if (review.liveAbort) review.liveAbort.abort();
  review.controller.abort();
}

// The settings panel and its buttons, Try again and Delete are the same elements for every job. A
// review that begins starts them over, so the panel, "Applying…", "Deleting…" and a disabled Try
// again do not carry on.
export function resetReviewDom() {
  hidePanel();
  $('panel-error').hidden = true;
  setText($('panel-error'), '');
  setText($('apply'), t('apply_to_book'));
  $('apply').disabled = true;
  $('try-again').disabled = false;
  for (const [buttonId, errorId] of [
    ['delete-job', 'delete-error'],
    ['process-delete', 'process-delete-error'],
  ]) {
    $(buttonId).disabled = false;
    setText($(buttonId), t('delete_job'));
    $(errorId).hidden = true;
  }
  $('approve-review').disabled = true;
}

export function showReview() {
  setStage('review');
  if (!state.review || state.review.jobId !== state.job.id) {
    state.review = newReview(state.job);
    resetReviewDom();
    takeCarry(state.review);
  }
  $('view-as').value = state.review.view;
  writeStyle(state.review.live.style);
  syncReviewDock();
  renderReview();
  focusStage();
  loadFilePreview();
}

// After Apply to book, the rebuilt job opens Review where the user was: the same file, page,
// finding, format and view. Every output changed, so every file needs review again.
export function takeCarry(review) {
  const carry = state.carry;
  if (!carry || carry.toJob !== state.job.id) return;
  // the carried place belongs to its own file: never applied to another one
  if (!isConverted(state.job.files[carry.fileIndex] || {})) return;
  state.carry = null;
  review.fileIndex = carry.fileIndex;
  const outputs = state.job.files[review.fileIndex].outputs || {};
  // an XTC stays an XTC when Apply changed its color mode: xtc and xtch name the same preview
  if (carry.format === 'epub' && outputs.epub) review.format = 'epub';
  else if (carry.format !== 'epub' && (outputs.xtch || outputs.xtc)) review.format = outputs.xtch ? 'xtch' : 'xtc';
  review.view = carry.view;
  review.pendingAnchor = carry.anchor;
  if (carry.selected) {
    const findings = state.run.files[review.fileIndex].findings;
    review.selected = findings.find((f) => f.page === carry.selected.page && f.message === carry.selected.message) || null;
  }
}

// A square of Convert's page map: Review of that file, at the first device page of that page.
export function openReviewAt(sourcePage) {
  const index = state.run.current === null ? 0 : state.run.current;
  showFile(index);
  const review = state.review;
  if (review.pages && review.pages.device_pages > 0) {
    const page = firstPageFrom(review.pages, sourcePage);
    if (page) goTo(page);
  } else {
    review.pendingAnchor = { source: sourcePage };
  }
}

// Review of one file of the job: from a queue pill on Convert, or a file that becomes ready.
export function showFile(index) {
  showReview();
  if (state.review.fileIndex === index) return;
  state.review.fileIndex = index;
  state.review.loadedFile = null;
  renderReview();
  loadFilePreview();
}

export function renderReview() {
  const { job, review } = state;
  const info = job.files[review.fileIndex];
  const file = state.run.files[review.fileIndex];
  const converted = isConverted(info);
  const xtc = info.outputs.xtch ? 'xtch' : (info.outputs.xtc ? 'xtc' : null);
  if (!info.outputs[review.format]) review.format = info.outputs.epub ? 'epub' : xtc;
  setText($('review-title'), info.name);
  renderChips(info, file, converted);
  const epubToggle = document.querySelector('input[name="preview-format"][value="epub"]');
  const xtcToggle = document.querySelector('input[name="preview-format"][value="xtc"]');
  epubToggle.disabled = !info.outputs.epub;
  xtcToggle.disabled = !xtc;
  (review.format === 'epub' ? epubToggle : xtcToggle).checked = true;
  document.querySelector('.approx').hidden = review.format !== 'epub';
  // what reaches the EPUB on the Xteink: Focus Mode only, the reader sets the rest
  $('dock-epub-note').hidden = review.format !== 'epub';
  $('focus-weight-note').hidden = review.format !== 'epub';
  $('panel-epub-note').hidden = makesXtc();
  $('change-settings').hidden = !converted;
  $('review-dock').hidden = !converted;
  $('approve-review').hidden = !converted;
  $('strip-section').hidden = !converted;
  updateApply();
  $('try-again').hidden = job.files.some(isConverted); // with nothing converted, trying again is the one action
  renderFilePick(job);
  renderNote(job, info, converted);
  renderReviewStatus(job);
  $('review-grid').hidden = !converted;
  renderFindings(file);
  renderPageStrip();
}

// While the job runs on, the top bar says what the other files do: converting, ready, failed, or
// cancelled, and leads back to Convert. A file ready to review is a link to it. A screen reader
// hears the words when they change, not each new percent.
export function renderReviewStatus(job) {
  const run = state.run;
  const parts = [];
  const spoken = [];
  const active = isActive(job);
  const ready = job.files.findIndex((info, i) => i !== state.review.fileIndex && isConverted(info) && !state.review.reviewed.has(i));
  if (active && run.current !== null && run.files[run.current].status === 'running') {
    const file = run.files[run.current];
    const info = job.files[run.current];
    const percent = Math.round(shownFraction(file, stagesFor(info, job.options, file.stages)) * 100);
    parts.push(t('converting_status', { name: info.name, percent }));
    spoken.push(t('converting_status_live', { name: info.name }));
  }
  const words = [];
  run.files.forEach((file, i) => {
    if (file.status === 'failed') words.push(t('file_failed_status', { name: job.files[i].name }));
  });
  if (job.status === 'cancelled') words.push(t('job_cancelled_status'));
  parts.push(...words);
  spoken.push(...words);
  const link = $('review-ready-link');
  link.hidden = ready < 0;
  if (ready >= 0) {
    const text = t('ready_to_review', { name: job.files[ready].name });
    link.dataset.index = String(ready);
    setText(link, text);
    spoken.push(text);
  }
  setText($('review-status-text'), parts.join(' · ') + (parts.length && ready >= 0 ? ' · ' : ''));
  setText($('review-status-live'), spoken.join(' · '));
  $('review-status').hidden = parts.length === 0 && ready < 0;
  $('review-progress-link').hidden = !active;
}

// The strip: one bar per page of the book (source pages of a PDF, device pages otherwise), the
// warnings and the page shown marked. It is one slider for the keyboard.
export function stripPlace() {
  const review = state.review;
  if (!review.pages) return null;
  if (isPdf() && review.pages.source_pages > 0) {
    return { total: review.pages.source_pages, current: review.sourceShown || nearestSource(review.page) || 1, source: true };
  }
  return { total: review.pages.device_pages, current: review.page, source: false };
}

export function renderPageStrip() {
  const place = stripPlace();
  const strip = $('page-strip');
  if (!place || place.total < 1) {
    strip.replaceChildren();
    setText($('strip-label'), '');
    return;
  }
  const file = state.run.files[state.review.fileIndex];
  const warned = place.source
    ? file.findings.filter((finding) => finding.level === 'warning' && finding.page > 0).map((finding) => finding.page)
    : [];
  // about two pixels a bar: a bar and its gap
  const room = strip.clientWidth > 0 ? Math.max(20, Math.floor(strip.clientWidth / 2)) : 600;
  const bars = stripBars(place.total, warned, place.current, room);
  strip.dataset.per = String(bars.length ? bars[0].last - bars[0].first + 1 : 1);
  renderStrip(strip, bars);
  const label = t('strip_value', { page: place.current, total: place.total });
  setText($('strip-label'), label);
  strip.setAttribute('aria-valuemax', String(place.total));
  strip.setAttribute('aria-valuenow', String(place.current));
  strip.setAttribute('aria-valuetext', warned.includes(place.current) ? t('strip_value_finding', { page: place.current, total: place.total }) : label);
}

export function goToPlace(page) {
  const place = stripPlace();
  if (!place) return;
  const target = Math.min(Math.max(1, page), place.total);
  if (!place.source) {
    goTo(target);
    return;
  }
  // backwards, the last device page at or before the page: a blank page has none of its own
  const pages = state.review.pages;
  const device = target < place.current ? lastPageUpTo(pages, target) || firstPageFrom(pages, target) : firstPageFrom(pages, target);
  if (device) goTo(device);
}

// the last device page whose source page is `source` or an earlier one
export function lastPageUpTo(pages, source) {
  const map = pages.page_map;
  for (let i = map.length - 1; i >= 0; i -= 1) if (map[i] > 0 && map[i] <= source) return i + 1;
  return null;
}

export function onStripClick(event) {
  const bar = event.target.closest && event.target.closest('.strip-bar');
  const place = stripPlace();
  if (!bar || !place) return;
  const index = Array.prototype.indexOf.call($('page-strip').children, bar);
  goToPlace(index * Number($('page-strip').dataset.per || 1) + 1);
}

export function onStripKey(event) {
  const place = stripPlace();
  if (!place) return;
  const moves = { ArrowLeft: -1, ArrowDown: -1, ArrowRight: 1, ArrowUp: 1, PageDown: -10, PageUp: 10 };
  if (event.key === 'Home') goToPlace(1);
  else if (event.key === 'End') goToPlace(place.total);
  else if (event.key in moves) goToPlace(place.current + moves[event.key]);
  else return;
  event.preventDefault();
}

export function renderChips(info, file, converted) {
  const chips = [];
  if (converted) {
    const time = file.seconds === null ? t('converted') : t('converted_in', { time: formatDuration(file.seconds) });
    chips.push(h('li', { class: 'chip' }, time));
    for (const [format, after] of Object.entries(info.sizes)) {
      if (after === null || after === undefined) continue;
      const before = info.size === null ? '' : formatSize(info.size);
      const values = { format: t(format === 'epub' ? 'output_epub' : 'output_xtc'), after: formatSize(after), before };
      const text = info.size === null ? t('chip_size_only', values) : t('chip_size', values);
      chips.push(h('li', { class: 'chip' }, text));
    }
    const warnings = file.findings.filter((finding) => finding.level === 'warning').length;
    const summary = warnings ? tn('warnings', warnings) : t('warnings_none');
    chips.push(h('li', { class: warnings ? 'chip warn' : 'chip' }, summary));
  }
  $('chips').replaceChildren(...chips);
}

export function renderFilePick(job) {
  const pick = $('file-pick');
  pick.hidden = job.files.length < 2;
  if (pick.hidden) return;
  const select = $('review-file');
  const statuses = state.run.files.map((file) => file.status);
  const key = `${job.id}:${job.status}:${job.files.map(isConverted).join()}:${statuses.join()}:${[...state.review.reviewed].join()}`;
  if (select.dataset.key !== key) {
    select.dataset.key = key;
    const label = (file, i) => {
      let word = t('review_not_converted');
      if (statuses[i] === 'running') word = t('queue_converting');
      else if (statuses[i] === 'failed') word = t('queue_failed');
      else if (job.status === 'cancelled' && !isConverted(file)) word = t('queue_cancelled');
      if (!isConverted(file)) return `${file.name} (${word})`;
      return `${file.name} (${t(state.review.reviewed.has(i) ? 'reviewed' : 'review_required')})`;
    };
    select.replaceChildren(...job.files.map((file, i) => h('option', { value: String(i) }, label(file, i))));
  }
  select.value = String(state.review.fileIndex);
}

export function renderNote(job, info, converted) {
  let text = '';
  if (!converted) text = info.error || (job.status === 'cancelled' ? t('job_cancelled') : t('file_not_converted'));
  else if (job.status === 'cancelled') text = t('job_cancelled');
  const note = $('review-note');
  note.hidden = text === '';
  setText(note, text);
  note.classList.toggle('problem', !converted);
}

// Warnings are the findings; notes (blank pages, OCR pages) sit in a group of their own, closed.
export function renderFindings(file) {
  const list = $('findings-list');
  const warnings = file.findings.filter((finding) => finding.level === 'warning');
  const notes = file.findings.filter((finding) => finding.level !== 'warning');
  const selected = state.review.selected ? file.findings.indexOf(state.review.selected) : -1;
  const key = `${state.job.id}:${state.review.fileIndex}:${file.findings.length}:${selected}`;
  setText($('findings-title'), t('findings_title', { n: warnings.length }));
  $('findings-empty').hidden = warnings.length > 0;
  $('notes').hidden = notes.length === 0;
  setText($('notes-title'), tn('notes_title', notes.length));
  if (list.dataset.key === key) return;
  list.dataset.key = key;
  list.replaceChildren(...warnings.map(findingItem));
  $('notes-list').replaceChildren(...notes.map((finding) => h('li', { class: 'finding plain' }, ...findingParts(finding))));
}

export function findingItem(finding) {
  const parts = findingParts(finding);
  if (!(finding.page > 0)) return h('li', { class: 'finding plain' }, ...parts);
  const current = state.review.selected === finding;
  if (current) parts.splice(1, 0, h('span', { class: 'showing' }, ` · ${t('showing')}`));
  const button = h('button', { type: 'button', class: 'finding', onclick: () => selectFinding(finding) }, ...parts);
  if (current) button.setAttribute('aria-current', 'true');
  return h('li', null, button);
}

// ----------------------------------------------------------- the panes

export function resetPanes() {
  const review = state.review;
  abortReview(review);
  review.controller = new AbortController();
  Object.assign(review, { pages: null, page: 1, sourceShown: null, showing: 'main', selected: null });
  for (const image of [$('device-img'), $('source-img')]) image.removeAttribute('src');
  $('source-page').hidden = true;
  $('source-text').hidden = true;
  $('source-text').textContent = '';
  for (const caption of [$('device-caption'), $('source-caption'), $('source-status'), $('device-status')]) {
    caption.textContent = '';
  }
  $('prev').disabled = true;
  $('next').disabled = true;
  delete $('findings-list').dataset.key;
}

export async function loadFilePreview() {
  const review = state.review;
  const info = state.job.files[review.fileIndex];
  if (!isConverted(info) || review.loadedFile === review.fileIndex) return;
  review.loadedFile = review.fileIndex;
  resetPanes();
  renderFindings(state.run.files[review.fileIndex]);
  if (info.kind !== 'pdf') loadText();
  await loadPages(null);
}

// The text of a book that is not a PDF is set once, as text, in a pane that scrolls.
export async function loadText() {
  const review = state.review;
  setText($('source-status'), t('loading'));
  try {
    const response = await request(URLS.text(state.job.id, review.fileIndex), { signal: review.controller.signal });
    const text = await response.text();
    if (state.review !== review) return;
    $('source-text').textContent = text;
    $('source-text').hidden = false;
    setText($('source-caption'), t('source_text_caption'));
    setText($('source-status'), '');
  } catch (error) {
    if (error.name !== 'AbortError') setText($('source-status'), error.message);
  }
}

// `anchor` keeps the place when the view changes: the same source page, or the same chapter.
export async function loadPages(anchor) {
  const review = state.review;
  const mine = ++review.pagesSeq;
  setText($('device-status'), t('preview_loading'));
  try {
    const address = URLS.pages(state.job.id, review.fileIndex, review.format, review.view);
    const pages = await getJson(address, { signal: review.controller.signal });
    if (state.review !== review || mine !== review.pagesSeq) return; // left, or the view changed
    review.pages = pages;
    setText($('device-status'), pages.device_pages > 0 ? '' : t('error_no_preview'));
    const pending = review.pendingAnchor;
    review.pendingAnchor = null;
    if (pages.device_pages > 0) goTo(pageOfAnchor(pages, anchor || pending) || firstPageOfSelected(pages) || 1);
  } catch (error) {
    if (error.name !== 'AbortError' && mine === review.pagesSeq) setText($('device-status'), error.message);
  }
}

export const isPdf = () => state.job.files[state.review.fileIndex].kind === 'pdf';

// device page p shows source page page_map[p - 1]; 0 means the page has no source page
export function sourceOfPage(page) {
  const value = state.review.pages.page_map[page - 1];
  return value > 0 ? value : null;
}

export function nearestSource(page) {
  const map = state.review.pages.page_map;
  for (let i = page - 1; i < map.length; i += 1) if (map[i] > 0) return map[i];
  for (let i = page - 1; i >= 0; i -= 1) if (map[i] > 0) return map[i];
  return null;
}

// the first device page that shows source page `source` or a later one
export function firstPageFrom(pages, source) {
  const map = pages.page_map;
  for (let i = 0; i < map.length; i += 1) if (map[i] > 0 && map[i] >= source) return i + 1;
  for (let i = map.length - 1; i >= 0; i -= 1) if (map[i] > 0) return i + 1;
  return null;
}

export const firstPageOfSelected = (pages) => {
  const selected = state.review.selected;
  return selected && selected.page > 0 ? firstPageFrom(pages, selected.page) : null;
};

// the chapter that holds a device page; a book without a heading has no chapters and is chapter 0
export function chapterOfPage(pages, page) {
  let chapter = 0;
  pages.chapters.forEach(([, first], index) => {
    if (first <= page) chapter = index;
  });
  return chapter;
}

export function anchorHere() {
  const review = state.review;
  if (!review.pages) return null;
  return isPdf()
    ? { source: review.sourceShown || nearestSource(review.page) }
    : { chapter: chapterOfPage(review.pages, review.page) };
}

export function pageOfAnchor(pages, anchor) {
  if (!anchor) return null;
  if (anchor.source) return firstPageFrom(pages, anchor.source);
  const chapter = pages.chapters[anchor.chapter];
  return chapter ? chapter[1] : null;
}

export function goTo(page) {
  const review = state.review;
  const count = review.pages.device_pages;
  review.page = Math.min(Math.max(1, page), count);
  $('prev').disabled = review.page <= 1;
  $('next').disabled = review.page >= count;
  updateSource();
  refreshDevice();
  renderPageStrip();
}

export const step = (delta) => {
  if (state.review && state.review.pages) goTo(state.review.page + delta);
};

// A device page with no source page leaves the original where it is.
export function updateSource() {
  const review = state.review;
  if (!isPdf()) return;
  let source = sourceOfPage(review.page);
  if (source === null && review.sourceShown === null) source = nearestSource(review.page);
  if (source === null) {
    if (review.sourceShown === null) setText($('source-status'), t('source_missing'));
    return;
  }
  if (source === review.sourceShown) return;
  review.sourceShown = source;
  setText($('source-status'), '');
  $('source-page').hidden = false;
  setImage($('source-img'), URLS.source(state.job.id, review.fileIndex, source), t('source_alt', { page: source }));
  setText($('source-caption'), t('source_caption', { page: source }));
}

export function setImage(image, address, alt) {
  image.alt = alt;
  if (image.getAttribute('src') !== address) image.setAttribute('src', address);
}

export function selectFinding(finding) {
  const review = state.review;
  review.selected = finding;
  renderFindings(state.run.files[review.fileIndex]);
  const button = $('findings-list').querySelector('[aria-current]');
  if (button) button.focus();
  if (!review.pages || review.pages.device_pages < 1) return;
  const page = firstPageFrom(review.pages, finding.page);
  if (page) goTo(page);
}

// A picture that cannot be shown says why: the server gave a reason, the picture could not. The
// reason is written only if the picture is still the one that failed.
export async function explainImage(image, status) {
  const address = image.getAttribute('src');
  if (!address || address.startsWith('data:')) return;
  let reason;
  try {
    const response = await fetch(address);
    reason = response.ok ? t('error_unknown', { status: response.status }) : await errorText(response);
  } catch (error) {
    reason = t('error_unreachable');
  }
  if (image.getAttribute('src') === address) setText(status, reason);
}

export function sizeFrameToImage(image, frame) {
  if (image.naturalWidth > 0) frame.style.aspectRatio = `${image.naturalWidth} / ${image.naturalHeight}`;
}

// ------------------------------------------------- device page and live

export function refreshDevice() {
  const review = state.review;
  clearTimeout(review.liveTimer);
  if (review.liveAbort) review.liveAbort.abort();
  if (liveDirty()) {
    setText($('device-status'), t('updating_preview')); // the old picture stays until the new one is here
    review.liveTimer = setTimeout(requestLive, LIVE_DELAY_MS);
    return;
  }
  showMain();
}

export function showMain() {
  const review = state.review;
  review.showing = 'main';
  setText($('device-status'), '');
  const address = URLS.device(
    state.job.id, review.fileIndex, review.format, review.page, encodeURIComponent(review.view),
  );
  setImage($('device-img'), address, t('device_alt', { page: review.page }));
  setText($('device-caption'), deviceCaption(t('device_caption', { page: review.page, total: review.pages.device_pages })));
}

export function deviceCaption(text) {
  const device = state.job.options.device;
  return `${t(`device_${device.replace('-', '_')}`)} · ${text}`;
}

// Compared value by value: the panel and the job keep the style's keys in other orders.
export function liveDirty() {
  return changedCount() > 0;
}

export function liveQuery() {
  const review = state.review;
  const style = review.live.style;
  const format = review.format === 'epub'
    ? 'epub'
    : (style.mode === 'xth' ? 'xtch' : 'xtc');
  const params = new URLSearchParams({
    format,
    view: review.view,
    style: JSON.stringify(style),
    size: review.live.size,
  });
  const source = isPdf() ? review.sourceShown || nearestSource(review.page) : null;
  if (source) params.set('page', String(source));
  else params.set('chapter', String(chapterOfPage(review.pages, review.page)));
  return params.toString();
}

// A newer request aborts the older one, so an answer that comes late never replaces a newer one.
export async function requestLive() {
  const review = state.review;
  const controller = new AbortController();
  review.liveAbort = controller;
  try {
    const response = await request(URLS.live(state.job.id, review.fileIndex, liveQuery()), { signal: controller.signal });
    const address = await readAsDataUrl(await response.blob());
    if (controller.signal.aborted || state.review !== review) return;
    review.showing = 'live';
    setImage($('device-img'), address, t('device_alt', { page: review.page }));
    const shown = Number(response.headers.get('X-Excerpt-Index')) + 1;
    const pages = Number(response.headers.get('X-Excerpt-Pages'));
    setText($('device-caption'), t('live_caption', { page: shown, pages }));
    setText($('device-status'), decodeURIComponent(response.headers.get('X-Font-Fallback') || ''));
  } catch (error) {
    if (error.name !== 'AbortError' && state.review === review) setText($('device-status'), error.message);
  }
}

export function writeStyle(style) {
  for (const [name, id] of Object.entries(STYLE_IDS)) {
    const input = $(id);
    if (STYLE_FLAGS.has(name)) input.checked = style[name];
    else input.value = String(style[name]);
  }
}

export function readStyle() {
  const style = {};
  for (const [name, id] of Object.entries(STYLE_IDS)) {
    const input = $(id);
    if (STYLE_FLAGS.has(name)) style[name] = input.checked;
    else if (STYLE_NUMBERS.has(name)) style[name] = Number(input.value);
    else style[name] = input.value;
  }
  return style;
}

export function syncWeights(preferred) {
  const family = $('font').value;
  const found = state.review.fonts.find((item) => item.family === family);
  const weights = found ? found.weights : [];
  $('font-weight').replaceChildren(
    ...weights.map((weight) => h('option', { value: String(weight) }, String(weight))),
  );
  const wanted = Number(preferred);
  $('font-weight').value = String(weights.includes(wanted) ? wanted : weights[0]);
  updateFocusAvailability();
}

export function updateFocusAvailability() {
  const found = state.review.fonts.find((item) => item.family === $('font').value);
  const available = Boolean(found?.weights.some((weight) => weight > Number($('font-weight').value)));
  $('focus-mode').disabled = !available;
  $('focus-unavailable').hidden = available;
  if (!available) $('focus-mode').checked = false;
  // above a semibold text only Bold is heavier: Semibold is not offered, and a chosen one moves up
  const review = state.review;
  const semibold = $('focus-weight').querySelector('option[value="600"]');
  semibold.disabled = Number($('font-weight').value) >= 600;
  if (semibold.disabled && review.live.style.focus_weight === 600) {
    review.live.style.focus_weight = 700;
    $('focus-weight').value = '700';
  }
}

export async function loadFonts() {
  const review = state.review;
  try {
    review.fonts = await getJson(URLS.fonts(state.job.id));
    $('font').replaceChildren(
      ...review.fonts.map((item) => h('option', { value: item.family }, item.family)),
      h('option', { value: '__upload__' }, t('font_upload')),
    );
    const wanted = review.live.style.font;
    if (!review.fonts.some((item) => item.family === wanted)) {
      review.live.style.font = 'Literata';
      setText($('panel-error'), t('font_missing_panel', { name: wanted }));
      $('panel-error').hidden = false;
    }
    $('font').value = review.live.style.font;
    syncWeights(review.live.style.font_weight);
  } catch (error) {
    setText($('panel-error'), error.message);
    $('panel-error').hidden = false;
  }
}

export async function openPanel() {
  const review = state.review;
  review.panelOpen = true;
  writeStyle(review.live.style);
  $('live-size').value = review.live.size;
  $('settings-panel').hidden = false;
  $('review-grid').classList.add('with-panel');
  $('change-settings').setAttribute('aria-expanded', 'true');
  $('panel-error').hidden = true;
  setText($('copy-status'), '');
  await loadFonts();
  await loadSavedStyles();
  updateApply();
  $('font').focus();
}

async function loadSavedStyles() {
  const entries = await getJson('/api/styles');
  $('saved-style').replaceChildren(
    h('option', { value: '' }, t('built_in_style')),
    ...entries.filter((item) => !item.error).map((item) =>
      h('option', { value: item.name }, `${item.name}${item.default ? ' (default)' : ''}`)),
  );
}

export async function chooseSavedStyle() {
  const name = $('saved-style').value;
  if (!name) return;
  try {
    const response = await request(`/api/styles/${encodeURIComponent(name)}`);
    const style = await response.json();
    writeStyle(style);
    syncWeights(style.font_weight);
    const findings = decodeURIComponent(response.headers.get('X-Style-Findings') || '');
    setText($('panel-error'), findings);
    $('panel-error').hidden = !findings;
    onLiveChange();
  } catch (error) {
    setText($('panel-error'), error.message);
    $('panel-error').hidden = false;
  }
}

export async function saveSavedStyle() {
  const name = window.prompt(t('save_style'));
  if (!name) return;
  try {
    let url = `/api/styles/${encodeURIComponent(name)}`;
    const init = { method: 'PUT', headers: JSON_HEADERS, body: JSON.stringify(readStyle()) };
    try {
      await request(url, init);
    } catch (error) {
      if (error.status !== 409 || !window.confirm(t('overwrite_style', { name }))) throw error;
      await request(`${url}?overwrite=true`, init);
    }
    await loadSavedStyles();
    $('saved-style').value = name;
  } catch (error) {
    setText($('panel-error'), error.message);
    $('panel-error').hidden = false;
  }
}

export async function makeSavedDefault() {
  const name = $('saved-style').value;
  if (!name) return;
  try {
    await getJson(`/api/styles/${encodeURIComponent(name)}/default`, { method: 'PUT' });
    await loadSavedStyles();
    $('saved-style').value = name;
  } catch (error) {
    setText($('panel-error'), error.message);
    $('panel-error').hidden = false;
  }
}

export async function deleteSavedStyle() {
  const name = $('saved-style').value;
  if (!name || !window.confirm(t('delete_style_confirm', { name }))) return;
  try {
    await request(`/api/styles/${encodeURIComponent(name)}`, { method: 'DELETE' });
    await loadSavedStyles();
  } catch (error) {
    setText($('panel-error'), error.message);
    $('panel-error').hidden = false;
  }
}

export function hidePanel() {
  $('settings-panel').hidden = true;
  $('review-grid').classList.remove('with-panel');
  $('change-settings').setAttribute('aria-expanded', 'false');
}

// `restore` puts the page as converted back in place of a live one.
export function closePanel(moveFocus, restore) {
  const review = state.review;
  review.panelOpen = false;
  hidePanel();
  if (restore && review.pages && review.pages.device_pages > 0) refreshDevice();
  if (moveFocus) $('change-settings').focus();
}

// The number of style values that differ from the files: the dock and the panel edit one style.
export function changedCount() {
  const { live } = state.review;
  const options = state.job.options;
  const names = new Set([...Object.keys(live.style), ...Object.keys(options.style)]);
  let count = live.size !== options.size ? 1 : 0;
  for (const name of names) {
    if (name === 'focus_weight' && !live.style.focus_mode) continue; // no bold to weigh
    if (JSON.stringify(live.style[name]) !== JSON.stringify(options.style[name])) count += 1;
  }
  return count;
}

export const makesXtc = () => (state.job.options.formats || []).some((format) => format.startsWith('xtc'));

// The changes that a rebuild would put into the files: the image size and Focus Mode always (Focus
// Mode is written into the EPUB), the other style values only when the job makes an XTC. On the
// Xteink the EPUB follows the reader's own text size, spacing and margins.
export function fileChangeCount() {
  const { live } = state.review;
  const options = state.job.options;
  const xtc = makesXtc();
  const names = new Set([...Object.keys(live.style), ...Object.keys(options.style)]);
  let count = live.size !== options.size ? 1 : 0;
  for (const name of names) {
    if (!xtc && name !== 'focus_mode' && name !== 'focus_weight') continue;
    if (name === 'focus_weight' && !live.style.focus_mode) continue; // no bold to weigh
    if (JSON.stringify(live.style[name]) !== JSON.stringify(options.style[name])) count += 1;
  }
  return count;
}

// A change that a rebuild would put into the files makes Apply the one blue button and holds
// Continue back; Apply waits while files of the job still convert. A change that only the preview
// shows says so, and holds nothing back.
export function updateApply() {
  const review = state.review;
  if (!review) return;
  const dirty = fileChangeCount() > 0;
  const shownOnly = !dirty && liveDirty();
  const busy = isActive(state.job);
  const converted = isConverted(state.job.files[review.fileIndex]);
  $('apply').disabled = !dirty || review.applying || busy;
  $('apply').classList.toggle('primary', dirty);
  $('apply').classList.toggle('secondary', !dirty);
  $('discard').hidden = !(dirty || shownOnly) || review.applying;
  let status = '';
  if (review.applying) status = t('applying_rebuild');
  else if (dirty && busy) status = `${tn('changes_pending', fileChangeCount())} · ${t('apply_wait')}`;
  else if (dirty) status = tn('changes_pending', fileChangeCount());
  else if (shownOnly) status = tn('changes_preview_only', changedCount());
  setText($('apply-status'), status);
  const next = nextUnreviewed();
  setText($('approve-review'), next !== undefined ? t('continue_next_file') : t('continue_to_export'));
  const waiting = next === undefined && !exportReady(true);
  $('approve-review').disabled = !converted || dirty || review.applying || waiting;
  $('approve-review').classList.toggle('primary', !dirty);
  $('approve-review').classList.toggle('secondary', dirty);
  let hint = '';
  if (dirty) hint = t('apply_or_discard');
  else if (waiting && busy) {
    const left = state.job.files.find((info, i) => state.run.files[i].status !== 'done' && state.run.files[i].status !== 'failed');
    if (left) hint = t('export_waiting_for', { name: left.name });
  }
  setText($('approve-hint'), hint);
}

export function nextUnreviewed() {
  const review = state.review;
  return state.job.files
    .map((file, index) => index)
    .find((index) => index !== review.fileIndex && isConverted(state.job.files[index]) && !review.reviewed.has(index));
}

export function discardChanges() {
  const review = state.review;
  review.live = { style: { ...state.job.options.style }, size: state.job.options.size };
  writeStyle(review.live.style);
  $('live-size').value = review.live.size;
  syncReviewDock();
  updateApply();
  if (review.pages && review.pages.device_pages > 0) refreshDevice();
}

export function onLiveChange() {
  const review = state.review;
  if (document.activeElement === $('font-weight')) updateFocusAvailability();
  review.live = { style: readStyle(), size: $('live-size').value };
  syncReviewDock();
  updateApply();
  if (review.pages && review.pages.device_pages > 0) refreshDevice();
}

export function syncReviewDock() {
  const style = state.review.live.style;
  const focus = Boolean(style.focus_mode);
  $('style-font-size').value = String(style.font_size);
  $('line-height').value = String(style.line_height);
  $('margin-x').value = String(style.margin_x);
  $('first-line-indent').value = String(style.first_line_indent);
  $('focus-mode').checked = focus;
  $('focus-weight').value = String(style.focus_weight);
  setText($('style-font-size-value'), String(style.font_size));
  setText($('line-height-value'), `${style.line_height}%`);
  setText($('margin-x-value'), String(style.margin_x));
  setText($('first-line-indent-value'), `${style.first_line_indent}%`);
  // a value that differs from the files says so, in words beside the number
  const applied = state.job.options.style;
  const dock = [['font_size', 'style-font-size'], ['line_height', 'line-height'], ['margin_x', 'margin-x'], ['first_line_indent', 'first-line-indent']];
  for (const [name, id] of dock) {
    const output = $(`${id}-value`);
    const changed = style[name] !== applied[name];
    output.classList.toggle('changed', changed);
    if (changed) output.append(` · ${t('changed')}`);
  }
  $('focus-mode-changed').hidden = focus === Boolean(applied.focus_mode);
  $('focus-weight-changed').hidden = !focus || style.focus_weight === applied.focus_weight;
  $('focus-weight').disabled = !focus;
  $('focus-weight-field').hidden = !focus;
}

export function onReviewDockChange(event) {
  const review = state.review;
  const input = event.target;
  const name = STYLE_NAMES.get(input.id);
  if (!name) return;
  let value = input.value;
  if (STYLE_FLAGS.has(name)) value = input.checked;
  else if (STYLE_NUMBERS.has(name)) value = Number(input.value);
  review.live.style[name] = value;
  syncReviewDock();
  updateApply();
  if (review.pages && review.pages.device_pages > 0) refreshDevice();
}

export function updateApproval() {
  updateApply();
}

export async function approveCurrentFile() {
  const review = state.review;
  if (fileChangeCount() > 0 || !isConverted(state.job.files[review.fileIndex])) return;
  review.reviewed.add(review.fileIndex);
  const successful = state.job.files
    .map((file, index) => index)
    .filter((index) => isConverted(state.job.files[index]));
  const next = successful.find((index) => !review.reviewed.has(index));
  if (next !== undefined) {
    review.fileIndex = next;
    review.loadedFile = null;
    renderReview();
    await loadFilePreview();
    return;
  }
  if (exportReady()) showExport();
  else renderReview();
}

// Export is per job: every file has ended, and every one that converted is reviewed. `counting`
// asks whether only the current file's review is missing.
export function exportReady(counting = false) {
  const { review } = state;
  if (isActive(state.job)) return false;
  const converted = state.job.files.filter(isConverted);
  const reviewed = review.reviewed.size + (counting && !review.reviewed.has(review.fileIndex) ? 1 : 0);
  return converted.length > 0 && reviewed >= converted.length;
}

export function showExport() {
  if (!exportReady()) {
    showReview();
    return;
  }
  setStage('export');
  renderExport();
  focusStage();
}

// Export: what was made, what was checked, and what is left of the job. Only reviewed files are
// here; the first download is the one blue button.
export function renderExport() {
  const { job, review, run } = state;
  const reviewed = job.files.map((info, index) => ({ info, index })).filter(({ info, index }) => isConverted(info) && review.reviewed.has(index));
  const rows = [];
  const checks = [];
  let primary = true;
  let warnings = 0;
  const device = t(`device_${job.options.device.replace('-', '_')}`);
  for (const { info, index } of reviewed) {
    const file = run.files[index];
    warnings += file.findings.filter((finding) => finding.level === 'warning').length;
    for (const [format, name] of Object.entries(info.outputs)) {
      const size = info.sizes[format];
      const parts = [t(format === 'epub' ? 'output_epub' : 'output_xtc')];
      if (format === 'epub') parts.push(t('reflowable'));
      else parts.push(t(format === 'xtch' ? 'xtc_kind_gray' : 'xtc_kind_bw', { device }));
      const description = h('span', null);
      if (size !== null && size !== undefined) {
        parts.push(format === 'epub' && info.size ? `${formatSize(size)}, ${t('down_from', { before: formatSize(info.size) })}` : formatSize(size));
      }
      const label = t('download_file', { format: t(format === 'epub' ? 'output_epub' : 'output_xtc') });
      const link = h('a', { class: `button ${primary ? 'primary' : 'secondary'}`, href: URLS.fileDownload(job.id, index, format), download: true }, label);
      primary = false;
      setText(description, parts.join(' · '));
      rows.push(h('li', { class: 'export-file' }, h('span', { class: 'export-file-copy' }, h('strong', null, name), description), link));
      // an XTC's page count comes from the header of the file: it is added when it is here
      if (format !== 'epub') {
        getJson(URLS.xtcPages(job.id, index, format)).then((count) => {
          if (state.stage === 'export' && state.job === job && count.pages > 0) {
            setText(description, [parts[0], parts[1], tn('pages', count.pages), ...parts.slice(2)].join(' · '));
          }
        }).catch(() => {});
      }
    }
    if (!info.outputs.epub || !info.epubcheck) continue; // an XTC only, or a job from before the check was recorded
    const lead = reviewed.length > 1 ? `${info.name}: ` : '';
    const found = file.findings.filter((finding) => finding.kind === 'epubcheck_warning');
    if (info.epubcheck === 'passed') {
      checks.push(h('li', { class: 'export-check check-ok' }, lead + t('epubcheck_passed')));
    } else if (info.epubcheck === 'passed_with_warnings') {
      checks.push(h('li', { class: 'export-check check-warn' }, h('details', null, h('summary', null, lead + tn('epubcheck_warnings', found.length || 1)), h('ul', null, ...found.map((finding) => h('li', null, finding.message))))));
    } else {
      checks.push(h('li', { class: 'export-check check-off' }, lead + t('epubcheck_not_run')));
    }
  }
  $('export-files').replaceChildren(...rows);
  $('export-checks').replaceChildren(...checks);
  setText($('export-status'), warnings ? tn('export_warnings', warnings) : t('export_ready'));
  const seen = tn('findings_seen', warnings);
  const first = reviewed[0];
  const summary = [];
  if (reviewed.length === 1) {
    summary.push(first.info.name);
    if (run.files[first.index].book) summary.push(tn('pages', run.files[first.index].book.pages));
  } else {
    summary.push(t('export_files', { n: reviewed.length }));
  }
  summary.push(t('reviewed_seen', { findings: seen }));
  if (reviewed.length === 1 && run.files[first.index].seconds !== null) {
    summary.push(t('converted_in', { time: formatDuration(run.files[first.index].seconds) }));
  }
  setText($('export-summary'), summary.join(' · '));
  // the applied values, not a style name: the job does not keep one
  // an EPUB-only job: only Focus Mode reached the file, the Xteink sets size and spacing
  const style = job.options.style;
  const values = makesXtc() ? [t('style_value_size', { n: style.font_size }), t('style_value_spacing', { n: style.line_height }), t('style_value_margins', { n: style.margin_x })] : [];
  if (style.focus_mode) values.push(t('style_value_focus', { weight: t(`focus_weight_${style.focus_weight}`).toLowerCase() }));
  $('export-style').hidden = values.length === 0;
  setText($('export-style'), values.length ? t('style_applied', { values: values.join(', ') }) : '');
  const others = job.files.map((info, index) => ({ info, index })).filter(({ info }) => !isConverted(info));
  $('export-others').hidden = others.length === 0;
  $('export-others-list').replaceChildren(
    ...others.map(({ info, index }) => h('li', null, h('span', null, `${info.name} · ${t('review_not_converted')}`), ' ', h('a', { href: '#', onclick: (event) => { event.preventDefault(); showFile(index); } }, t('review_it')))),
  );
}

export function backToReview() {
  showReview();
}

export function onFontChange() {
  if ($('font').value === '__upload__') {
    $('font').value = state.review.live.style.font;
    $('font-upload').click();
    return;
  }
  syncWeights(state.review.live.style.font_weight);
  onLiveChange();
}

export async function onFontUpload() {
  const [file] = $('font-upload').files;
  $('font-upload').value = '';
  if (!file) return;
  const form = new FormData();
  form.append('files', file, file.name);
  try {
    const [uploaded] = await getJson(URLS.fontUpload(), { method: 'POST', body: form });
    const existing = state.review.fonts.find((item) => item.family === uploaded.family);
    if (existing) existing.weights = [...new Set([...existing.weights, ...uploaded.weights])].sort((a, b) => a - b);
    else state.review.fonts.push(uploaded);
    const uploadOption = $('font').querySelector('option[value="__upload__"]');
    if (![...$('font').options].some((option) => option.value === uploaded.family)) {
      $('font').insertBefore(h('option', { value: uploaded.family }, uploaded.family), uploadOption);
    }
    $('font').value = uploaded.family;
    syncWeights(uploaded.weights[0]);
    onLiveChange();
  } catch (error) {
    setText($('panel-error'), error.message || t('font_error'));
    $('panel-error').hidden = false;
  }
}

export async function copyStyle() {
  try {
    await navigator.clipboard.writeText(JSON.stringify(readStyle(), null, 2));
    setText($('copy-status'), t('style_copied'));
  } catch (error) {
    setText($('copy-status'), error.message);
  }
}

export async function rebuild(options, fail) {
  try {
    const init = { method: 'POST', headers: JSON_HEADERS, body: JSON.stringify(options) };
    const job = await getJson(URLS.rebuild(state.job.id), init);
    if (state.carry && !state.carry.toJob) state.carry.toJob = job.id;
    location.hash = `#job=${job.id}`;
    return true;
  } catch (error) {
    fail(error.message);
    return false;
  }
}

export async function applyChanges() {
  const review = state.review;
  review.applying = true;
  $('apply').disabled = true;
  setText($('apply'), t('applying'));
  $('panel-error').hidden = true;
  updateApply();
  const selected = review.selected ? { page: review.selected.page, message: review.selected.message } : null;
  state.carry = {
    fromJob: state.job.id,
    toJob: null,
    fileIndex: review.fileIndex,
    anchor: anchorHere(),
    selected,
    format: review.format,
    view: review.view,
  };
  const options = {
    ...state.job.options,
    formats: state.job.options.formats.map((format) => {
      if (format !== 'xtch' && format !== 'xtc') return format;
      return review.live.style.mode === 'xth' ? 'xtch' : 'xtc';
    }),
    style: review.live.style,
    size: review.live.size,
  };
  const ok = await rebuild(options, (message) => {
    setText($('panel-error'), message);
    $('panel-error').hidden = false;
  });
  if (ok || state.review !== review) return;
  state.carry = null;
  review.applying = false;
  setText($('apply'), t('apply_to_book'));
  updateApply();
}

export async function tryAgain() {
  $('try-again').disabled = true;
  const ok = await rebuild(state.job.options, (message) => {
    setText($('review-note'), message);
    $('review-note').hidden = false;
  });
  if (!ok) $('try-again').disabled = false;
}

// The job and all its files leave the server, after the user says yes. Then the page starts over
// on Select, which reads Recent conversions again. A job that is gone already (deleted in
// another tab) counts as deleted.
export async function deleteJob(event) {
  if (!window.confirm(t('delete_confirm'))) return;
  const mine = state.sequence;
  const id = state.job.id;
  const button = event.currentTarget;
  const errorLine = $(button.id === 'delete-job' ? 'delete-error' : 'process-delete-error');
  button.disabled = true;
  setText(button, t('deleting'));
  errorLine.hidden = true;
  try {
    await request(URLS.job(id), { method: 'DELETE' });
  } catch (error) {
    if (mine !== state.sequence) return;
    if (error.status !== 404) {
      button.disabled = false;
      setText(button, t('delete_job'));
      setText(errorLine, error.message);
      errorLine.hidden = false;
      button.focus(); // it lost the focus while it was disabled
      return;
    }
  }
  if (mine !== state.sequence) return;
  history.replaceState(null, '', location.pathname + location.search);
  route().catch(pageFailed);
}

export function onFileSwitch() {
  const review = state.review;
  if (review.panelOpen) closePanel(false, false); // the panes are reloaded for the other file
  review.fileIndex = Number($('review-file').value);
  renderReview();
  loadFilePreview();
}

// A live preview that waits for its timer or is on its way reads review.pages, which is emptied here.
export function onViewChange() {
  const review = state.review;
  review.view = $('view-as').value;
  if (!review.pages) return;
  const anchor = anchorHere();
  clearTimeout(review.liveTimer);
  if (review.liveAbort) review.liveAbort.abort();
  review.pages = null;
  loadPages(anchor);
}

export function onFormatChange() {
  const review = state.review;
  const info = state.job.files[review.fileIndex];
  const selected = document.querySelector('input[name="preview-format"]:checked').value;
  review.format = selected === 'epub' ? 'epub' : (info.outputs.xtch ? 'xtch' : 'xtc');
  if (!review.pages) {
    renderReview();
    return;
  }
  const anchor = anchorHere();
  clearTimeout(review.liveTimer);
  if (review.liveAbort) review.liveAbort.abort();
  review.pages = null;
  renderReview();
  loadPages(anchor);
}

export function onKey(event) {
  if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return;
  if (state.stage !== 'review' || !state.review || !state.review.pages) return;
  if (event.altKey || event.ctrlKey || event.metaKey || event.shiftKey) return;
  if (event.target.closest && event.target.closest('button, a, input, select, textarea, [role="slider"]')) return;
  event.preventDefault();
  step(event.key === 'ArrowRight' ? 1 : -1);
}

