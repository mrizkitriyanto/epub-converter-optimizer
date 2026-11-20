import { $, MIN_SAMPLE_MS, QUEUE_POLL_MS, REPLAY_GAP_MS, STAGES, STAGE_NAME, URLS, approximateLeft, focusStage, formatDuration, getJson, h, renderStepper, setStage, setText, showBanner, state, t, tn } from './core.js';
import { mapCells, pagesPerSquare, renderPageMap, squareSize } from './pagemap.js';
import { openReviewAt, rebuild, renderReview, showFile, showReview } from './review.js';

// ------------------------------------------------ a job and its events

export const isActive = (job) => job.status === 'queued' || job.status === 'running';
export const isConverted = (file) => Boolean(file.outputs && Object.keys(file.outputs).length);

// What the events say of one file. `book` and the page numbers draw the page map, `stageTimes` and
// the start and end come from the server's time on each event (`t`), so they survive a reload.
// `shown` is the percent shown so far: it never goes back.
export function newFileRun() {
  return {
    status: 'waiting',
    stages: {},
    stageTimes: {},
    page: null,
    anchor: null,
    rate: null,
    findings: [],
    seconds: null,
    book: null,
    donePages: new Set(),
    startedAt: null,
    endedAt: null,
    error: null,
    shown: 0,
  };
}

export function newRun(job) {
  return { current: null, files: job.files.map(newFileRun), reviewOpened: false, liveAt: 0 };
}

export function parseEvent(message) {
  try {
    return JSON.parse(message.data);
  } catch (error) {
    return null;
  }
}

// The stream replays every event of the job and then goes on live. It is closed on `end`: the
// server ends the response, and a browser would reconnect and replay it all again. A stream
// that ends without `end` means the server stopped.
export function listen(job) {
  const source = new EventSource(URLS.events(job.id));
  const stream = { source, lastAt: null, replaying: true, ended: false };
  state.stream = stream;
  source.onmessage = (message) => {
    if (state.stream !== stream) return;
    const event = parseEvent(message);
    if (!event) return;
    // Only a gap between two events ends the replay: how long the stream took to open says nothing.
    const now = performance.now();
    if (stream.lastAt !== null && now - stream.lastAt >= REPLAY_GAP_MS) stream.replaying = false;
    stream.lastAt = now;
    apply(event, stream.replaying);
    if (event.type === 'end') {
      stream.ended = true;
      source.close();
      finish(job.id);
    }
  };
  source.onerror = () => {
    if (state.stream !== stream || stream.ended) return;
    source.close();
    state.lost = true;
    if (state.stage === 'processing') renderProcessing();
    else showBanner(t('error_stopped'));
  };
}

export function apply(event, replaying) {
  const run = state.run;
  const file = run.files[run.current === null ? 0 : run.current];
  const at = typeof event.t === 'number' ? event.t : null;
  if (event.type === 'file') {
    const target = run.files[event.index];
    if (!target) return;
    if (event.status === 'started') {
      run.current = event.index;
      target.status = 'running';
      target.startedAt = at;
    } else if (event.status === 'done') {
      target.status = 'done';
      target.endedAt = at;
      target.seconds = typeof event.seconds === 'number' ? event.seconds : null;
      // the job as loaded knows nothing of this file's outputs yet: the event brings them
      state.job.files[event.index].outputs = event.outputs || {};
      state.job.files[event.index].sizes = event.sizes || {};
      state.job.files[event.index].epubcheck = event.epubcheck;
      // the first file that converts opens Review; later ones never take the user away from it
      if (!run.reviewOpened && state.stage === 'processing') {
        run.reviewOpened = true;
        showReview();
      }
    } else if (event.status === 'failed') {
      target.status = 'failed';
      target.endedAt = at;
      target.error = event.error || null;
    }
  } else if (event.type === 'stage' && file) {
    file.stages[event.stage] = event.status;
    const times = file.stageTimes[event.stage] || { start: null, end: null };
    if (event.status === 'started') times.start = at;
    else times.end = at;
    file.stageTimes[event.stage] = times;
  } else if (event.type === 'page' && file) {
    samplePages(file, event, replaying);
    if (typeof event.page === 'number') file.donePages.add(event.page);
  } else if (event.type === 'book' && file) {
    file.book = { pages: event.pages, scanned: event.scanned || [], blank: event.blank || [] };
  } else if (event.type === 'finding' && file) {
    file.findings.push({ page: event.page, kind: event.kind, level: event.level, message: event.message });
  }
  scheduleRender();
}

// The remaining time comes from the page rate. A replay delivers many pages in a moment, so it
// only moves the starting point; the rate is measured from live events.
export function samplePages(file, event, replaying) {
  const now = performance.now();
  if (replaying || !file.anchor) {
    file.anchor = { done: event.done, at: now };
  } else if (now - file.anchor.at >= MIN_SAMPLE_MS) {
    const rate = (event.done - file.anchor.done) / ((now - file.anchor.at) / 1000);
    if (rate > 0) file.rate = file.rate ? file.rate * 0.6 + rate * 0.4 : rate;
    file.anchor = { done: event.done, at: now };
  }
  file.page = { done: event.done, total: event.total };
}

// When the job ends: Review when anything converted, else the failure or the cancel stays on
// Convert, with what can be done next.
export async function finish(id) {
  const mine = state.sequence;
  try {
    const job = await getJson(URLS.job(id));
    if (mine !== state.sequence) return;
    state.job = job;
  } catch (error) {
    if (mine === state.sequence) showBanner(error.message);
    return;
  }
  const converted = state.job.files.some(isConverted);
  renderStepper(); // the way back to Convert goes with the running job
  if (state.stage === 'processing' && converted) showReview();
  else if (state.stage === 'processing') renderProcessing();
  else renderReview();
}

export function pollQueue(id) {
  state.poller = setInterval(async () => {
    try {
      const job = await getJson(URLS.job(id));
      if (!state.job || state.job.id !== id) return;
      state.job = job;
      if (job.status !== 'queued') {
        clearInterval(state.poller);
        state.poller = null;
      }
      scheduleRender();
    } catch (error) {
      clearInterval(state.poller);
      state.poller = null;
    }
  }, QUEUE_POLL_MS);
}

export let renderQueued = false;
export function scheduleRender() {
  if (renderQueued) return;
  renderQueued = true;
  requestAnimationFrame(() => {
    renderQueued = false;
    if (!state.job || !state.run) return;
    if (state.stage === 'processing') renderProcessing();
    else if (state.stage === 'review') renderReview();
  });
}

// ------------------------------------------------------------ processing

// The stages a file goes through, as the pipeline runs them: a PDF is read, laid out and fixed
// (not fixed when made into page images); an EPUB stage only builds an EPUB from another input;
// optimizing only happens to an EPUB output; XTC only when it is asked for. A stage the server
// reports that is not expected here is shown too, never dropped.
export function stagesFor(file, options, seen = {}) {
  const formats = options.formats || [];
  const epub = formats.includes('epub');
  const names = [];
  if (file.kind === 'pdf') names.push('read', 'layout');
  if (file.kind === 'pdf' && options.mode !== 'pages') names.push('fix');
  if (epub && file.kind !== 'epub') names.push('epub');
  if (epub) names.push('optimize');
  if (formats.some((format) => format.startsWith('xtc'))) names.push('xtc');
  for (const name of Object.keys(seen)) if (!names.includes(name)) names.push(name);
  return STAGES.filter((name) => names.includes(name));
}

// 'reused' is a stage that sent no event because the PDF was read before: its result is in the
// extraction cache, and the stages after it have started. 'stopped' is the stage a failure ended.
export function stageStatus(file, names, name) {
  const seen = file.stages[name];
  if (seen === 'finished') return 'done';
  if (seen === 'started') return file.status === 'failed' ? 'stopped' : 'now';
  const later = names.slice(names.indexOf(name) + 1).some((other) => file.stages[other]);
  return later || file.status === 'done' ? 'reused' : 'todo';
}

// The expected share of the time of each stage, made to add up to 1 over the stages of the file.
export const STAGE_WEIGHTS = { read: 0.05, layout: 0.55, fix: 0.15, epub: 0.1, optimize: 0.08, xtc: 0.07 };

export function stageWeight(names, name) {
  const total = names.reduce((sum, other) => sum + STAGE_WEIGHTS[other], 0);
  return STAGE_WEIGHTS[name] / total;
}

// How far a stage is: done or reused 1, a running stage its pages, or half when it counts none.
// A stage a failure stopped keeps only the pages it finished.
export function stageFraction(file, names, name) {
  const status = stageStatus(file, names, name);
  if (status === 'done' || status === 'reused') return 1;
  if (status !== 'now' && status !== 'stopped') return 0;
  if (name === 'layout' && file.page && file.page.total > 0) return file.page.done / file.page.total;
  return status === 'stopped' ? 0 : 0.5;
}

// The share of the file that is done. It never shows 100 before the file is done, and the caller
// keeps the largest value shown so far, so it never goes back.
export function progressFraction(file, names) {
  if (file.status === 'done') return 1;
  let done = 0;
  for (const name of names) done += stageWeight(names, name) * stageFraction(file, names, name);
  return Math.min(done, 0.99);
}

export function formatClock(seconds) {
  const total = Math.max(0, Math.floor(seconds));
  const minutes = Math.floor(total / 60);
  return `${minutes}:${String(total % 60).padStart(2, '0')}`;
}

export function elapsedSeconds(file) {
  if (file.startedAt === null) return null;
  const end = file.endedAt !== null ? file.endedAt : Date.now() / 1000;
  return Math.max(0, end - file.startedAt);
}

export function timeLine(file) {
  const elapsed = elapsedSeconds(file);
  const parts = [];
  if (file.status === 'running' && file.rate > 0 && file.page && file.page.done < file.page.total) {
    parts.push(approximateLeft((file.page.total - file.page.done) / file.rate));
  }
  if (elapsed !== null) parts.push(t('elapsed_so_far', { elapsed: formatClock(elapsed) }));
  return parts.join(' · ');
}

export function showProcessing() {
  setStage('processing');
  renderProcessing();
  focusStage();
}

export function outputsText(options) {
  const formats = options.formats || [];
  const epub = formats.includes('epub');
  const xtc = formats.some((format) => format.startsWith('xtc'));
  if (epub && xtc) return t('outputs_both');
  return epub ? t('output_epub') : t('output_xtc');
}

export function renderProcessing() {
  const { job, run } = state;
  const index = run.current === null ? 0 : run.current;
  const info = job.files[index];
  const file = run.files[index];
  const names = stagesFor(info, job.options, file.stages);
  renderQueue(job, run, index);
  setText($('file-title'), info.name);
  const meta = [];
  if (file.book) meta.push(tn('pages', file.book.pages));
  meta.push(t(`device_${job.options.device.replace('-', '_')}`), outputsText(job.options));
  setText($('file-meta'), meta.join(' · '));
  file.shown = Math.max(file.shown, progressFraction(file, names));
  const percent = Math.round(file.shown * 100);
  setText($('percent'), `${percent}%`);
  setText($('time-line'), timeLine(file));
  renderStageBar(names, file);
  renderMap(file);
  // a square of a converted file opens that page in Review: a mouse shortcut, the keyboard has the
  // findings and Review's strip
  $('page-map').onclick = file.status === 'done' && file.book
    ? (event) => {
      const square = event.target.closest('.pm-cell');
      if (!square) return;
      const position = Array.prototype.indexOf.call($('page-map').children, square);
      openReviewAt(position * pagesPerSquare(file.book.pages) + 1);
    }
    : null;
  $('page-map').classList.toggle('clickable', file.status === 'done');
  renderFeed(file, index);
  // what a screen reader hears, at most every 2 seconds
  const now = performance.now();
  if (now - run.liveAt >= 2000 || file.status !== 'running') {
    run.liveAt = now;
    const current = names.find((name) => stageStatus(file, names, name) === 'now');
    setText($('progress-live'), [`${percent}%`, current ? STAGE_NAME[current]() : '', timeLine(file)].filter(Boolean).join(' · '));
  }
  const ended = !isActive(job);
  const converted = job.files.some(isConverted);
  let problem = state.lost ? t('error_stopped') : state.cancelError;
  if (!problem && file.status === 'failed') problem = file.error || t('file_not_converted');
  if (!problem && ended && job.status === 'cancelled') problem = t('job_cancelled');
  $('process-error').hidden = problem === '';
  setText($('process-error'), problem);
  $('process-actions').hidden = !(ended && !converted);
  $('process-try-again').hidden = !(ended && !converted && job.status === 'failed');
  setText($('cancel'), state.cancelling ? t('cancelling') : t('cancel'));
  $('cancel').hidden = ended;
  $('cancel').disabled = state.cancelling || state.lost;
}

// One pill per file when the job has several: a word for its state, and a link to Review once
// it has converted.
export function renderQueue(job, run, index) {
  const queue = $('file-queue');
  queue.hidden = job.files.length < 2;
  if (queue.hidden) return;
  queue.replaceChildren(
    ...job.files.map((info, i) => {
      const status = run.files[i].status;
      let word = t('queue_waiting_short');
      if (status === 'running') word = t('queue_converting');
      else if (status === 'done') word = t('queue_done');
      else if (status === 'failed') word = t('queue_failed');
      else if (job.status === 'cancelled') word = t('queue_cancelled');
      else if (i === index + 1) word = t('queue_next_short');
      const text = `${info.name} · ${word}`;
      const content = isConverted(info)
        ? h('a', { href: '#', onclick: (event) => { event.preventDefault(); showFile(i); } }, text)
        : text;
      return h('li', { class: `queue-pill queue-${status}` }, content);
    }),
  );
}

// The segments are made once for a set of stages and then only change their state, so a screen
// reader hears what changed and not the whole list again.
export function renderStageBar(names, file) {
  const bar = $('stage-bar');
  if (bar.dataset.names !== names.join()) {
    bar.dataset.names = names.join();
    bar.replaceChildren(
      ...names.map((name) => {
        const segment = h(
          'li',
          { class: 'seg seg-todo', 'data-stage': name },
          h('span', { class: 'seg-track', 'aria-hidden': 'true' }, h('span', { class: 'seg-fill' })),
          h('span', { class: 'seg-name' }, t(`stage_short_${name}`), h('span', { class: 'visually-hidden' }, ` (${STAGE_NAME[name]()})`)),
          h('span', { class: 'seg-state' }),
        );
        segment.style.flexGrow = String(stageWeight(names, name) * 10);
        return segment;
      }),
    );
  }
  for (const segment of bar.children) {
    const name = segment.dataset.stage;
    const status = stageStatus(file, names, name);
    const shown = status === 'reused' ? 'done' : status;
    segment.className = `seg seg-${shown}`;
    segment.querySelector('.seg-fill').style.width = `${Math.round(stageFraction(file, names, name) * 100)}%`;
    setText(segment.querySelector('.seg-state'), stageText(file, name, status));
  }
}

export function stageText(file, name, status) {
  if (status === 'reused') return t('stage_reused');
  if (status === 'stopped') return t('stage_stopped');
  if (status === 'todo') return t('stage_waiting');
  if (status === 'done') {
    const times = file.stageTimes[name];
    if (times && times.start !== null && times.end !== null) return t('stage_done_in', { time: formatDuration(times.end - times.start) });
    return t('stage_done');
  }
  if (name === 'layout' && file.page) return t('stage_pages', { done: file.page.done, total: file.page.total });
  return t('stage_in_progress');
}

// The page map needs the book event: a Markdown or EPUB file, and a job from before the event,
// has none, and the findings then take the whole width.
export function renderMap(file) {
  const panel = $('page-map-panel');
  panel.hidden = !file.book;
  $('convert-grid').classList.toggle('no-map', !file.book);
  if (!file.book) return;
  const done = file.donePages;
  // a job from before page numbers were sent: fill the pages in order from the count
  if (done.size === 0 && file.page && file.page.done > 0) {
    const blank = new Set(file.book.blank);
    for (let n = 1, counted = 0; n <= file.book.pages && counted < file.page.done; n += 1) {
      if (blank.has(n)) continue;
      done.add(n);
      counted += 1;
    }
  }
  const complete = file.status === 'done' || file.stages.layout === 'finished' || (!file.stages.layout && Boolean(file.stages.fix || file.stages.epub || file.stages.optimize));
  let current = null;
  if (file.stages.layout === 'started' && file.status === 'running') {
    const blank = new Set(file.book.blank);
    for (let n = 1; n <= file.book.pages; n += 1) {
      if (!done.has(n) && !blank.has(n)) {
        current = n;
        break;
      }
    }
  }
  const warned = file.findings.filter((finding) => finding.level === 'warning' && finding.page > 0).map((finding) => finding.page);
  const cells = mapCells(file.book, { done, current, complete }, warned, 'convert');
  renderPageMap($('page-map'), cells, squareSize(file.book.pages));
  const read = complete ? file.book.pages : Math.min(file.book.pages, done.size + file.book.blank.filter((n) => n < (current || 0)).length);
  const title = `${t('pages_title')} · ${t('pages_read', { done: read, total: file.book.pages })}`;
  setText($('page-map-title'), title);
  $('page-map').setAttribute('aria-label', title);
}

export function findingParts(finding) {
  const parts = [];
  const where = finding.page > 0 ? t('finding_page', { page: finding.page }) : t('whole_book');
  parts.push(h('span', { class: 'where' }, where), ' ');
  if (finding.level === 'warning') parts.push(h('span', { class: 'tag-warning' }, t('finding_warning')), ' ');
  parts.push(finding.message);
  return parts;
}

// The feed shows the warnings of the file that is being converted, newest at the bottom. Notes
// (blank pages, OCR pages) are not counted: Review lists them apart.
export function renderFeed(file, index) {
  const feed = $('feed');
  const warnings = file.findings.filter((finding) => finding.level === 'warning');
  if (feed.dataset.file !== String(index) || Number(feed.dataset.count) > warnings.length) {
    feed.dataset.file = String(index);
    feed.dataset.count = '0';
    feed.replaceChildren();
  }
  const shown = Number(feed.dataset.count);
  for (const finding of warnings.slice(shown)) feed.append(h('li', { class: 'feed-item' }, ...findingParts(finding)));
  feed.dataset.count = String(warnings.length);
  setText($('feed-count'), `(${warnings.length})`);
  $('feed-empty').hidden = warnings.length > 0;
}

export async function cancelJob() {
  state.cancelling = true;
  state.cancelError = '';
  renderProcessing();
  try {
    await getJson(URLS.cancel(state.job.id), { method: 'POST' });
  } catch (error) {
    // 409: the job had just finished, and its end event is on the way
    if (error.status === 409) return;
    state.cancelling = false;
    state.cancelError = error.message;
    renderProcessing();
  }
}

// Nothing converted: the same files again, with the same settings.
export async function retryJob() {
  $('process-try-again').disabled = true;
  const ok = await rebuild(state.job.options, (message) => {
    setText($('process-error'), message);
    $('process-error').hidden = false;
  });
  if (!ok) $('process-try-again').disabled = false;
}
