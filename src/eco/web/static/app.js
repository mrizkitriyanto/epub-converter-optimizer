'use strict';

import { $, URLS, dropTokenFromAddress, getJson, route, setText, showBanner, state, t } from './core.js';
import { addFiles, continueWithoutModels, renderDetails, setSetupButtons, showSetup, startConversion, startDownload, syncSettingHints, uploadLibraryFonts, wholeFontSize } from './start.js';
import { apply, cancelJob } from './job.js';
import { applyChanges, approveCurrentFile, backToReview, chooseSavedStyle, closePanel, copyStyle, deleteJob, deleteSavedStyle, explainImage, makeSavedDefault, onFileSwitch, onFontChange, onFontUpload, onFormatChange, onKey, onLiveChange, onReviewDockChange, onViewChange, openPanel, saveSavedStyle, sizeFrameToImage, step, tryAgain } from './review.js';

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
    $('font-size').dataset.edited = 'true';
    $('font-size').value = String(wholeFontSize($('font-size').value));
  });
  for (const id of ['embed-focus', 'embed-focus-strength']) {
    $(id).addEventListener('change', () => { $(id).dataset.edited = 'true'; });
  }
  $('library-font-upload').addEventListener('change', uploadLibraryFonts);
  for (const output of document.querySelectorAll('input[name="output"]')) {
    output.addEventListener('change', () => {
      if (!document.querySelector('input[name="output"]:checked')) output.checked = true;
    });
  }
  $('setup-download').addEventListener('click', () => startDownload(false));
  $('setup-ipv4').addEventListener('click', () => startDownload(true));
  $('setup-skip').addEventListener('click', continueWithoutModels);
  $('models-download').addEventListener('click', showSetup);
  $('cancel').addEventListener('click', cancelJob);
  $('try-again').addEventListener('click', tryAgain);
  $('delete-job').addEventListener('click', deleteJob);
  $('review-delete-job').addEventListener('click', deleteJob);
  $('back-to-review').addEventListener('click', backToReview);
  $('change-settings').addEventListener('click', () => {
    if (state.review.panelOpen) closePanel(true, true);
    else openPanel();
  });
  $('review-file').addEventListener('change', onFileSwitch);
  $('view-as').addEventListener('change', onViewChange);
  for (const format of document.querySelectorAll('input[name="preview-format"]')) {
    format.addEventListener('change', onFormatChange);
  }
  for (const input of $('review-dock').querySelectorAll('input')) {
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
