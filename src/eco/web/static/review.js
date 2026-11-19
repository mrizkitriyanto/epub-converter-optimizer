import { $, JSON_HEADERS, LIVE_DELAY_MS, URLS, VIEW_FOR_FIRMWARE, errorText, focusStage, formatDuration, formatSize, getJson, h, readAsDataUrl, request, route, setStage, setText, state, t, tn } from './core.js';
import { apply, findingParts, isConverted } from './job.js';

const STYLE_IDS = {
  font: 'font', font_size: 'style-font-size', font_weight: 'font-weight', line_height: 'line-height',
  margin: 'margin', align: 'align', hyphenate: 'hyphenate', lang: 'style-lang', mode: 'color-mode',
  dither: 'dither', dither_strength: 'dither-strength', negative: 'negative', bar_position: 'bar-position',
  bar_line: 'bar-line', bar_page: 'bar-page', bar_book_percent: 'bar-book-percent',
  bar_chapter_page: 'bar-chapter-page', bar_chapter_percent: 'bar-chapter-percent',
  bar_chapter_title: 'bar-chapter-title', bar_chapter_marks: 'bar-chapter-marks',
  bar_full_width: 'bar-full-width', bar_font_size: 'bar-font-size', bar_edge_margin: 'bar-edge-margin',
  bar_side_margin: 'bar-side-margin', orientation: 'orientation',
};
const STYLE_FLAGS = new Set([
  'hyphenate', 'dither', 'negative', 'bar_line', 'bar_page', 'bar_book_percent',
  'bar_chapter_page', 'bar_chapter_percent', 'bar_chapter_title', 'bar_chapter_marks', 'bar_full_width',
]);
const STYLE_NUMBERS = new Set([
  'font_size', 'font_weight', 'line_height', 'margin', 'dither_strength', 'bar_font_size',
  'bar_edge_margin', 'bar_side_margin', 'orientation',
]);

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
    panelOpen: false,
    applying: false,
    live: { style: { ...job.options.style }, size: job.options.size },
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
  setText($('apply'), t('apply'));
  $('apply').disabled = true;
  $('try-again').disabled = false;
  $('delete-job').disabled = false;
  setText($('delete-job'), t('delete_job'));
  $('delete-error').hidden = true;
}

export function showReview() {
  setStage('review');
  if (!state.review || state.review.jobId !== state.job.id) {
    state.review = newReview(state.job);
    resetReviewDom();
  }
  $('view-as').value = state.review.view;
  renderReview();
  focusStage();
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
  $('download').hidden = !converted;
  if (converted) {
    $('download').href = URLS.fileDownload(job.id, review.fileIndex, review.format);
    setText($('download'), t(`download_${review.format}`));
  }
  const epubToggle = document.querySelector('input[name="preview-format"][value="epub"]');
  const xtcToggle = document.querySelector('input[name="preview-format"][value="xtc"]');
  epubToggle.disabled = !info.outputs.epub;
  xtcToggle.disabled = !xtc;
  (review.format === 'epub' ? epubToggle : xtcToggle).checked = true;
  document.querySelector('.approx').hidden = review.format !== 'epub';
  $('change-settings').hidden = !converted;
  $('try-again').hidden = job.files.some(isConverted); // with nothing converted, trying again is the one action
  renderFilePick(job);
  renderNote(job, info, converted);
  $('review-grid').hidden = !converted;
  renderFindings(file);
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
  const key = `${job.id}:${job.files.map(isConverted).join()}`; // two jobs can look alike
  if (select.dataset.key !== key) {
    select.dataset.key = key;
    const label = (file) => (isConverted(file) ? file.name : `${file.name} (${t('review_not_converted')})`);
    select.replaceChildren(...job.files.map((file, i) => h('option', { value: String(i) }, label(file))));
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

export function renderFindings(file) {
  const list = $('findings-list');
  const key = `${state.job.id}:${state.review.fileIndex}:${file.findings.length}`;
  setText($('findings-title'), t('findings_title', { n: file.findings.length }));
  $('findings-empty').hidden = file.findings.length > 0;
  if (list.dataset.key === key) return;
  list.dataset.key = key;
  list.replaceChildren(...file.findings.map(findingItem));
}

export function findingItem(finding) {
  const parts = findingParts(finding);
  if (!(finding.page > 0)) return h('li', { class: 'finding plain' }, ...parts);
  const button = h('button', { type: 'button', class: 'finding', onclick: () => selectFinding(finding, button) }, ...parts);
  if (state.review.selected === finding) button.setAttribute('aria-current', 'true');
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
    if (pages.device_pages > 0) goTo(pageOfAnchor(pages, anchor) || firstPageOfSelected(pages) || 1);
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

export function selectFinding(finding, button) {
  const review = state.review;
  review.selected = finding;
  for (const other of $('findings-list').querySelectorAll('[aria-current]')) other.removeAttribute('aria-current');
  button.setAttribute('aria-current', 'true');
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
  if (review.panelOpen && liveDirty()) {
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
  setText($('device-caption'), t('device_caption', { page: review.page, total: review.pages.device_pages }));
}

export function liveDirty() {
  const { live } = state.review;
  const options = state.job.options;
  return JSON.stringify(live.style) !== JSON.stringify(options.style) || live.size !== options.size;
}

export function liveQuery() {
  const review = state.review;
  const format = review.format === 'epub'
    ? 'epub'
    : (review.live.style.mode === 'xth' ? 'xtch' : 'xtc');
  const params = new URLSearchParams({
    format,
    view: review.view,
    style: JSON.stringify(review.live.style),
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
    setText($('device-status'), '');
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
}

export async function loadFonts() {
  const review = state.review;
  try {
    review.fonts = await getJson(URLS.fonts(state.job.id));
    $('font').replaceChildren(
      ...review.fonts.map((item) => h('option', { value: item.family }, item.family)),
      h('option', { value: '__upload__' }, t('font_upload')),
    );
    $('font').value = review.live.style.font;
    syncWeights(review.live.style.font_weight);
  } catch (error) {
    setText($('panel-error'), error.message);
    $('panel-error').hidden = false;
  }
}

export async function openPanel() {
  const review = state.review;
  const options = state.job.options;
  review.panelOpen = true;
  review.live = { style: { ...options.style }, size: options.size };
  writeStyle(review.live.style);
  $('live-size').value = options.size;
  $('settings-panel').hidden = false;
  $('review-grid').classList.add('with-panel');
  $('change-settings').setAttribute('aria-expanded', 'true');
  $('panel-error').hidden = true;
  setText($('copy-status'), '');
  await loadFonts();
  updateApply();
  $('font').focus();
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

export function updateApply() {
  $('apply').disabled = !liveDirty() || state.review.applying;
}

export function onLiveChange() {
  const review = state.review;
  review.live = { style: readStyle(), size: $('live-size').value };
  updateApply();
  if (review.pages && review.pages.device_pages > 0) refreshDevice();
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
  form.append('file', file, file.name);
  try {
    const uploaded = await getJson(URLS.fontUpload(state.job.id), { method: 'POST', body: form });
    const existing = state.review.fonts.find((item) => item.family === uploaded.family);
    if (existing) existing.weights = [...new Set([...existing.weights, ...uploaded.weights])].sort((a, b) => a - b);
    else state.review.fonts.push(uploaded);
    const uploadOption = $('font').querySelector('option[value="__upload__"]');
    $('font').insertBefore(h('option', { value: uploaded.family }, uploaded.family), uploadOption);
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
  review.applying = false;
  setText($('apply'), t('apply'));
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
// on Select files, which reads Recent conversions again. A job that is gone already (deleted in
// another tab) counts as deleted.
export async function deleteJob() {
  if (!window.confirm(t('delete_confirm'))) return;
  const mine = state.sequence;
  const id = state.job.id;
  const button = $('delete-job');
  button.disabled = true;
  setText(button, t('deleting'));
  $('delete-error').hidden = true;
  try {
    await request(URLS.job(id), { method: 'DELETE' });
  } catch (error) {
    if (mine !== state.sequence) return;
    if (error.status !== 404) {
      button.disabled = false;
      setText(button, t('delete_job'));
      setText($('delete-error'), error.message);
      $('delete-error').hidden = false;
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
  if (event.target.closest && event.target.closest('input, select, textarea')) return;
  event.preventDefault();
  step(event.key === 'ArrowRight' ? 1 : -1);
}

