import { newChoice, showSelect } from './start.js';
import { isActive, isConverted, listen, newRun, pollQueue, showProcessing } from './job.js';
import { abortReview, backToReview, rebuild, showReview, step } from './review.js';

'use strict';

/*
 * The eco workspace. One page with four stages: Select (with the model download), Convert,
 * Review, and Export. The open job is in the address (#job=<id>), so a reload
 * or a link goes back to it: a queued or running job opens Convert, any other job opens Review.
 *
 * The tests read this file, so it keeps four habits:
 * - every text comes from t(...) or tn(...), which read the strings block of the page;
 * - every element is found with $(...);
 * - every address of the API is in URLS;
 * - what the server sends (file names, messages) goes into the page as text, never as markup.
 */
// ---------------------------------------------------------------- basics

export const $ = (id) => document.getElementById(id);
export const STRINGS = JSON.parse($('strings').textContent);

export function t(key, values) {
  const text = STRINGS[key];
  if (text === undefined) return key;
  return text.replace(/\{(\w+)\}/g, (whole, name) =>
    values && name in values ? String(values[name]) : whole,
  );
}

export const tn = (key, n, values) => t(`${key}_${n === 1 ? 'one' : 'other'}`, { ...values, n });

export function h(tag, props, ...children) {
  const element = document.createElement(tag);
  for (const [name, value] of Object.entries(props || {})) {
    if (value === null || value === undefined || value === false) continue;
    if (name === 'class') element.className = value;
    else if (name.startsWith('on')) element.addEventListener(name.slice(2), value);
    else element.setAttribute(name, value === true ? '' : value);
  }
  element.append(...children.filter((child) => child !== null && child !== undefined));
  return element;
}

// A mistake in this script must not leave a blank page: say so, and leave the details in the console.
export function pageFailed(error) {
  showBanner(t('error_script'));
  console.error(error);
}

export function setText(element, text) {
  if (element.textContent !== text) element.textContent = text;
}

export function formatSize(bytes) {
  if (bytes < 1000) return `${bytes} ${t('unit_b')}`;
  if (bytes < 1e6) return `${Math.round(bytes / 1e3)} ${t('unit_kb')}`;
  return `${(bytes / 1e6).toFixed(1)} ${t('unit_mb')}`;
}

export function formatMinutes(minutes) {
  if (minutes < 60) return `${minutes} ${t('unit_min')}`;
  return `${Math.floor(minutes / 60)} ${t('unit_h')} ${minutes % 60} ${t('unit_min')}`;
}

export function formatDuration(seconds) {
  const total = Math.max(1, Math.round(seconds));
  if (total < 60) return `${total} ${t('unit_s')}`;
  const rest = total % 60;
  const minutes = formatMinutes(Math.floor(total / 60));
  return rest && total < 3600 ? `${minutes} ${rest} ${t('unit_s')}` : minutes;
}

export function approximateLeft(seconds) {
  if (seconds < 45) return t('remaining_soon');
  return t('remaining_left', { time: formatMinutes(Math.round(seconds / 60)) });
}

export const STAGES = ['read', 'layout', 'fix', 'epub', 'optimize', 'xtc'];
export const STAGE_NAME = {
  read: () => t('stage_read'),
  layout: () => t('stage_layout'),
  fix: () => t('stage_fix'),
  epub: () => t('stage_epub'),
  optimize: () => t('stage_optimize'),
  xtc: () => t('stage_xtc'),
};
export const STATE_NAME = {
  done: () => t('state_done'),
  now: () => t('state_now'),
  todo: () => t('state_todo'),
};
export const STATUS_NAME = {
  queued: () => t('status_queued'),
  running: () => t('status_running'),
  done: () => t('status_done'),
  failed: () => t('status_failed'),
  cancelled: () => t('status_cancelled'),
};
// X4, X4 Pro and X4 v2 Classic share a screen: only the name of their files differs.
export const DEVICE_HINT = {
  x4: 'device_x4_hint',
  'x4-pro': 'device_x4_hint',
  'x4-classic': 'device_x4_hint',
  x3: 'device_x3_hint',
  general: 'device_general_hint',
};
// The note on Select while the models are missing: no download started, one runs, or one failed.
export const MODELS_NOTE = {
  idle: () => t('models_needed', { mb: state.setup.total_mb }),
  running: () => t('models_downloading_note'),
  failed: () => t('models_failed_note'),
};
export const MODE_HINT = {
  auto: () => t('mode_text_hint'),
  pages: () => t('mode_pages_hint'),
};
// The view that matches the firmware the book was made for; CrossInk draws like CrossPoint.
export const VIEW_FOR_FIRMWARE = {
  any: 'crosspoint',
  stock: 'stock',
  crosspoint: 'crosspoint',
  crossink: 'crossink',
};
export const STEPS = [
  () => t('step_select'),
  () => t('step_processing'),
  () => t('step_review'),
  () => t('step_export'),
];

export const SUPPORTED_FILE = /\.(pdf|md|epub)$/i;
export const JSON_HEADERS = { 'Content-Type': 'application/json' };
export const LIVE_DELAY_MS = 300; // after the last change, before the live preview is asked for
export const QUEUE_POLL_MS = 2000; // a queued job has no event: its position is polled
export const REPLAY_GAP_MS = 250; // a quiet gap this long between two events means the replay of a stream is over
export const MIN_SAMPLE_MS = 500; // page events closer than this are folded into one rate sample

// ------------------------------------------------------------------- API

export const URLS = {
  setup: '/api/setup',
  setupDownload: '/api/setup/download',
  setupEvents: '/api/setup/events',
  inspect: '/api/inspect',
  jobs: '/api/jobs',
  job: (id) => `/api/jobs/${id}`,
  events: (id) => `/api/jobs/${id}/events`,
  cancel: (id) => `/api/jobs/${id}/cancel`,
  rebuild: (id) => `/api/jobs/${id}/rebuild`,
  fonts: (id) => `/api/fonts?job=${id}`,
  fontUpload: () => '/api/fonts',
  fileDownload: (id, n, format, library = false) => `/api/jobs/${id}/files/${n}/download/${format}${library ? '?name=library' : ''}`,
  pages: (id, n, format, view) => `/api/jobs/${id}/files/${n}/pages?format=${format}&view=${view}`,
  xtcPages: (id, n, format) => `/api/jobs/${id}/files/${n}/xtc-pages?format=${format}`,
  source: (id, n, page) => `/api/jobs/${id}/files/${n}/source/${page}.png`,
  device: (id, n, format, page, view) => format === 'epub'
    ? `/api/jobs/${id}/files/${n}/preview/epub/${page}.png?view=${view}`
    : `/api/jobs/${id}/files/${n}/xtc/${page}.png`,
  live: (id, n, query) => `/api/jobs/${id}/files/${n}/live.png?${query}`,
  text: (id, n) => `/api/jobs/${id}/files/${n}/text`,
};

export class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.status = status || 0;
  }
}

// The `error` of any answer that is not 2xx is the text to show.
export async function errorText(response) {
  try {
    const body = await response.json();
    if (typeof body.error === 'string') return body.error;
  } catch (error) {
    // an answer that is not JSON has no text of its own
  }
  return t('error_unknown', { status: response.status });
}

export async function request(address, init) {
  let response;
  try {
    response = await fetch(address, init);
  } catch (error) {
    if (error.name === 'AbortError') throw error;
    throw new ApiError(t('error_unreachable'));
  }
  if (!response.ok) throw new ApiError(await errorText(response), response.status);
  return response;
}

export const getJson = async (address, init) => (await request(address, init)).json();

export function readAsDataUrl(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result);
    reader.onerror = () => reject(new ApiError(t('error_unknown', { status: 0 })));
    reader.readAsDataURL(file);
  });
}

// ----------------------------------------------------------------- state

export const state = {
  started: false, // after the first stage is shown, a change of stage moves the focus
  stage: null, // select, processing, review or export
  setup: null, // GET /api/setup
  download: 'idle', // the model download this page started: idle, running or failed
  files: [], // the files chosen, not uploaded yet: { file, kind, scan, controller }, see newChoice
  scanning: null, // the chosen PDF that the server is reading now (POST /api/inspect), one at a time
  uploading: false,
  job: null, // GET /api/jobs/{id}
  run: null, // what the events of the job say, per file
  stream: null, // the open event stream of the job
  poller: null, // the timer that polls a queued job
  clock: null, // the timer that moves the elapsed time of a running file between its events
  cancelling: false,
  cancelError: '', // why Cancel did not work
  lost: false, // the stream ended without an end event
  review: null, // the Review stage's own state
  carry: null, // where Review was when Apply rebuilt the job; it outlives the route to the new job
  sequence: 0, // a new number at each route: an answer that comes late is dropped
};

export const SECTIONS = {
  select: $('stage-select'),
  processing: $('stage-processing'),
  review: $('stage-review'),
  export: $('stage-export'),
};

export function setStage(name) {
  state.stage = name;
  for (const [key, section] of Object.entries(SECTIONS)) section.hidden = key !== name;
  renderStepper();
}

// After a change of stage the heading of the new stage takes the focus, once it has its text.
export function focusStage() {
  if (state.started) SECTIONS[state.stage].querySelector('h2').focus();
}

export const showBanner = (text) => {
  const banner = $('banner');
  banner.textContent = text;
  banner.hidden = false;
};
export const hideBanner = () => {
  $('banner').hidden = true;
};

// --------------------------------------------------------------- stepper

export function stepStates() {
  if (state.stage === 'select') {
    return ['current', 'todo', 'todo', 'todo'];
  }
  if (state.stage === 'processing') return ['done', 'current', 'todo', 'todo'];
  if (state.stage === 'review') return ['done', 'done', 'current', 'todo'];
  if (state.stage === 'export') return ['done', 'done', 'done', 'current'];
  return null;
}

export function renderStepper() {
  const states = stepStates();
  $('stepper').hidden = !states;
  if (states) $('stepper-list').replaceChildren(...states.map((status, i) => stepItem(i, status)));
}

// Going back is a link only where it is valid: Select always starts a new conversion, Convert
// shows the progress while the job still runs, and Review is the way back from Export.
export function stepItem(index, status) {
  const name = STEPS[index]();
  const completed = status === 'done' ? h('span', { class: 'visually-hidden' }, ` (${t('step_done')})`) : null;
  let go = null;
  if (status === 'done' && index === 0) go = (event) => onStepLink(event, index);
  if (index === 1 && state.stage === 'review' && state.job && isActive(state.job)) {
    go = (event) => {
      event.preventDefault();
      showProcessing();
    };
  }
  if (index === 2 && state.stage === 'processing' && state.job && state.job.files.some(isConverted)) {
    go = (event) => {
      event.preventDefault();
      showReview();
    };
  }
  if (index === 2 && state.stage === 'export') {
    go = (event) => {
      event.preventDefault();
      backToReview();
    };
  }
  const content = go
    ? h('a', { class: 'step-link', href: '#', onclick: go }, name, completed)
    : h('span', { class: 'step-label', 'aria-current': status === 'current' ? 'step' : null }, name, completed);
  return h('li', { class: `step ${status}` }, content);
}

// From an open job, the Select link clears the hash and the route follows.
export function onStepLink(event, index) {
  if (index !== 0 || state.stage !== 'select') return;
  event.preventDefault();
  $('file-input').focus();
}

// --------------------------------------------------------------- routing

export const jobIdOfAddress = () => (/^#job=([0-9a-f]{16})$/.exec(location.hash) || [])[1] || null;

export async function route() {
  const mine = ++state.sequence;
  stopWork();
  hideBanner();
  const id = jobIdOfAddress();
  if (!id) {
    showStart();
    return;
  }
  let job;
  try {
    job = await getJson(URLS.job(id));
  } catch (error) {
    if (mine !== state.sequence) return;
    history.replaceState(null, '', location.pathname + location.search);
    showBanner(error.message);
    showStart();
    return;
  }
  if (mine !== state.sequence) return;
  state.job = job;
  state.run = newRun(job);
  // a job that ended with nothing converted shows its failure, or its cancel, on Convert
  if (isActive(job) || !job.files.some(isConverted)) showProcessing();
  else showReview();
  listen(job);
  if (job.status === 'queued') pollQueue(job.id);
}

export function stopWork() {
  if (state.stream) state.stream.source.close();
  clearInterval(state.poller);
  if (state.review) abortReview(state.review);
  Object.assign(state, {
    stream: null,
    poller: null,
    job: null,
    run: null,
    review: null,
    cancelling: false,
    cancelError: '',
    lost: false,
  });
}

// Select is the start: while the models are missing, its notice offers the download.
export function showStart() {
  showSelect();
}

export function dropTokenFromAddress() {
  const address = new URL(location.href);
  if (!address.searchParams.has('token')) return;
  address.searchParams.delete('token');
  history.replaceState(null, '', address.pathname + address.search + address.hash);
}

