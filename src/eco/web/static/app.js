'use strict';

/*
 * The eco workspace. One page with four stages: the setup gate (models missing), Select files and
 * Settings, Processing, and Review & download. The open job is in the address (#job=<id>), so a
 * reload or a link goes back to it: a queued or running job opens Processing, any other Review.
 *
 * The tests read this file, so it keeps four habits:
 * - every text comes from t(...) or tn(...), which read the strings block of the page;
 * - every element is found with $(...);
 * - every address of the API is in URLS;
 * - what the server sends (file names, messages) goes into the page as text, never as markup.
 */
(() => {
  // ---------------------------------------------------------------- basics

  const $ = (id) => document.getElementById(id);
  const STRINGS = JSON.parse($('strings').textContent);

  function t(key, values) {
    const text = STRINGS[key];
    if (text === undefined) return key;
    return text.replace(/\{(\w+)\}/g, (whole, name) =>
      values && name in values ? String(values[name]) : whole,
    );
  }

  const tn = (key, n, values) => t(`${key}_${n === 1 ? 'one' : 'other'}`, { ...values, n });

  function h(tag, props, ...children) {
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

  function setText(element, text) {
    if (element.textContent !== text) element.textContent = text;
  }

  function formatSize(bytes) {
    if (bytes < 1000) return `${bytes} ${t('unit_b')}`;
    if (bytes < 1e6) return `${Math.round(bytes / 1e3)} ${t('unit_kb')}`;
    return `${(bytes / 1e6).toFixed(1)} ${t('unit_mb')}`;
  }

  function formatMinutes(minutes) {
    if (minutes < 60) return `${minutes} ${t('unit_min')}`;
    return `${Math.floor(minutes / 60)} ${t('unit_h')} ${minutes % 60} ${t('unit_min')}`;
  }

  function formatDuration(seconds) {
    const total = Math.max(1, Math.round(seconds));
    if (total < 60) return `${total} ${t('unit_s')}`;
    const rest = total % 60;
    const minutes = formatMinutes(Math.floor(total / 60));
    return rest && total < 3600 ? `${minutes} ${rest} ${t('unit_s')}` : minutes;
  }

  function approximateLeft(seconds) {
    if (seconds < 45) return t('remaining_soon');
    return t('remaining_left', { time: formatMinutes(Math.round(seconds / 60)) });
  }

  const STAGE_NAME = {
    read: () => t('stage_read'),
    layout: () => t('stage_layout'),
    fix: () => t('stage_fix'),
    epub: () => t('stage_epub'),
    optimize: () => t('stage_optimize'),
    xtc: () => t('stage_xtc'),
  };
  const STATE_NAME = {
    done: () => t('state_done'),
    now: () => t('state_now'),
    todo: () => t('state_todo'),
  };
  const STATUS_NAME = {
    queued: () => t('status_queued'),
    running: () => t('status_running'),
    done: () => t('status_done'),
    failed: () => t('status_failed'),
    cancelled: () => t('status_cancelled'),
  };
  const FIRMWARE_ADVICE = {
    any: () => t('firmware_any_advice'),
    stock: () => t('firmware_stock_advice'),
    crosspoint: () => t('firmware_crosspoint_advice'),
    crossink: () => t('firmware_crossink_advice'),
  };
  // The note of Select files while the models are missing: no download started, one runs, or one failed.
  const MODELS_NOTE = {
    idle: () => t('models_missing_note'),
    running: () => t('models_downloading_note'),
    failed: () => t('models_failed_note'),
  };
  const MODE_HINT = {
    auto: () => t('mode_text_hint'),
    reflow: () => t('mode_text_hint'),
    pages: () => t('mode_pages_hint'),
  };
  // The view that matches the firmware the book was made for; CrossInk draws like CrossPoint.
  const VIEW_FOR_FIRMWARE = {
    any: 'crosspoint',
    stock: 'stock',
    crosspoint: 'crosspoint',
    crossink: 'crossink',
  };
  const STEPS = [
    () => t('step_select'),
    () => t('step_settings'),
    () => t('step_processing'),
    () => t('step_review'),
  ];

  const SUPPORTED_FILE = /\.(pdf|md|epub)$/i;
  const JSON_HEADERS = { 'Content-Type': 'application/json' };
  const LIVE_DELAY_MS = 300; // after the last change, before the live preview is asked for
  const QUEUE_POLL_MS = 2000; // a queued job has no event: its position is polled
  const REPLAY_GAP_MS = 250; // a quiet gap this long between two events means the replay of a stream is over
  const MIN_SAMPLE_MS = 500; // page events closer than this are folded into one rate sample
  const DEFAULT_FONT_SIZE = 32;

  // ------------------------------------------------------------------- API

  const URLS = {
    setup: '/api/setup',
    setupDownload: '/api/setup/download',
    setupEvents: '/api/setup/events',
    inspect: '/api/inspect',
    jobs: '/api/jobs',
    job: (id) => `/api/jobs/${id}`,
    events: (id) => `/api/jobs/${id}/events`,
    cancel: (id) => `/api/jobs/${id}/cancel`,
    rebuild: (id) => `/api/jobs/${id}/rebuild`,
    fileDownload: (id, n) => `/api/jobs/${id}/files/${n}/download/epub`,
    pages: (id, n, view) => `/api/jobs/${id}/files/${n}/pages?format=epub&view=${view}`,
    source: (id, n, page) => `/api/jobs/${id}/files/${n}/source/${page}.png`,
    device: (id, n, page, view) => `/api/jobs/${id}/files/${n}/preview/epub/${page}.png?view=${view}`,
    live: (id, n, query) => `/api/jobs/${id}/files/${n}/live.png?${query}`,
    text: (id, n) => `/api/jobs/${id}/files/${n}/text`,
  };

  class ApiError extends Error {
    constructor(message, status) {
      super(message);
      this.status = status || 0;
    }
  }

  // The `error` of any answer that is not 2xx is the text to show.
  async function errorText(response) {
    try {
      const body = await response.json();
      if (typeof body.error === 'string') return body.error;
    } catch (error) {
      // an answer that is not JSON has no text of its own
    }
    return t('error_unknown', { status: response.status });
  }

  async function request(address, init) {
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

  const getJson = async (address, init) => (await request(address, init)).json();

  function readAsDataUrl(file) {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(reader.result);
      reader.onerror = () => reject(new ApiError(t('error_unknown', { status: 0 })));
      reader.readAsDataURL(file);
    });
  }

  // ----------------------------------------------------------------- state

  const state = {
    started: false, // after the first stage is shown, a change of stage moves the focus
    stage: null, // setup, select, processing or review
    setup: null, // GET /api/setup
    skipModels: false, // the user went on from the setup gate without the models; this page load only
    download: 'idle', // the model download this page started: idle, running or failed
    files: [], // the files chosen, not uploaded yet: { file, kind, scan, controller }, see newChoice
    scanning: null, // the chosen PDF that the server is reading now (POST /api/inspect), one at a time
    uploading: false,
    job: null, // GET /api/jobs/{id}
    run: null, // what the events of the job say, per file
    stream: null, // the open event stream of the job
    poller: null, // the timer that polls a queued job
    cancelling: false,
    cancelError: '', // why Cancel did not work
    lost: false, // the stream ended without an end event
    review: null, // the Review stage's own state
    sequence: 0, // a new number at each route: an answer that comes late is dropped
  };

  const SECTIONS = {
    setup: $('stage-setup'),
    select: $('stage-select'),
    processing: $('stage-processing'),
    review: $('stage-review'),
  };

  function setStage(name) {
    state.stage = name;
    for (const [key, section] of Object.entries(SECTIONS)) section.hidden = key !== name;
    renderStepper();
  }

  // After a change of stage the heading of the new stage takes the focus, once it has its text.
  function focusStage() {
    if (state.started) SECTIONS[state.stage].querySelector('h2').focus();
  }

  const showBanner = (text) => {
    const banner = $('banner');
    banner.textContent = text;
    banner.hidden = false;
  };
  const hideBanner = () => {
    $('banner').hidden = true;
  };

  // --------------------------------------------------------------- stepper

  function stepStates() {
    if (state.stage === 'select') {
      return state.files.length
        ? ['done', 'current', 'todo', 'todo']
        : ['current', 'todo', 'todo', 'todo'];
    }
    if (state.stage === 'processing') return ['done', 'done', 'current', 'todo'];
    if (state.stage === 'review') return ['done', 'done', 'done', 'current'];
    return null; // the setup gate comes before the steps
  }

  function renderStepper() {
    const states = stepStates();
    $('stepper').hidden = !states;
    if (states) $('stepper-list').replaceChildren(...states.map((status, i) => stepItem(i, status)));
  }

  function stepItem(index, status) {
    const name = STEPS[index]();
    const completed = status === 'done' ? h('span', { class: 'visually-hidden' }, ` (${t('step_done')})`) : null;
    // Select files and Settings lead back to the start; the later steps have nowhere to lead.
    const content =
      status === 'done' && index < 2
        ? h('a', { class: 'step-link', href: '#', onclick: (event) => onStepLink(event, index) }, name, completed)
        : h('span', { class: 'step-label', 'aria-current': status === 'current' ? 'step' : null }, name, completed);
    return h('li', { class: `step ${status}` }, content);
  }

  // On Select files a step link only moves the focus, to what the step is about. From the other
  // stages the address changes, and the route follows.
  function onStepLink(event, index) {
    if (state.stage !== 'select') return;
    event.preventDefault();
    if (index === 0) $('file-input').focus();
    else $('device').focus();
  }

  // --------------------------------------------------------------- routing

  const jobIdOfAddress = () => (/^#job=([0-9a-f]{16})$/.exec(location.hash) || [])[1] || null;

  async function route() {
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
    if (isActive(job)) showProcessing();
    else showReview();
    listen(job);
    if (job.status === 'queued') pollQueue(job.id);
  }

  function stopWork() {
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

  // The setup gate is the first view while the models are missing, unless the user went on without them.
  function showStart() {
    if (state.setup.ready || state.skipModels) showSelect();
    else showSetup();
  }

  function dropTokenFromAddress() {
    const address = new URL(location.href);
    if (!address.searchParams.has('token')) return;
    address.searchParams.delete('token');
    history.replaceState(null, '', address.pathname + address.search + address.hash);
  }

  // ------------------------------------------------------------ setup gate

  // The buttons, the error and the log of the gate belong to the download: they are set when the page
  // starts and by the download, never by showing the gate. A download that went on while the user was
  // on Select files, and its failure, are what the gate shows when the user comes back.
  function showSetup() {
    setStage('setup');
    const { models, total_mb: total } = state.setup;
    $('model-list').replaceChildren(
      ...models.map((model) =>
        h(
          'li',
          null,
          h('span', { class: 'model-name' }, model.name),
          h('span', { class: 'model-size' }, t('model_size', { mb: model.size_mb })),
        ),
      ),
    );
    setText($('model-total'), t('setup_total', { mb: total }));
    focusStage();
  }

  function continueWithoutModels() {
    state.skipModels = true;
    showSelect();
  }

  function setSetupButtons(failed) {
    const download = $('setup-download');
    download.disabled = false;
    download.textContent = failed ? t('try_again') : t('setup_button', { mb: state.setup.total_mb });
    $('setup-ipv4').hidden = !failed;
    $('setup-ipv4').disabled = false;
  }

  function showSetupError(lead, detail, hint) {
    const lines = [h('span', { class: 'block' }, lead)];
    if (detail) lines.push(h('span', { class: 'block muted' }, detail));
    if (hint) lines.push(h('span', { class: 'block' }, hint));
    $('setup-error').replaceChildren(...lines);
    $('setup-error').hidden = false;
    setSetupButtons(true);
    state.download = 'failed'; // the user may be on Select files, where the gate is out of sight
    renderModelsNote();
  }

  async function startDownload(ipv4) {
    $('setup-download').disabled = true;
    $('setup-ipv4').disabled = true;
    setText($('setup-download'), t('setup_working'));
    $('setup-error').hidden = true;
    $('setup-log').replaceChildren();
    state.download = 'running';
    let response;
    try {
      response = await fetch(
        URLS.setupDownload,
        ipv4 ? { method: 'POST', headers: JSON_HEADERS, body: JSON.stringify({ ipv4: true }) } : { method: 'POST' },
      );
    } catch (error) {
      showSetupError(t('error_unreachable'));
      return;
    }
    // 409: a download is already running (the page was reloaded); its stream replays the log.
    if (response.status !== 202 && response.status !== 409) {
      showSetupError(await errorText(response));
      return;
    }
    listenSetup();
  }

  function listenSetup() {
    const source = new EventSource(URLS.setupEvents);
    let ended = false;
    source.onmessage = (message) => {
      const event = parseEvent(message);
      if (!event) return;
      if (event.type === 'progress') {
        $('setup-log').append(h('li', null, event.message));
      } else if (event.type === 'end') {
        ended = true;
        source.close();
        setupEnded(event);
      }
    };
    source.onerror = () => {
      if (ended) return;
      source.close();
      showSetupError(t('error_stopped'));
    };
  }

  async function setupEnded(event) {
    if (event.status !== 'done') {
      showSetupError(t('setup_stopped'), event.message, t('setup_stopped_hint'));
      return;
    }
    try {
      state.setup = await getJson(URLS.setup);
    } catch (error) {
      showSetupError(error.message);
      return;
    }
    if (!state.setup.ready) {
      showSetupError(t('setup_not_ready'));
      return;
    }
    state.download = 'idle';
    // a user who went on without the models is on Select files: the note goes, and the rows stop warning
    if (state.stage === 'setup') {
      route();
    } else if (state.stage === 'select') {
      renderModelsNote();
      renderDetails();
    }
  }

  // ---------------------------------------------------- select and settings

  function showSelect() {
    setStage('select');
    renderModelsNote();
    renderFiles();
    syncSettingHints();
    loadRecent();
    focusStage();
  }

  // Markdown and EPUB files need no model, and neither does a PDF read as page images. While the
  // models are missing the note says so, and what became of a download that was started.
  function renderModelsNote() {
    // the note goes when the models are ready, so the keyboard focus must not be on what goes
    if (state.setup.ready && $('models-note').contains(document.activeElement)) $('files-title').focus();
    $('models-note').hidden = state.setup.ready;
    setText($('models-text'), MODELS_NOTE[state.download]());
  }

  function showDropErrors(messages) {
    const error = $('drop-error');
    error.replaceChildren(...messages.map((message) => h('span', { class: 'block' }, message)));
    error.hidden = messages.length === 0;
    if (messages.length) error.scrollIntoView({ block: 'nearest' });
  }

  function addFiles(list) {
    const refused = [];
    for (const file of list) {
      if (SUPPORTED_FILE.test(file.name)) state.files.push(newChoice(file));
      else refused.push(t('error_unsupported', { name: file.name }));
    }
    showDropErrors(refused);
    renderFiles();
    scanNext();
  }

  // A file the user chose. A PDF is read by the server before it is converted (`scan`): how many pages
  // it has and how many are scanned. A Markdown or EPUB file has no pages to count and converts in
  // seconds, so it is not read. `scan.status` is waiting, reading, done or error.
  function newChoice(file) {
    const kind = file.name.slice(file.name.lastIndexOf('.') + 1).toLowerCase();
    return { file, kind, scan: kind === 'pdf' ? { status: 'waiting' } : null, controller: null };
  }

  function removeFile(index) {
    const [removed] = state.files.splice(index, 1);
    if (removed.controller) removed.controller.abort(); // it is being read now: stop that
    renderFiles();
    const next = $('file-list').querySelector('button');
    (next || $('file-input')).focus();
  }

  // The server reads the chosen PDFs one at a time, and not while the files are uploaded for the
  // conversion: two uploads at once only slow each other down. When one reading ends, however it
  // ends, the next starts.
  async function scanNext() {
    if (state.scanning || state.uploading) return;
    const entry = state.files.find((choice) => choice.scan && choice.scan.status === 'waiting');
    if (!entry) return;
    state.scanning = entry;
    entry.scan = { status: 'reading' };
    entry.controller = new AbortController();
    const form = new FormData();
    form.append('file', entry.file, entry.file.name);
    try {
      const answer = await getJson(URLS.inspect, { method: 'POST', body: form, signal: entry.controller.signal });
      entry.scan = { ...answer, status: 'done' };
    } catch (error) {
      // Aborted: the file was removed, or the upload of the job began. If it is still here it is read again.
      entry.scan = error.name === 'AbortError' ? { status: 'waiting' } : { status: 'error', message: error.message };
    }
    entry.controller = null;
    state.scanning = null;
    renderDetails();
    scanNext();
  }

  function pauseScanning() {
    if (state.scanning) state.scanning.controller.abort();
  }

  function renderFiles() {
    $('file-list').replaceChildren(
      ...state.files.map((choice, index) =>
        h(
          'li',
          { class: 'file-row' },
          h(
            'div',
            null,
            h('span', { class: 'file-name' }, choice.file.name),
            h('span', { class: 'block file-detail' }),
            h('span', { class: 'block hint file-note' }),
          ),
          h(
            'button',
            {
              type: 'button',
              class: 'link-button',
              'aria-label': t('remove_file_named', { name: choice.file.name }),
              onclick: () => removeFile(index),
            },
            t('remove_file'),
          ),
        ),
      ),
    );
    const count = state.files.length;
    let label = t('start_none');
    if (state.uploading) label = t('uploading');
    else if (count > 0) label = tn('start', count);
    setText($('start'), label);
    $('start').disabled = count === 0 || state.uploading;
    setText($('start-hint'), count === 0 ? t('start_hint') : '');
    $('file-input').disabled = state.uploading;
    $('drop-zone').classList.toggle('busy', state.uploading);
    renderDetails();
    if (state.stage === 'select') renderStepper();
  }

  // The text under each file name. It changes only text, never the rows, so a row that has the
  // keyboard focus keeps it when an answer comes in or a setting changes.
  function renderDetails() {
    const options = readOptions();
    const rows = $('file-list').children;
    state.files.forEach((choice, index) => {
      const { detail, note } = rowText(choice, options);
      const warning = rows[index].querySelector('.file-note');
      setText(rows[index].querySelector('.file-detail'), detail);
      setText(warning, note);
      warning.hidden = note === '';
    });
  }

  // The two lines under the name of a file. `detail` is its size and what is known of the file. `note`
  // is a muted warning: why the PDF could not be read, or why its conversion would not work.
  function rowText(choice, options) {
    const parts = [formatSize(choice.file.size)];
    let note = '';
    if (choice.kind === 'md') {
      parts.push(t('kind_markdown'));
    } else if (choice.kind === 'epub') {
      parts.push(t('kind_epub'));
    } else if (choice.scan.status === 'error') {
      note = choice.scan.message;
    } else if (choice.scan.status !== 'done') {
      parts.push(t('file_reading'));
    } else {
      parts.push(tn('pages', choice.scan.pages), pdfKind(choice.scan, options));
      if (needsModels(options)) note = t('row_needs_models');
      else parts.push(approximateTime(estimateSeconds(choice.scan, options)));
    }
    return { detail: parts.join(' · '), note };
  }

  // Digital, scanned (all the pages or most of them), or partly scanned. OCR is named only when it
  // will run: a PDF made into page images has none, and neither has one with OCR off.
  function pdfKind(scan, options) {
    if (scan.scanned_pages === 0) return t('kind_digital');
    if (scan.scanned_pages * 2 <= scan.pages) {
      return t('kind_partly', { scanned: scan.scanned_pages, pages: scan.pages });
    }
    const ocr = options.mode !== 'pages' && options.ocr !== 'off';
    return ocr ? t('kind_scanned') : t('kind_scanned_no_ocr');
  }

  // What the pipeline will do with the current settings: a PDF made into page images costs the
  // page-image rate for every page. Otherwise OCR off reads every page as a digital one, "every
  // page" as a scanned one, and the automatic setting each page as what it is.
  function estimateSeconds(scan, options) {
    const rate = scan.seconds_per_page;
    if (options.mode === 'pages') return scan.pages * rate.pages;
    if (options.ocr === 'off') return scan.pages * rate.digital;
    if (options.ocr === 'force') return scan.pages * rate.scanned;
    return (scan.pages - scan.scanned_pages) * rate.digital + scan.scanned_pages * rate.scanned;
  }

  function approximateTime(seconds) {
    if (seconds < 45) return t('estimate_short');
    return t('estimate_about', { time: formatMinutes(Math.round(seconds / 60)) });
  }

  // Everything but page images needs the models, and a PDF converted without them fails.
  function needsModels(options) {
    return !state.setup.ready && options.mode !== 'pages';
  }

  function syncSettingHints() {
    setText($('firmware-advice'), FIRMWARE_ADVICE[$('firmware').value]());
    setText($('mode-hint'), MODE_HINT[$('mode').value]());
  }

  function wholeFontSize(value) {
    const number = Math.round(parseFloat(value));
    return Number.isNaN(number) ? DEFAULT_FONT_SIZE : Math.min(96, Math.max(8, number));
  }

  function readOptions() {
    const text = (input) => input.value.trim() || null;
    const formats = Array.from(document.querySelectorAll('input[name="output"]:checked'), (input) => input.value);
    return {
      device: $('device').value,
      firmware: $('firmware').value,
      formats,
      size: $('size').value,
      mode: $('mode').value,
      ocr: $('ocr').value,
      title: text($('book-title')),
      author: text($('book-author')),
      lang: text($('book-lang')),
      font_size: wholeFontSize($('font-size').value),
    };
  }

  async function startConversion() {
    if (state.uploading || state.files.length === 0) return;
    const form = new FormData();
    form.append('options', JSON.stringify(readOptions())); // first: a bad option is refused before a file is written
    for (const choice of state.files) form.append('files[]', choice.file, choice.file.name);
    showDropErrors([]);
    state.uploading = true;
    pauseScanning(); // a reading in progress stops now, and starts again if this upload fails
    renderFiles();
    try {
      const job = await getJson(URLS.jobs, { method: 'POST', body: form });
      state.files = [];
      state.uploading = false;
      location.hash = `#job=${job.id}`;
    } catch (error) {
      state.uploading = false;
      renderFiles();
      showDropErrors([error.message]);
      scanNext();
    }
  }

  async function loadRecent() {
    const mine = state.sequence;
    const status = $('recent-status');
    status.hidden = false;
    setText(status, t('loading'));
    $('recent').replaceChildren();
    try {
      const jobs = await getJson(URLS.jobs);
      if (mine !== state.sequence) return;
      status.hidden = jobs.length > 0;
      setText(status, t('recent_empty'));
      $('recent').replaceChildren(...jobs.map(recentRow));
    } catch (error) {
      if (mine !== state.sequence) return;
      setText(status, t('recent_error', { error: error.message }));
    }
  }

  function recentRow(job) {
    const first = job.files.length ? job.files[0].name : job.id;
    const more = job.files.length - 1;
    const name = more > 0 ? `${first} ${tn('recent_more', more)}` : first;
    const when = new Date(job.created * 1000).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' });
    const status = (STATUS_NAME[job.status] || (() => job.status))();
    return h('li', null, h('a', { href: `#job=${job.id}` }, name), h('span', { class: 'recent-meta' }, `${status} · ${when}`));
  }

  // ------------------------------------------------ a job and its events

  const isActive = (job) => job.status === 'queued' || job.status === 'running';
  const isConverted = (file) => Boolean(file.outputs && file.outputs.epub);

  function newFileRun() {
    return { status: 'waiting', stages: {}, page: null, anchor: null, rate: null, findings: [], seconds: null };
  }

  function newRun(job) {
    return { current: null, files: job.files.map(newFileRun) };
  }

  function parseEvent(message) {
    try {
      return JSON.parse(message.data);
    } catch (error) {
      return null;
    }
  }

  // The stream replays every event of the job and then goes on live. It is closed on `end`: the
  // server ends the response, and a browser would reconnect and replay it all again. A stream
  // that ends without `end` means the server stopped.
  function listen(job) {
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

  function apply(event, replaying) {
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
  function samplePages(file, event, replaying) {
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

  async function finish(id) {
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

  function pollQueue(id) {
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

  let renderQueued = false;
  function scheduleRender() {
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
  function stagesFor(file, options) {
    let names = ['optimize'];
    if (file.kind === 'md') names = ['epub', 'optimize'];
    if (file.kind === 'pdf') names = ['read', 'layout', 'fix', 'epub', 'optimize'];
    if (file.kind === 'pdf' && options.mode === 'pages') names = names.filter((name) => name !== 'fix');
    if (options.formats.some((format) => format.startsWith('xtc'))) names.push('xtc');
    return names;
  }

  // 'reused' is a stage that sent no event because the PDF was read before: its result is in the
  // extraction cache, and the stages after it have started.
  function stageStatus(file, names, name) {
    const seen = file.stages[name];
    if (seen === 'finished') return 'done';
    if (seen === 'started') return 'now';
    const later = names.slice(names.indexOf(name) + 1).some((other) => file.stages[other]);
    return later || file.status === 'done' ? 'reused' : 'todo';
  }

  function fractionDone(file, names) {
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

  function pageLine(file) {
    if (!file.page) return '';
    const parts = [t('page_of', { done: file.page.done, total: file.page.total })];
    if (file.rate > 0 && file.page.done < file.page.total) {
      parts.push(approximateLeft((file.page.total - file.page.done) / file.rate));
    }
    return parts.join(' · ');
  }

  function queueLine(job, run) {
    if (job.status === 'queued' && run.current === null) {
      return job.position > 0 ? tn('queue_waiting', job.position) : t('queue_starting');
    }
    const next = job.files[(run.current === null ? 0 : run.current) + 1];
    return next ? t('queue_next', { name: next.name }) : '';
  }

  function showProcessing() {
    setStage('processing');
    renderProcessing();
    focusStage();
  }

  function renderProcessing() {
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
  function renderStages(names, file) {
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

  function findingParts(finding) {
    const parts = [];
    if (finding.page > 0) parts.push(h('span', { class: 'where' }, t('finding_page', { page: finding.page })), ' ');
    if (finding.level === 'warning') parts.push(h('span', { class: 'tag-warning' }, t('finding_warning')), ' ');
    parts.push(finding.message);
    return parts;
  }

  // The feed shows the findings of the file that is being converted, newest at the bottom.
  function renderFeed(file, index) {
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

  async function cancelJob() {
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

  // ---------------------------------------------------------------- review

  function newReview(job) {
    const first = job.files.findIndex(isConverted);
    return {
      jobId: job.id,
      fileIndex: Math.max(0, first),
      view: VIEW_FOR_FIRMWARE[job.options.firmware] || 'crosspoint',
      pages: null, // GET .../pages for the file and view
      page: 1, // the device page shown, from 1
      loadedFile: null, // the file whose panes are loaded
      pagesSeq: 0,
      sourceShown: null, // the source page shown, from 1
      showing: 'main', // main: the page as converted; live: a page drawn with the new settings
      selected: null, // the finding that was clicked
      panelOpen: false,
      applying: false,
      live: { font: job.options.font_size, size: job.options.size },
      controller: new AbortController(), // for the requests of the panes of this file
      liveTimer: null,
      liveAbort: null,
    };
  }

  function abortReview(review) {
    clearTimeout(review.liveTimer);
    if (review.liveAbort) review.liveAbort.abort();
    review.controller.abort();
  }

  // The settings panel and its buttons, and Try again, are the same elements for every job. A review
  // that begins starts them over, so the panel, "Applying…" and a disabled Try again do not carry on.
  function resetReviewDom() {
    hidePanel();
    $('panel-error').hidden = true;
    setText($('panel-error'), '');
    setText($('apply'), t('apply'));
    $('apply').disabled = true;
    $('try-again').disabled = false;
  }

  function showReview() {
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

  function renderReview() {
    const { job, review } = state;
    const info = job.files[review.fileIndex];
    const file = state.run.files[review.fileIndex];
    const converted = isConverted(info);
    setText($('review-title'), info.name);
    renderChips(info, file, converted);
    $('download').hidden = !converted;
    if (converted) $('download').href = URLS.fileDownload(job.id, review.fileIndex);
    $('change-settings').hidden = !converted;
    $('try-again').hidden = job.files.some(isConverted); // with nothing converted, trying again is the one action
    renderFilePick(job);
    renderNote(job, info, converted);
    $('review-grid').hidden = !converted;
    renderFindings(file);
  }

  function renderChips(info, file, converted) {
    const chips = [];
    if (converted) {
      const time = file.seconds === null ? t('converted') : t('converted_in', { time: formatDuration(file.seconds) });
      chips.push(h('li', { class: 'chip' }, time));
      const after = info.sizes.epub;
      if (after !== null && after !== undefined) {
        const before = info.size === null ? '' : formatSize(info.size);
        const values = { format: t('output_epub'), after: formatSize(after), before };
        const text = info.size === null ? t('chip_size_only', values) : t('chip_size', values);
        chips.push(h('li', { class: 'chip' }, text));
      }
      const warnings = file.findings.filter((finding) => finding.level === 'warning').length;
      const summary = warnings ? tn('warnings', warnings) : t('warnings_none');
      chips.push(h('li', { class: warnings ? 'chip warn' : 'chip' }, summary));
    }
    $('chips').replaceChildren(...chips);
  }

  function renderFilePick(job) {
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

  function renderNote(job, info, converted) {
    let text = '';
    if (!converted) text = info.error || (job.status === 'cancelled' ? t('job_cancelled') : t('file_not_converted'));
    else if (job.status === 'cancelled') text = t('job_cancelled');
    const note = $('review-note');
    note.hidden = text === '';
    setText(note, text);
    note.classList.toggle('problem', !converted);
  }

  function renderFindings(file) {
    const list = $('findings-list');
    const key = `${state.job.id}:${state.review.fileIndex}:${file.findings.length}`;
    setText($('findings-title'), t('findings_title', { n: file.findings.length }));
    $('findings-empty').hidden = file.findings.length > 0;
    if (list.dataset.key === key) return;
    list.dataset.key = key;
    list.replaceChildren(...file.findings.map(findingItem));
  }

  function findingItem(finding) {
    const parts = findingParts(finding);
    if (!(finding.page > 0)) return h('li', { class: 'finding plain' }, ...parts);
    const button = h('button', { type: 'button', class: 'finding', onclick: () => selectFinding(finding, button) }, ...parts);
    if (state.review.selected === finding) button.setAttribute('aria-current', 'true');
    return h('li', null, button);
  }

  // ----------------------------------------------------------- the panes

  function resetPanes() {
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

  async function loadFilePreview() {
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
  async function loadText() {
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
  async function loadPages(anchor) {
    const review = state.review;
    const mine = ++review.pagesSeq;
    setText($('device-status'), t('preview_loading'));
    try {
      const address = URLS.pages(state.job.id, review.fileIndex, review.view);
      const pages = await getJson(address, { signal: review.controller.signal });
      if (state.review !== review || mine !== review.pagesSeq) return; // left, or the view changed
      review.pages = pages;
      setText($('device-status'), pages.device_pages > 0 ? '' : t('error_no_preview'));
      if (pages.device_pages > 0) goTo(pageOfAnchor(pages, anchor) || firstPageOfSelected(pages) || 1);
    } catch (error) {
      if (error.name !== 'AbortError' && mine === review.pagesSeq) setText($('device-status'), error.message);
    }
  }

  const isPdf = () => state.job.files[state.review.fileIndex].kind === 'pdf';

  // device page p shows source page page_map[p - 1]; 0 means the page has no source page
  function sourceOfPage(page) {
    const value = state.review.pages.page_map[page - 1];
    return value > 0 ? value : null;
  }

  function nearestSource(page) {
    const map = state.review.pages.page_map;
    for (let i = page - 1; i < map.length; i += 1) if (map[i] > 0) return map[i];
    for (let i = page - 1; i >= 0; i -= 1) if (map[i] > 0) return map[i];
    return null;
  }

  // the first device page that shows source page `source` or a later one
  function firstPageFrom(pages, source) {
    const map = pages.page_map;
    for (let i = 0; i < map.length; i += 1) if (map[i] > 0 && map[i] >= source) return i + 1;
    for (let i = map.length - 1; i >= 0; i -= 1) if (map[i] > 0) return i + 1;
    return null;
  }

  const firstPageOfSelected = (pages) => {
    const selected = state.review.selected;
    return selected && selected.page > 0 ? firstPageFrom(pages, selected.page) : null;
  };

  // the chapter that holds a device page; a book without a heading has no chapters and is chapter 0
  function chapterOfPage(pages, page) {
    let chapter = 0;
    pages.chapters.forEach(([, first], index) => {
      if (first <= page) chapter = index;
    });
    return chapter;
  }

  function anchorHere() {
    const review = state.review;
    if (!review.pages) return null;
    return isPdf()
      ? { source: review.sourceShown || nearestSource(review.page) }
      : { chapter: chapterOfPage(review.pages, review.page) };
  }

  function pageOfAnchor(pages, anchor) {
    if (!anchor) return null;
    if (anchor.source) return firstPageFrom(pages, anchor.source);
    const chapter = pages.chapters[anchor.chapter];
    return chapter ? chapter[1] : null;
  }

  function goTo(page) {
    const review = state.review;
    const count = review.pages.device_pages;
    review.page = Math.min(Math.max(1, page), count);
    $('prev').disabled = review.page <= 1;
    $('next').disabled = review.page >= count;
    updateSource();
    refreshDevice();
  }

  const step = (delta) => {
    if (state.review && state.review.pages) goTo(state.review.page + delta);
  };

  // A device page with no source page leaves the original where it is.
  function updateSource() {
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

  function setImage(image, address, alt) {
    image.alt = alt;
    if (image.getAttribute('src') !== address) image.setAttribute('src', address);
  }

  function selectFinding(finding, button) {
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
  async function explainImage(image, status) {
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

  function sizeFrameToImage(image, frame) {
    if (image.naturalWidth > 0) frame.style.aspectRatio = `${image.naturalWidth} / ${image.naturalHeight}`;
  }

  // ------------------------------------------------- device page and live

  function refreshDevice() {
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

  function showMain() {
    const review = state.review;
    review.showing = 'main';
    setText($('device-status'), '');
    const address = URLS.device(state.job.id, review.fileIndex, review.page, encodeURIComponent(review.view));
    setImage($('device-img'), address, t('device_alt', { page: review.page }));
    setText($('device-caption'), t('device_caption', { page: review.page, total: review.pages.device_pages }));
  }

  function liveDirty() {
    const { live } = state.review;
    const options = state.job.options;
    return live.font !== options.font_size || live.size !== options.size;
  }

  function liveQuery() {
    const review = state.review;
    const params = new URLSearchParams({
      format: 'epub',
      view: review.view,
      font_size: String(review.live.font),
      size: review.live.size,
    });
    const source = isPdf() ? review.sourceShown || nearestSource(review.page) : null;
    if (source) params.set('page', String(source));
    else params.set('chapter', String(chapterOfPage(review.pages, review.page)));
    return params.toString();
  }

  // A newer request aborts the older one, so an answer that comes late never replaces a newer one.
  async function requestLive() {
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

  function openPanel() {
    const review = state.review;
    const options = state.job.options;
    review.panelOpen = true;
    review.live = { font: options.font_size, size: options.size };
    $('live-font').value = String(options.font_size);
    $('live-font-value').value = String(options.font_size);
    $('live-size').value = options.size;
    $('settings-panel').hidden = false;
    $('review-grid').classList.add('with-panel');
    $('change-settings').setAttribute('aria-expanded', 'true');
    $('panel-error').hidden = true;
    updateApply();
    $('live-font').focus();
  }

  function hidePanel() {
    $('settings-panel').hidden = true;
    $('review-grid').classList.remove('with-panel');
    $('change-settings').setAttribute('aria-expanded', 'false');
  }

  // `restore` puts the page as converted back in place of a live one.
  function closePanel(moveFocus, restore) {
    const review = state.review;
    review.panelOpen = false;
    hidePanel();
    if (restore && review.pages && review.pages.device_pages > 0) refreshDevice();
    if (moveFocus) $('change-settings').focus();
  }

  function updateApply() {
    $('apply').disabled = !liveDirty() || state.review.applying;
  }

  function onLiveChange() {
    const review = state.review;
    review.live = { font: Number($('live-font').value), size: $('live-size').value };
    $('live-font-value').value = String(review.live.font);
    updateApply();
    if (review.pages && review.pages.device_pages > 0) refreshDevice();
  }

  async function rebuild(options, fail) {
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

  async function applyChanges() {
    const review = state.review;
    review.applying = true;
    $('apply').disabled = true;
    setText($('apply'), t('applying'));
    $('panel-error').hidden = true;
    const options = { ...state.job.options, font_size: review.live.font, size: review.live.size };
    const ok = await rebuild(options, (message) => {
      setText($('panel-error'), message);
      $('panel-error').hidden = false;
    });
    if (ok || state.review !== review) return;
    review.applying = false;
    setText($('apply'), t('apply'));
    updateApply();
  }

  async function tryAgain() {
    $('try-again').disabled = true;
    const ok = await rebuild(state.job.options, (message) => {
      setText($('review-note'), message);
      $('review-note').hidden = false;
    });
    if (!ok) $('try-again').disabled = false;
  }

  function onFileSwitch() {
    const review = state.review;
    if (review.panelOpen) closePanel(false, false); // the panes are reloaded for the other file
    review.fileIndex = Number($('review-file').value);
    renderReview();
    loadFilePreview();
  }

  function onViewChange() {
    const review = state.review;
    review.view = $('view-as').value;
    if (!review.pages) return;
    const anchor = anchorHere();
    review.pages = null;
    loadPages(anchor);
  }

  function onKey(event) {
    if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return;
    if (state.stage !== 'review' || !state.review || !state.review.pages) return;
    if (event.altKey || event.ctrlKey || event.metaKey || event.shiftKey) return;
    if (event.target.closest && event.target.closest('input, select, textarea')) return;
    event.preventDefault();
    step(event.key === 'ArrowRight' ? 1 : -1);
  }

  // ------------------------------------------------------------------ init

  function bind() {
    $('file-input').addEventListener('change', (event) => {
      const chosen = Array.from(event.target.files);
      event.target.value = '';
      addFiles(chosen);
    });
    const zone = $('drop-zone');
    for (const name of ['dragenter', 'dragover']) {
      zone.addEventListener(name, (event) => {
        event.preventDefault();
        if (!state.uploading) zone.classList.add('dragging');
      });
    }
    zone.addEventListener('dragleave', (event) => {
      if (!zone.contains(event.relatedTarget)) zone.classList.remove('dragging');
    });
    zone.addEventListener('drop', (event) => {
      event.preventDefault();
      zone.classList.remove('dragging');
      if (!state.uploading) addFiles(Array.from(event.dataTransfer.files));
    });
    // a file dropped beside the zone must not make the browser leave the page
    for (const name of ['dragover', 'drop']) window.addEventListener(name, (event) => event.preventDefault());

    $('start').addEventListener('click', startConversion);
    $('firmware').addEventListener('change', syncSettingHints);
    $('mode').addEventListener('change', syncSettingHints);
    // the estimate of a PDF follows the settings, and so does the warning about the models
    $('device').addEventListener('change', renderDetails);
    $('mode').addEventListener('change', renderDetails);
    $('ocr').addEventListener('change', renderDetails);
    $('font-size').addEventListener('change', () => {
      $('font-size').value = String(wholeFontSize($('font-size').value));
    });
    $('setup-download').addEventListener('click', () => startDownload(false));
    $('setup-ipv4').addEventListener('click', () => startDownload(true));
    $('setup-skip').addEventListener('click', continueWithoutModels);
    $('models-download').addEventListener('click', showSetup);
    $('cancel').addEventListener('click', cancelJob);
    $('try-again').addEventListener('click', tryAgain);
    $('change-settings').addEventListener('click', () => {
      if (state.review.panelOpen) closePanel(true, true);
      else openPanel();
    });
    $('review-file').addEventListener('change', onFileSwitch);
    $('view-as').addEventListener('change', onViewChange);
    $('prev').addEventListener('click', () => step(-1));
    $('next').addEventListener('click', () => step(1));
    $('live-font').addEventListener('input', onLiveChange);
    $('live-size').addEventListener('change', onLiveChange);
    $('apply').addEventListener('click', applyChanges);
    $('close-panel').addEventListener('click', () => closePanel(true, true));
    $('settings-panel').addEventListener('keydown', (event) => {
      if (event.key === 'Escape') closePanel(true, true);
    });
    document.addEventListener('keydown', onKey);

    $('device-img').addEventListener('load', () => {
      sizeFrameToImage($('device-img'), $('device-screen'));
      if (state.review && state.review.showing === 'main') setText($('device-status'), '');
    });
    $('device-img').addEventListener('error', () => explainImage($('device-img'), $('device-status')));
    $('source-img').addEventListener('load', () => {
      sizeFrameToImage($('source-img'), $('source-page'));
      setText($('source-status'), '');
    });
    $('source-img').addEventListener('error', () => explainImage($('source-img'), $('source-status')));
  }

  // A mistake in this script must not leave a blank page: say so, and leave the details in the console.
  function pageFailed(error) {
    showBanner(t('error_script'));
    console.error(error);
  }

  async function init() {
    dropTokenFromAddress();
    bind();
    try {
      state.setup = await getJson(URLS.setup);
    } catch (error) {
      showBanner(error.message);
      return;
    }
    setSetupButtons(false);
    await route();
    state.started = true;
    window.addEventListener('hashchange', () => route().catch(pageFailed));
  }

  init().catch(pageFailed);
})();
