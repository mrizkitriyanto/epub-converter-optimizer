'use strict';

import { $, URLS, dropTokenFromAddress, getJson, pageFailed, route, setText, showBanner, state } from './core.js';
import { addFiles, chooseStyle, renderDetails, setSetupButtons, showDropErrors, startConversion, startDownload, syncSettingHints, uploadLibraryFonts } from './start.js';
import { cancelJob, retryJob, showProcessing } from './job.js';
import { applyChanges, approveCurrentFile, backToReview, chooseSavedStyle, closePanel, copyStyle, deleteJob, deleteSavedStyle, discardChanges, explainImage, makeSavedDefault, onFileSwitch, onStripClick, onStripKey, onFontChange, onFontUpload, onFormatChange, onKey, onLiveChange, onReviewDockChange, onViewChange, openPanel, saveSavedStyle, showFile, sizeFrameToImage, step, tryAgain } from './review.js';

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
  $('select-style').addEventListener('change', () => {
    $('select-style').dataset.edited = 'true';
    chooseStyle().catch((error) => showDropErrors([error.message]));
  });
  for (const size of document.querySelectorAll('input[name="size"]')) size.addEventListener('change', renderDetails);
  $('library-font-upload').addEventListener('change', uploadLibraryFonts);
  for (const output of document.querySelectorAll('input[name="output"]')) {
    output.addEventListener('change', () => {
      if (!document.querySelector('input[name="output"]:checked')) output.checked = true;
    });
  }
  $('models-download').addEventListener('click', () => startDownload(false));
  $('models-ipv4').addEventListener('click', () => startDownload(true));
  $('cancel').addEventListener('click', cancelJob);
  $('process-try-again').addEventListener('click', retryJob);
  $('process-back').addEventListener('click', () => { location.hash = ''; });
  $('try-again').addEventListener('click', tryAgain);
  $('delete-job').addEventListener('click', deleteJob);
  $('process-delete').addEventListener('click', deleteJob);
  $('discard').addEventListener('click', discardChanges);
  $('page-strip').addEventListener('click', onStripClick);
  $('page-strip').addEventListener('keydown', onStripKey);
  $('review-progress-link').addEventListener('click', showProcessing);
  $('select-focus-help').addEventListener('click', () => {
    const about = $('select-focus-about');
    about.hidden = !about.hidden;
    $('select-focus-help').setAttribute('aria-expanded', String(!about.hidden));
  });
  $('review-ready-link').addEventListener('click', (event) => {
    event.preventDefault();
    showFile(Number(event.currentTarget.dataset.index));
  });
  $('back-to-review').addEventListener('click', backToReview);
  $('convert-another').addEventListener('click', () => { location.hash = ''; });
  $('change-settings').addEventListener('click', () => {
    if (state.review.panelOpen) closePanel(true, true);
    else openPanel();
  });
  $('review-file').addEventListener('change', onFileSwitch);
  $('view-as').addEventListener('change', onViewChange);
  for (const format of document.querySelectorAll('input[name="preview-format"]')) {
    format.addEventListener('change', onFormatChange);
  }
  for (const input of $('review-dock').querySelectorAll('input, select')) {
    input.addEventListener('input', onReviewDockChange);
  }
  $('approve-review').addEventListener('click', approveCurrentFile);
  $('prev').addEventListener('click', () => step(-1));
  $('next').addEventListener('click', () => step(1));
  for (const input of $('page-style').querySelectorAll('input:not(#font-upload), select:not(#font)')) {
    input.addEventListener('input', onLiveChange);
  }
  $('font').addEventListener('change', onFontChange);
  $('font-upload').addEventListener('change', onFontUpload);
  $('live-size').addEventListener('change', onLiveChange);
  $('apply').addEventListener('click', applyChanges);
  $('copy-style').addEventListener('click', copyStyle);
  $('saved-style').addEventListener('change', chooseSavedStyle);
  $('save-style').addEventListener('click', saveSavedStyle);
  $('default-style').addEventListener('click', makeSavedDefault);
  $('delete-style').addEventListener('click', deleteSavedStyle);
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
