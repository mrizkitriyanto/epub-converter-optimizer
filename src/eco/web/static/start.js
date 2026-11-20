import { $, DEFAULT_FONT_SIZE, FIRMWARE_ADVICE, JSON_HEADERS, MODELS_NOTE, MODE_HINT, STATUS_NAME, SUPPORTED_FILE, URLS, errorText, focusStage, formatMinutes, formatSize, getJson, h, renderStepper, request, route, setStage, setText, state, t, tn } from './core.js';
import { parseEvent } from './job.js';

// ------------------------------------------------------------ setup gate

// The buttons, the error and the log of the gate belong to the download: they are set when the page
// starts and by the download, never by showing the gate. A download that went on while the user was
// on Select files, and its failure, are what the gate shows when the user comes back.
export function showSetup() {
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

export function continueWithoutModels() {
  state.skipModels = true;
  showSelect();
}

export function setSetupButtons(failed, offerIpv4 = failed) {
  const download = $('setup-download');
  download.disabled = false;
  download.textContent = failed ? t('try_again') : t('setup_button', { mb: state.setup.total_mb });
  $('setup-ipv4').hidden = !offerIpv4;
  $('setup-ipv4').disabled = false;
}

export function showSetupError(lead, detail, hint, offerIpv4 = true) {
  const lines = [h('span', { class: 'block' }, lead)];
  if (detail) lines.push(h('span', { class: 'block muted' }, detail));
  if (hint) lines.push(h('span', { class: 'block' }, hint));
  $('setup-error').replaceChildren(...lines);
  $('setup-error').hidden = false;
  setSetupButtons(true, offerIpv4);
  state.download = 'failed'; // the user may be on Select files, where the gate is out of sight
  renderModelsNote();
}

export async function startDownload(ipv4) {
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

export function listenSetup() {
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

export async function setupEnded(event) {
  if (event.status !== 'done') {
    // The server says when a missing Visual C++ runtime stopped the run. Its message is all there is
    // to tell, and trying over IPv4 cannot help.
    if (event.vc_runtime_missing) showSetupError(event.message, null, null, false);
    else showSetupError(t('setup_stopped'), event.message, t('setup_stopped_hint'));
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

export function showSelect() {
  setStage('select');
  loadDefaultStyle();
  loadLibraryFonts();
  renderModelsNote();
  renderFiles();
  syncSettingHints();
  loadRecent();
  focusStage();
}

export async function loadLibraryFonts() {
  try {
    const fonts = await getJson('/api/fonts');
    $('library-font-list').replaceChildren(...fonts.map((font) => {
      const weights = font.weights.map((weight) => {
        const focus = font.weights.some((other) => other > weight);
        return `${weight} (${t('focus_mode_label')}: ${t(focus ? 'focus_available_yes' : 'focus_available_no')})`;
      }).join(', ');
      const label = `${font.family} · ${weights}`;
      const remove = font.styles ? h('button', {
        type: 'button', onclick: () => removeLibraryFont(font.family),
        'aria-label': t('font_remove', { name: font.family }),
      }, t('font_delete')) : null;
      return h('li', null, label, remove);
    }));
  } catch (error) {
    setText($('library-font-status'), error.message);
  }
}

async function removeLibraryFont(family) {
  if (!window.confirm(t('font_remove', { name: family }))) return;
  try {
    await request(`/api/fonts/${encodeURIComponent(family)}`, { method: 'DELETE' });
    await loadLibraryFonts();
  } catch (error) {
    setText($('library-font-status'), error.message);
  }
}

export async function uploadLibraryFonts() {
  const input = $('library-font-upload');
  if (!input.files.length) return;
  const form = new FormData();
  for (const file of input.files) form.append('files', file, file.name);
  input.value = '';
  try {
    const added = await getJson('/api/fonts', { method: 'POST', body: form });
    setText($('library-font-status'), added.map((item) => `${item.family}: ${item.status}`).join(', '));
    await loadLibraryFonts();
  } catch (error) {
    setText($('library-font-status'), error.message);
  }
}

async function loadDefaultStyle() {
  try {
    const saved = await getJson('/api/styles');
    const chosen = saved.find((item) => item.default && !item.error);
    const style = chosen ? await getJson(`/api/styles/${encodeURIComponent(chosen.name)}`) : null;
    const input = $('font-size');
    if (!input.dataset.edited) input.value = String(style?.font_size || DEFAULT_FONT_SIZE);
    if (!$('embed-focus').dataset.edited) $('embed-focus').checked = Boolean(style?.focus_mode);
    if (!$('embed-focus-strength').dataset.edited) $('embed-focus-strength').value = style?.focus_strength || 'medium';
  } catch (error) {
    // A new job still uses the server's default when this hint cannot load.
  }
}

// Markdown and EPUB files need no model, and neither does a PDF read as page images. While the
// models are missing the note says so, and what became of a download that was started.
export function renderModelsNote() {
  // the note goes when the models are ready, so the keyboard focus must not be on what goes
  if (state.setup.ready && $('models-note').contains(document.activeElement)) $('files-title').focus();
  $('models-note').hidden = state.setup.ready;
  setText($('models-text'), MODELS_NOTE[state.download]());
}

export function showDropErrors(messages) {
  const error = $('drop-error');
  error.replaceChildren(...messages.map((message) => h('span', { class: 'block' }, message)));
  error.hidden = messages.length === 0;
  if (messages.length) error.scrollIntoView({ block: 'nearest' });
}

export function addFiles(list) {
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
export function newChoice(file) {
  const kind = file.name.slice(file.name.lastIndexOf('.') + 1).toLowerCase();
  return { file, kind, scan: kind === 'pdf' ? { status: 'waiting' } : null, controller: null };
}

export function removeFile(index) {
  const [removed] = state.files.splice(index, 1);
  if (removed.controller) removed.controller.abort(); // it is being read now: stop that
  renderFiles();
  const next = $('file-list').querySelector('button');
  (next || $('file-input')).focus();
}

// The server reads the chosen PDFs one at a time, and not while the files are uploaded for the
// conversion: two uploads at once only slow each other down. When one reading ends, however it
// ends, the next starts.
export async function scanNext() {
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

export function pauseScanning() {
  if (state.scanning) state.scanning.controller.abort();
}

export function renderFiles() {
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
export function renderDetails() {
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
export function rowText(choice, options) {
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
export function pdfKind(scan, options) {
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
export function estimateSeconds(scan, options) {
  const rate = scan.seconds_per_page;
  if (options.mode === 'pages') return scan.pages * rate.pages;
  if (options.ocr === 'off') return scan.pages * rate.digital;
  if (options.ocr === 'force') return scan.pages * rate.scanned;
  return (scan.pages - scan.scanned_pages) * rate.digital + scan.scanned_pages * rate.scanned;
}

export function approximateTime(seconds) {
  if (seconds < 45) return t('estimate_short');
  return t('estimate_about', { time: formatMinutes(Math.round(seconds / 60)) });
}

// Everything but page images needs the models, and a PDF converted without them fails.
export function needsModels(options) {
  return !state.setup.ready && options.mode !== 'pages';
}

export function syncSettingHints() {
  setText($('firmware-advice'), FIRMWARE_ADVICE[$('firmware').value]());
  setText($('mode-hint'), MODE_HINT[$('mode').value]());
}

export function wholeFontSize(value) {
  const number = Math.round(parseFloat(value));
  return Number.isNaN(number) ? DEFAULT_FONT_SIZE : Math.min(64, Math.max(16, number));
}

export function readOptions() {
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
    style: {
      ...($('font-size').dataset.edited ? { font_size: wholeFontSize($('font-size').value) } : {}),
      focus_mode: $('embed-focus').checked,
      focus_strength: $('embed-focus-strength').value,
    },
  };
}

export async function startConversion() {
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

export async function loadRecent() {
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

export function recentRow(job) {
  const first = job.files.length ? job.files[0].name : job.id;
  const more = job.files.length - 1;
  const name = more > 0 ? `${first} ${tn('recent_more', more)}` : first;
  const when = new Date(job.created * 1000).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' });
  const status = (STATUS_NAME[job.status] || (() => job.status))();
  return h('li', null, h('a', { href: `#job=${job.id}` }, name), h('span', { class: 'recent-meta' }, `${status} · ${when}`));
}

