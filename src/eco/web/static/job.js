import { $, MIN_SAMPLE_MS, QUEUE_POLL_MS, REPLAY_GAP_MS, STAGE_NAME, STATE_NAME, URLS, approximateLeft, focusStage, getJson, h, setStage, setText, showBanner, state, t, tn } from './core.js';
import { renderReview, showReview } from './review.js';

// ------------------------------------------------ a job and its events

export const isActive = (job) => job.status === 'queued' || job.status === 'running';
export const isConverted = (file) => Boolean(file.outputs && Object.keys(file.outputs).length);

export function newFileRun() {
  return { status: 'waiting', stages: {}, page: null, anchor: null, rate: null, findings: [], seconds: null };
}

export function newRun(job) {
  return { current: null, files: job.files.map(newFileRun) };
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
  if (event.type === 'file') {
    const target = run.files[event.index];
    if (!target) return;
    if (event.status === 'started') {
      run.current = event.index;
      target.status = 'running';
    } else if (event.status === 'done') {
      target.status = 'done';
      target.seconds = typeof event.seconds === 'number' ? event.seconds : null;
    } else if (event.status === 'failed') {
      target.status = 'failed';
    }
  } else if (event.type === 'stage' && file) {
    file.stages[event.stage] = event.status;
  } else if (event.type === 'page' && file) {
    samplePages(file, event, replaying);
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
  if (state.stage === 'processing') showReview();
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

// The stages a file goes through. A Markdown file has no PDF to read, an EPUB is only
// optimized, and a PDF made into page images has nothing to fix.
export function stagesFor(file, options) {
  let names = ['optimize'];
  if (file.kind === 'md') names = ['epub', 'optimize'];
  if (file.kind === 'pdf') names = ['read', 'layout', 'fix', 'epub', 'optimize'];
  if (file.kind === 'pdf' && options.mode === 'pages') names = names.filter((name) => name !== 'fix');
  if (options.formats.some((format) => format.startsWith('xtc'))) names.push('xtc');
  return names;
}

// 'reused' is a stage that sent no event because the PDF was read before: its result is in the
// extraction cache, and the stages after it have started.
export function stageStatus(file, names, name) {
  const seen = file.stages[name];
  if (seen === 'finished') return 'done';
  if (seen === 'started') return 'now';
  const later = names.slice(names.indexOf(name) + 1).some((other) => file.stages[other]);
  return later || file.status === 'done' ? 'reused' : 'todo';
}

export function fractionDone(file, names) {
  if (file.status === 'done') return 1;
  let done = 0;
  for (const name of names) {
    const status = stageStatus(file, names, name);
    if (status === 'done' || status === 'reused') done += 1;
    else if (status === 'now' && name === 'layout' && file.page && file.page.total > 0) {
      done += file.page.done / file.page.total;
    }
  }
  return done / names.length;
}

export function pageLine(file) {
  if (!file.page) return '';
  const parts = [t('page_of', { done: file.page.done, total: file.page.total })];
  if (file.rate > 0 && file.page.done < file.page.total) {
    parts.push(approximateLeft((file.page.total - file.page.done) / file.rate));
  }
  return parts.join(' · ');
}

export function queueLine(job, run) {
  if (job.status === 'queued' && run.current === null) {
    return job.position > 0 ? tn('queue_waiting', job.position) : t('queue_starting');
  }
  const next = job.files[(run.current === null ? 0 : run.current) + 1];
  return next ? t('queue_next', { name: next.name }) : '';
}

export function showProcessing() {
  setStage('processing');
  renderProcessing();
  focusStage();
}

export function renderProcessing() {
  const { job, run } = state;
  const index = run.current === null ? 0 : run.current;
  const info = job.files[index];
  const file = run.files[index];
  const names = stagesFor(info, job.options);
  const position = t('file_of', { n: index + 1, total: job.files.length });
  setText($('file-title'), job.files.length > 1 ? `${info.name} (${position})` : info.name);
  const fraction = fractionDone(file, names);
  $('bar').setAttribute('aria-valuenow', String(Math.round(fraction * 100)));
  $('bar-fill').style.width = `${fraction * 100}%`;
  setText($('page-line'), pageLine(file));
  renderStages(names, file);
  setText($('queue-line'), queueLine(job, run));
  renderFeed(file, index);
  const problem = state.lost ? t('error_stopped') : state.cancelError;
  $('process-error').hidden = problem === '';
  setText($('process-error'), problem);
  setText($('cancel'), state.cancelling ? t('cancelling') : t('cancel'));
  $('cancel').disabled = state.cancelling || state.lost;
}

// The rows are made once for a set of stages and then only change their state, so a screen
// reader hears what changed and not the whole list again.
export function renderStages(names, file) {
  const list = $('stages');
  if (list.dataset.names !== names.join()) {
    list.dataset.names = names.join();
    list.replaceChildren(
      ...names.map((name) =>
        h(
          'li',
          { class: 'stage-row todo', 'data-stage': name },
          h('span', { class: 'stage-mark', 'aria-hidden': 'true' }),
          h('span', { class: 'stage-name' }, STAGE_NAME[name]()),
          h('span', { class: 'visually-hidden' }),
          h('span', { class: 'stage-note' }),
        ),
      ),
    );
  }
  for (const row of list.children) {
    const status = stageStatus(file, names, row.dataset.stage);
    if (row.dataset.status === status) continue;
    row.dataset.status = status;
    const shown = status === 'reused' ? 'done' : status;
    row.className = `stage-row ${shown}`;
    setText(row.children[2], ` (${STATE_NAME[shown]()})`);
    setText(row.children[3], status === 'reused' ? `· ${t('state_reused')}` : '');
  }
}

export function findingParts(finding) {
  const parts = [];
  if (finding.page > 0) parts.push(h('span', { class: 'where' }, t('finding_page', { page: finding.page })), ' ');
  if (finding.level === 'warning') parts.push(h('span', { class: 'tag-warning' }, t('finding_warning')), ' ');
  parts.push(finding.message);
  return parts;
}

// The feed shows the findings of the file that is being converted, newest at the bottom.
export function renderFeed(file, index) {
  const feed = $('feed');
  if (feed.dataset.file !== String(index) || Number(feed.dataset.count) > file.findings.length) {
    feed.dataset.file = String(index);
    feed.dataset.count = '0';
    feed.replaceChildren();
  }
  const shown = Number(feed.dataset.count);
  const atBottom = feed.scrollTop + feed.clientHeight >= feed.scrollHeight - 8;
  for (const finding of file.findings.slice(shown)) feed.append(h('li', { class: 'feed-item' }, ...findingParts(finding)));
  feed.dataset.count = String(file.findings.length);
  $('feed-empty').hidden = file.findings.length > 0;
  if (atBottom) feed.scrollTop = feed.scrollHeight;
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

