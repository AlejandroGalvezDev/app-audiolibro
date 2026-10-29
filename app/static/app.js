'use strict';

(() => {
  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => Array.from(root.querySelectorAll(selector));

  const STATUS_LABELS = {
    queued: 'en cola',
    running: 'generando',
    done: 'completado',
    error: 'error',
  };
  const REGION_NAMES = {
    ES: 'España', MX: 'México', AR: 'Argentina', CO: 'Colombia', US: 'Estados Unidos',
    GB: 'Reino Unido', FR: 'Francia', DE: 'Alemania', BR: 'Brasil', IT: 'Italia',
    PT: 'Portugal', CL: 'Chile', PE: 'Perú', VE: 'Venezuela', UY: 'Uruguay',
  };
  const SELECTION_KEY = 'audiolibro.file';
  const JOB_KEY = 'audiolibro.job';

  let toastTimer = null;

  const state = {
    providers: [],
    providerData: null,
    file: null,
    source: 'upload',
    jobId: null,
    pollTimer: null,
    dynamicVoices: new Set(),
    lastJobStatus: null,
    browser: { data: null, filter: '' },
    jobsTimer: null,
  };

  // ---------------------------------------------------------------- utils
  function escapeHtml(value) {
    return String(value ?? '').replace(/[&<>"']/g, (character) => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
    }[character]));
  }

  function formatBytes(bytes) {
    if (!bytes) return '0 B';
    const units = ['B', 'KB', 'MB', 'GB'];
    const index = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
    const value = bytes / Math.pow(1024, index);
    return `${value.toFixed(index === 0 ? 0 : 1)} ${units[index]}`;
  }

  function formatDate(timestamp) {
    if (!timestamp) return '';
    try {
      return new Date(timestamp * 1000).toLocaleString('es-ES', {
        day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit',
      });
    } catch {
      return '';
    }
  }

  function languageName(code) {
    if (!code) return 'Desconocido';
    const [base, region] = String(code).split('-');
    let language = base;
    try {
      const display = new Intl.DisplayNames(['es'], { type: 'language' });
      language = display.of(base) || base;
      language = language.charAt(0).toUpperCase() + language.slice(1);
    } catch {
      /* Intl no disponible */
    }
    return region ? `${language} · ${REGION_NAMES[region] || region}` : language;
  }

  function regionOf(lang) {
    return String(lang || '').split('-')[1] || String(lang || '');
  }

  function toast(message, type = 'info') {
    const element = $('#toast');
    if (!element) return;
    element.textContent = message;
    element.className = `toast show ${type}`;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => {
      element.className = 'toast';
    }, 5200);
  }

  function setBusy(button, busy, label) {
    if (!button) return;
    if (busy) {
      if (!button.dataset.originalLabel) button.dataset.originalLabel = button.textContent;
      button.disabled = true;
      if (label) button.textContent = label;
    } else {
      button.disabled = false;
      button.textContent = button.dataset.originalLabel || label || button.textContent;
    }
  }

  async function api(path, options = {}) {
    const init = { ...options };
    if (init.body && !(init.body instanceof FormData) && typeof init.body !== 'string') {
      init.headers = { 'Content-Type': 'application/json', ...(init.headers || {}) };
      init.body = JSON.stringify(init.body);
    }
    let response;
    try {
      response = await fetch(path, init);
    } catch (error) {
      throw new Error(`No se pudo conectar con el servidor: ${error.message}`);
    }
    const contentType = response.headers.get('content-type') || '';
    let data = null;
    if (contentType.includes('application/json')) {
      data = await response.json().catch(() => null);
    } else {
      data = await response.text();
    }
    if (!response.ok) {
      let detail = data && typeof data === 'object'
        ? (data.detail || data.message)
        : data;
      if (Array.isArray(detail)) {
        detail = detail.map((item) => item.msg || JSON.stringify(item)).join('; ');
      } else if (detail && typeof detail === 'object') {
        detail = detail.message || JSON.stringify(detail);
      }
      throw new Error(detail || `Error HTTP ${response.status}`);
    }
    return data;
  }

  function statusBadge(status) {
    const css = status === 'done' ? 'ok'
      : status === 'error' ? 'error'
        : status === 'running' ? 'running' : 'queued';
    return `<span class="badge ${css}">${STATUS_LABELS[status] || status}</span>`;
  }

  function providerCard(provider) {
    return `
      <article class="provider card ${provider.available ? 'is-ok' : 'is-off'}">
        <header>
          <h3>${escapeHtml(provider.label)}</h3>
          <span class="badge ${provider.available ? 'ok' : 'off'}">${provider.available ? 'disponible' : 'no disponible'}</span>
        </header>
        <p>${escapeHtml(provider.description)}</p>
        <p class="provider-reason">${escapeHtml(provider.reason || '')}</p>
        <footer>
          <span class="tag">${provider.requires_key ? 'API key' : 'sin clave'}</span>
          <span class="tag">${provider.voices.length} voces</span>
          ${provider.requires_key ? `<span class="tag">${provider.configured ? 'configurado' : 'sin configurar'}</span>` : ''}
          ${provider.enabled === false ? '<span class="tag">desactivado</span>' : ''}
        </footer>
      </article>`;
  }

  // ---------------------------------------------------------------- index
  function currentProvider() {
    return state.providers.find((provider) => provider.id === $('#provider-select')?.value) || null;
  }

  async function loadProviders() {
    const grid = $('#providers-grid');
    if (grid) {
      grid.innerHTML = '<div class="skeleton card"></div><div class="skeleton card"></div><div class="skeleton card"></div>';
    }
    try {
      const data = await api('/api/providers');
      state.providerData = data;
      state.providers = data.providers || [];
      if (grid) {
        grid.innerHTML = state.providers.map(providerCard).join('')
          || '<div class="empty">No hay proveedores TTS registrados.</div>';
      }
      const select = $('#provider-select');
      if (!select) return;
      const previous = select.value;
      select.innerHTML = state.providers.map((provider) => `
        <option value="${escapeHtml(provider.id)}" ${provider.available ? '' : 'disabled'}>
          ${escapeHtml(provider.label)}${provider.available ? '' : ' · no disponible'}
        </option>`).join('');
      const usable = state.providers.find((provider) => provider.available);
      const preferred = state.providers.find((provider) => provider.id === previous && provider.available);
      select.value = (preferred || state.providers.find((provider) => provider.id === data.default_provider) || usable || {}).id || '';
      applyProvider();
    } catch (error) {
      if (grid) grid.innerHTML = `<div class="alert">${escapeHtml(error.message)}</div>`;
      toast(error.message, 'error');
    }
  }

  function applyProvider(preferredVoice = null) {
    const provider = currentProvider();
    const langSelect = $('#lang-select');
    const accentSelect = $('#accent-select');
    const voiceSelect = $('#voice-select');
    const hint = $('#provider-hint');
    const generateButton = $('#generate-btn');
    if (!provider) {
      if (langSelect) langSelect.innerHTML = '';
      if (accentSelect) accentSelect.innerHTML = '<option value="all">Todos</option>';
      if (voiceSelect) voiceSelect.innerHTML = '';
      if (generateButton) generateButton.disabled = true;
      return;
    }

    if (generateButton) generateButton.disabled = !provider.available;
    if (hint) {
      hint.innerHTML = provider.available
        ? escapeHtml(provider.reason || 'Listo para generar')
        : `No disponible: ${escapeHtml(provider.reason || 'sin detalle')}${provider.requires_key ? ' · <a href="/register">configurar</a>' : ''}`;
    }

    const voices = provider.voices || [];
    const languages = [...new Set(voices.map((voice) => voice.lang).filter(Boolean))].sort();
    const previousLang = langSelect.value;
    const voiceLanguage = preferredVoice
      ? (voices.find((voice) => voice.id === preferredVoice) || {}).lang
      : null;
    langSelect.innerHTML = languages.map((lang) => `
      <option value="${escapeHtml(lang)}">${escapeHtml(languageName(lang))}</option>`).join('');
    const selectedLang = [voiceLanguage, previousLang].find((lang) => languages.includes(lang)) || languages[0] || '';
    if (selectedLang) langSelect.value = selectedLang;
    populateAccents(preferredVoice);
    populateVoices(preferredVoice);

    if (provider.id === 'edge' && !state.dynamicVoices.has('edge')) {
      loadDynamicVoices('edge');
    }
  }

  function populateAccents(preferredVoice = null) {
    const provider = currentProvider();
    const langSelect = $('#lang-select');
    const accentSelect = $('#accent-select');
    if (!provider || !accentSelect) return;
    const lang = langSelect.value;
    const regions = [...new Set(
      (provider.voices || [])
        .filter((voice) => voice.lang === lang)
        .map((voice) => regionOf(voice.lang))
        .filter(Boolean),
    )].sort();
    const previous = accentSelect.value;
    let options = '<option value="all">Todos</option>';
    options += regions.map((region) => `
      <option value="${escapeHtml(region)}">${escapeHtml(REGION_NAMES[region] || region)} (${escapeHtml(region)})</option>`).join('');
    accentSelect.innerHTML = options;
    const preferredRegion = preferredVoice
      ? regionOf((provider.voices.find((voice) => voice.id === preferredVoice) || {}).lang)
      : null;
    accentSelect.value = [preferredRegion, previous].find((region) => region === 'all' || regions.includes(region)) || 'all';
  }

  function populateVoices(preferredVoice = null) {
    const provider = currentProvider();
    const voiceSelect = $('#voice-select');
    if (!provider || !voiceSelect) return;
    const lang = $('#lang-select').value;
    const accent = $('#accent-select').value;
    const previous = voiceSelect.value;
    let voices = (provider.voices || []).filter((voice) => voice.lang === lang);
    if (accent && accent !== 'all') {
      const filtered = voices.filter((voice) => regionOf(voice.lang) === accent);
      if (filtered.length) voices = filtered;
    }
    voiceSelect.innerHTML = voices.map((voice) => `
      <option value="${escapeHtml(voice.id)}">${escapeHtml(voice.label || voice.id)}${voice.gender ? ` · ${escapeHtml(voice.gender)}` : ''}</option>`).join('');
    const chosen = [preferredVoice, previous].find((id) => voices.some((voice) => voice.id === id))
      || (voices[0] || {}).id;
    if (chosen) voiceSelect.value = chosen;
  }

  async function loadDynamicVoices(providerId) {
    state.dynamicVoices.add(providerId);
    try {
      const data = await api(`/api/providers/${encodeURIComponent(providerId)}/voices`);
      const provider = state.providers.find((item) => item.id === providerId);
      if (!provider || !data.voices || !data.voices.length) return;
      provider.voices = data.voices;
      if (currentProvider() && currentProvider().id === providerId) {
        applyProvider($('#voice-select').value || null);
      }
    } catch {
      /* se mantiene la lista estática */
    }
  }

  async function playVoicePreview() {
    const providerId = $('#provider-select')?.value;
    const voiceId = $('#voice-select')?.value;
    const audio = $('#preview-audio');
    const status = $('#preview-status');
    const button = $('#preview-voice-btn');
    if (!providerId || !voiceId) {
      toast('Selecciona un proveedor y una voz', 'warning');
      return;
    }
    setBusy(button, true, 'Generando…');
    if (status) status.textContent = 'Generando muestra…';
    try {
      const url = `/api/preview/${encodeURIComponent(providerId)}/${encodeURIComponent(voiceId)}`;
      const response = await fetch(url);
      if (!response.ok) {
        const data = await response.json().catch(() => null);
        throw new Error(data?.detail || `Error ${response.status}`);
      }
      const blob = await response.blob();
      const objectUrl = URL.createObjectURL(blob);
      if (audio) {
        if (audio.src && audio.src.startsWith('blob:')) URL.revokeObjectURL(audio.src);
        audio.src = objectUrl;
        audio.load();
        await audio.play();
      }
      if (status) status.textContent = 'Reproduciendo muestra.';
    } catch (error) {
      if (status) status.textContent = `Error: ${error.message}`;
      toast(error.message, 'error');
    } finally {
      setBusy(button, false);
    }
  }

  function selectSource(source) {
    state.source = source;
    $$('.tab[data-source]').forEach((tab) => {
      tab.classList.toggle('active', tab.dataset.source === source);
    });
    $$('[data-panel]').forEach((panel) => {
      panel.classList.toggle('hidden', panel.dataset.panel !== source);
    });
  }

  function setSelectedFile(file) {
    state.file = file || null;
    const wrapper = $('#selected-file');
    const label = $('#selected-file-name');
    if (!file) {
      wrapper?.classList.add('hidden');
      if (label) label.textContent = '';
      return;
    }
    if (label) label.textContent = `${file.name} · ${formatBytes(file.size)}`;
    wrapper?.classList.remove('hidden');
  }

  function readStoredSelection() {
    try {
      const raw = localStorage.getItem(SELECTION_KEY);
      if (!raw) return;
      const selection = JSON.parse(raw);
      if (selection && selection.path) {
        $('#file-path').value = selection.path;
        selectSource('server');
        toast(`Archivo seleccionado: ${selection.name || selection.path}`);
      }
    } catch {
      /* selección inválida */
    } finally {
      localStorage.removeItem(SELECTION_KEY);
    }
  }

  function renderJob(job) {
    const panel = $('#job-panel');
    if (!panel || !job) return;
    panel.classList.remove('hidden');
    $('#job-id').textContent = job.id;
    $('#job-title').textContent = job.title || job.filename || 'Audiolibro';
    const badge = $('#job-status');
    badge.className = `badge ${job.status === 'done' ? 'ok' : job.status === 'error' ? 'error' : job.status === 'running' ? 'running' : 'queued'}`;
    badge.textContent = STATUS_LABELS[job.status] || job.status;
    $('#job-progress').style.width = `${Math.max(0, Math.min(100, job.progress || 0))}%`;
    $('#job-message').textContent = job.error || job.message || '';

    const chapters = job.chapters || [];
    $('#job-chapters').innerHTML = chapters.map((chapter) => `
      <div class="chapter-row">
        <div>
          <strong>${escapeHtml(chapter.title)}</strong>
          <small>${chapter.chars} caracteres${chapter.duration ? ` · ${chapter.duration}s` : ''}</small>
        </div>
        ${job.status === 'done'
          ? `<a class="btn ghost small" href="${chapter.download_url}">Descargar</a>`
          : '<span class="tag">pendiente</span>'}
      </div>`).join('');

    const actions = [];
    if (job.download_url) {
      actions.push(`<a class="btn primary" href="${job.download_url}">Descargar audiolibro completo</a>`);
    }
    actions.push('<a class="btn ghost" href="/jobs">Ver todos los trabajos</a>');
    $('#job-actions').innerHTML = actions.join('');

    if (job.status === 'done' && state.lastJobStatus !== 'done') {
      toast('Audiolibro listo para descargar', 'ok');
    }
    if (job.status === 'error' && state.lastJobStatus !== 'error') {
      toast(job.error || 'La generación falló', 'error');
    }
    state.lastJobStatus = job.status;
  }

  function startJobPolling(jobId) {
    state.jobId = jobId;
    localStorage.setItem(JOB_KEY, jobId);
    clearTimeout(state.pollTimer);
    const tick = async () => {
      try {
        const job = await api(`/api/jobs/${encodeURIComponent(jobId)}`);
        renderJob(job);
        if (job.status === 'queued' || job.status === 'running') {
          state.pollTimer = setTimeout(tick, 1500);
        } else {
          localStorage.removeItem(JOB_KEY);
        }
      } catch (error) {
        localStorage.removeItem(JOB_KEY);
        toast(error.message, 'error');
      }
    };
    tick();
  }

  function initIndex() {
    const form = $('#generate-form');
    if (!form) return;

    $$('.tab[data-source]').forEach((tab) => {
      tab.addEventListener('click', () => selectSource(tab.dataset.source));
    });

    const fileInput = $('#file-input');
    const dropzone = $('#dropzone');
    dropzone?.addEventListener('dragover', (event) => {
      event.preventDefault();
      dropzone.classList.add('dragover');
    });
    dropzone?.addEventListener('dragleave', () => dropzone.classList.remove('dragover'));
    dropzone?.addEventListener('drop', (event) => {
      event.preventDefault();
      dropzone.classList.remove('dragover');
      const file = event.dataTransfer.files?.[0];
      if (file) validateAndSetFile(file);
    });
    fileInput?.addEventListener('change', () => {
      if (fileInput.files?.[0]) validateAndSetFile(fileInput.files[0]);
    });
    $('#clear-file')?.addEventListener('click', () => {
      setSelectedFile(null);
      if (fileInput) fileInput.value = '';
    });

    $('#provider-select')?.addEventListener('change', () => applyProvider());
    $('#lang-select')?.addEventListener('change', () => {
      populateAccents();
      populateVoices();
    });
    $('#accent-select')?.addEventListener('change', () => populateVoices());
    $('#speed')?.addEventListener('input', () => {
      $('#speed-value').textContent = `${parseFloat($('#speed').value).toFixed(2)}×`;
    });
    $('#refresh-providers')?.addEventListener('click', loadProviders);
    $('#preview-voice-btn')?.addEventListener('click', playVoicePreview);
    form.addEventListener('submit', onGenerate);

    readStoredSelection();
    loadProviders();

    const activeJob = localStorage.getItem(JOB_KEY);
    if (activeJob) {
      startJobPolling(activeJob);
    }
  }

  function validateAndSetFile(file) {
    const extension = (file.name.split('.').pop() || '').toLowerCase();
    if (!['epub', 'pdf'].includes(extension)) {
      toast('Solo se permiten archivos .epub o .pdf', 'error');
      return;
    }
    const maxMb = (state.providerData?.settings?.max_upload_mb) || 100;
    if (file.size > maxMb * 1024 * 1024) {
      toast(`El archivo supera el límite de ${maxMb} MB`, 'error');
      return;
    }
    setSelectedFile(file);
    $('#upload-status').textContent = '';
  }

  async function onGenerate(event) {
    event.preventDefault();
    const button = $('#generate-btn');
    const provider = currentProvider();
    if (!provider) return toast('Selecciona un proveedor disponible', 'error');
    if (!provider.available) return toast(provider.reason || 'Proveedor no disponible', 'error');

    const body = {
      provider: provider.id,
      voice: $('#voice-select').value || null,
      lang: $('#lang-select').value || 'es-ES',
      speed: parseFloat($('#speed').value || '1'),
      format: $('#format-select').value || 'mp3',
    };

    setBusy(button, true, 'Preparando…');
    try {
      if (state.source === 'upload') {
        if (!state.file) throw new Error('Selecciona un archivo EPUB o PDF');
        const formData = new FormData();
        formData.append('file', state.file);
        $('#upload-status').textContent = 'Subiendo archivo…';
        const uploaded = await api('/api/upload', { method: 'POST', body: formData });
        $('#upload-status').textContent = `Subido: ${uploaded.filename} (${formatBytes(uploaded.size)})`;
        body.upload_id = uploaded.upload_id;
      } else {
        const path = $('#file-path').value.trim();
        if (!path) throw new Error('Indica la ruta del archivo del servidor');
        body.file_path = path;
      }

      const result = await api('/api/generate', { method: 'POST', body });
      state.lastJobStatus = null;
      startJobPolling(result.job_id);
      renderJob(result.job);
      toast('Generación iniciada', 'ok');
      $('#job-panel').scrollIntoView({ behavior: 'smooth', block: 'start' });
    } catch (error) {
      toast(error.message, 'error');
    } finally {
      setBusy(button, false, 'Generar audiolibro');
    }
  }

  // -------------------------------------------------------------- browser
  function renderBreadcrumbs(data) {
    const container = $('#breadcrumbs');
    if (!container) return;
    const baseName = (data.base || '').split('/').filter(Boolean).pop() || 'inicio';
    const parts = [];
    parts.push(`<button type="button" data-path="">🏠 ${escapeHtml(baseName)}</button>`);
    const relative = data.relative === '.' ? '' : data.relative;
    if (relative) {
      let accumulated = '';
      relative.split('/').filter(Boolean).forEach((segment) => {
        accumulated = accumulated ? `${accumulated}/${segment}` : segment;
        parts.push('<span class="sep">/</span>');
        parts.push(`<button type="button" data-path="${escapeHtml(accumulated)}">${escapeHtml(segment)}</button>`);
      });
    }
    container.innerHTML = parts.join('');
    $$('button[data-path]', container).forEach((button) => {
      button.addEventListener('click', () => browserLoad(button.dataset.path));
    });
    const upButton = $('#up-btn');
    if (upButton) upButton.disabled = !data.parent;
  }

  function renderBrowserEntries() {
    const container = $('#entries');
    const data = state.browser.data;
    if (!container || !data) return;
    const filter = state.browser.filter.toLowerCase();
    const entries = (data.entries || []).filter(
      (entry) => !filter || entry.name.toLowerCase().includes(filter),
    );
    if (!entries.length) {
      container.innerHTML = '<div class="empty">No hay archivos ni carpetas que coincidan.</div>';
      return;
    }
    container.innerHTML = entries.map((entry) => {
      if (entry.type === 'dir') {
        return `
          <div class="entry is-dir ${entry.hidden ? 'hidden' : ''}" data-dir="${escapeHtml(entry.relative)}" tabindex="0">
            <span class="entry-icon">📁</span>
            <span class="entry-name">${escapeHtml(entry.name)}</span>
            <span class="entry-meta">carpeta</span>
          </div>`;
      }
      const size = formatBytes(entry.size);
      const action = entry.selectable
        ? `<button class="btn secondary small" type="button" data-select="${escapeHtml(entry.path)}" data-name="${escapeHtml(entry.name)}">Seleccionar</button>`
        : '<span class="entry-meta">no compatible</span>';
      return `
        <div class="entry ${entry.hidden ? 'hidden' : ''} ${entry.selectable ? '' : 'disabled'}">
          <span class="entry-icon">📄</span>
          <span class="entry-name">${escapeHtml(entry.name)}</span>
          <span class="entry-meta">${escapeHtml(entry.ext)} · ${size}</span>
          ${action}
        </div>`;
    }).join('');

    $$('.entry.is-dir', container).forEach((row) => {
      const open = () => browserLoad(row.dataset.dir);
      row.addEventListener('click', open);
      row.addEventListener('keydown', (event) => {
        if (event.key === 'Enter') open();
      });
    });
    $$('button[data-select]', container).forEach((button) => {
      button.addEventListener('click', () => selectBrowserFile(button.dataset.select, button.dataset.name));
    });
  }

  function selectBrowserFile(path, name) {
    localStorage.setItem(SELECTION_KEY, JSON.stringify({ path, name }));
    window.location.href = '/';
  }

  async function browserLoad(path = '') {
    const errorBox = $('#browser-error');
    const entries = $('#entries');
    errorBox?.classList.add('hidden');
    if (entries) entries.innerHTML = '<div class="loading">Cargando…</div>';
    try {
      const query = path ? `?path=${encodeURIComponent(path)}` : '';
      const data = await api(`/api/files${query}`);
      state.browser.data = data;
      state.browser.filter = $('#filter')?.value || '';
      renderBreadcrumbs(data);
      renderBrowserEntries();
      const url = new URL(window.location.href);
      if (path) url.searchParams.set('path', path);
      else url.searchParams.delete('path');
      window.history.replaceState({}, '', url);
    } catch (error) {
      if (errorBox) {
        errorBox.textContent = error.message;
        errorBox.classList.remove('hidden');
      }
      if (entries) entries.innerHTML = '<div class="empty">No se pudo cargar el directorio.</div>';
    }
  }

  function initBrowser() {
    if (!$('#entries')) return;
    const params = new URLSearchParams(window.location.search);
    browserLoad(params.get('path') || '');
    $('#up-btn')?.addEventListener('click', () => {
      const parent = state.browser.data?.parent;
      if (parent) browserLoad(parent);
    });
    $('#refresh-btn')?.addEventListener('click', () => {
      browserLoad(state.browser.data?.relative || '');
    });
    $('#filter')?.addEventListener('input', (event) => {
      state.browser.filter = event.target.value;
      renderBrowserEntries();
    });
  }

  // ------------------------------------------------------------- register
  const FREE_PROVIDERS = ['piper', 'edge', 'gtts'];

  function freeProviderCard(provider) {
    return `
      <article class="provider card ${provider.available ? 'is-ok' : 'is-off'}" data-provider="${escapeHtml(provider.id)}">
        <header>
          <h3>${escapeHtml(provider.label)}</h3>
          <span class="badge ${provider.available ? 'ok' : 'off'}">${provider.available ? 'disponible' : 'no disponible'}</span>
        </header>
        <p>${escapeHtml(provider.description)}</p>
        <p class="provider-reason">${escapeHtml(provider.reason || '')}</p>
        <label class="switch-row">
          <input type="checkbox" data-free-toggle ${provider.enabled !== false ? 'checked' : ''}>
          <span>Proveedor activo</span>
        </label>
      </article>`;
  }

  async function loadFreeProviders() {
    const container = $('#free-providers');
    if (!container) return;
    container.innerHTML = '<div class="skeleton card"></div><div class="skeleton card"></div>';
    try {
      const data = await api('/api/providers');
      const free = (data.providers || []).filter((provider) => FREE_PROVIDERS.includes(provider.id));
      container.innerHTML = free.map(freeProviderCard).join('')
        || '<div class="empty">No hay proveedores gratuitos.</div>';
      $$('[data-free-toggle]', container).forEach((checkbox) => {
        const card = checkbox.closest('[data-provider]');
        const providerId = card?.dataset.provider;
        checkbox.addEventListener('change', async () => {
          checkbox.disabled = true;
          try {
            await api(`/api/providers/${encodeURIComponent(providerId)}/enabled`, {
              method: 'POST',
              body: { enabled: checkbox.checked },
            });
            toast(checkbox.checked ? 'Proveedor activado' : 'Proveedor desactivado', 'ok');
            await loadFreeProviders();
          } catch (error) {
            checkbox.checked = !checkbox.checked;
            checkbox.disabled = false;
            toast(error.message, 'error');
          }
        });
      });
    } catch (error) {
      container.innerHTML = `<div class="alert">${escapeHtml(error.message)}</div>`;
    }
  }

  function credentialCard(item) {
    const fields = (item.fields || []).map((field) => {
      const value = field.secret ? '' : (field.masked || field.default || '');
      const placeholder = field.masked || field.default || '';
      return `
        <label class="field">
          <span>${escapeHtml(field.label)}${field.required ? ' *' : ''}</span>
          <input class="input" name="${escapeHtml(field.name)}"
            type="${field.secret ? 'password' : 'text'}"
            value="${escapeHtml(value)}"
            placeholder="${escapeHtml(placeholder)}"
            autocomplete="off" spellcheck="false">
          ${field.help ? `<small class="hint">${escapeHtml(field.help)}</small>` : ''}
        </label>`;
    }).join('');
    return `
      <article class="card credential-card" data-provider="${escapeHtml(item.provider)}">
        <header>
          <div>
            <h3>${escapeHtml(item.label || item.provider)}</h3>
            <p class="muted">${escapeHtml(item.description || '')}</p>
          </div>
          <span class="badge ${item.configured ? 'ok' : 'off'}">${item.configured ? 'configurado' : 'sin configurar'}</span>
        </header>
        <form data-form>
          ${fields}
          <label class="switch-row">
            <input type="checkbox" name="enabled" ${item.enabled !== false ? 'checked' : ''}>
            <span>Proveedor activo</span>
          </label>
          <div class="form-actions">
            <button class="btn primary small" type="submit">Guardar</button>
            <button class="btn secondary small" type="button" data-test>Probar conexión</button>
            ${item.configured ? '<button class="btn danger small" type="button" data-clear>Borrar</button>' : ''}
          </div>
          <p class="hint test-result" data-result></p>
        </form>
      </article>`;
  }

  async function loadCredentials() {
    const list = $('#credentials-list');
    if (!list) return;
    list.innerHTML = '<div class="skeleton card"></div><div class="skeleton card"></div>';
    try {
      const data = await api('/api/credentials');
      state.credentials = data;
      list.innerHTML = (data.providers || []).map(credentialCard).join('')
        || '<div class="empty">No hay servicios que requieran credenciales.</div>';
      bindCredentialForms();
    } catch (error) {
      list.innerHTML = `<div class="alert">${escapeHtml(error.message)}</div>`;
    }
  }

  function bindCredentialForms() {
    $$('.credential-card').forEach((card) => {
      const provider = card.dataset.provider;
      const form = $('form', card);
      const result = $('[data-result]', card);
      form?.addEventListener('submit', async (event) => {
        event.preventDefault();
        const formData = new FormData(form);
        const enabled = formData.get('enabled') === 'on';
        formData.delete('enabled');
        const values = Object.fromEntries(formData.entries());
        const button = $('button[type="submit"]', form);
        setBusy(button, true, 'Guardando…');
        try {
          await api(`/api/credentials/${encodeURIComponent(provider)}`, {
            method: 'POST',
            body: { values, enabled },
          });
          toast('Credenciales guardadas', 'ok');
          await loadCredentials();
        } catch (error) {
          toast(error.message, 'error');
          setBusy(button, false);
        }
      });
      $('[data-test]', card)?.addEventListener('click', async (event) => {
        const button = event.currentTarget;
        setBusy(button, true, 'Probando…');
        result.className = 'hint test-result';
        result.textContent = 'Comprobando conexión…';
        try {
          const response = await api(`/api/credentials/${encodeURIComponent(provider)}/test`, { method: 'POST' });
          result.textContent = response.message;
          result.classList.add(response.ok ? 'ok' : 'error');
        } catch (error) {
          result.textContent = error.message;
          result.classList.add('error');
        } finally {
          setBusy(button, false, 'Probar conexión');
        }
      });
      $('[data-clear]', card)?.addEventListener('click', async () => {
        if (!window.confirm('¿Borrar las credenciales guardadas de este proveedor?')) return;
        try {
          await api(`/api/credentials/${encodeURIComponent(provider)}`, { method: 'DELETE' });
          toast('Credenciales eliminadas', 'ok');
          await loadCredentials();
        } catch (error) {
          toast(error.message, 'error');
        }
      });
    });
  }

  function initRegister() {
    if (!$('#credentials-list')) return;
    loadFreeProviders();
    loadCredentials();
  }

  // ----------------------------------------------------------------- jobs
  function jobCard(job) {
    const chapters = (job.chapters || []).map((chapter) => `
      <div class="chapter-row">
        <div><strong>${escapeHtml(chapter.title)}</strong><small>${chapter.chars} caracteres${chapter.duration ? ` · ${chapter.duration}s` : ''}</small></div>
        ${job.status === 'done' ? `<a class="btn ghost small" href="${chapter.download_url}">Descargar</a>` : ''}
      </div>`).join('');
    const download = job.download_url
      ? `<a class="btn primary small" href="${job.download_url}">Descargar completo</a>` : '';
    return `
      <article class="card job-card">
        <header>
          <div>
            <h3>${escapeHtml(job.title || job.filename)}</h3>
            <div class="job-sub">${escapeHtml(job.provider)} · ${escapeHtml(job.voice || 'voz por defecto')} · ${escapeHtml(job.lang)} · ${job.speed}× · ${formatDate(job.created_at)}</div>
          </div>
          ${statusBadge(job.status)}
        </header>
        <div class="progress"><div class="progress-bar" style="width:${Math.max(0, Math.min(100, job.progress || 0))}%"></div></div>
        <p class="muted">${escapeHtml(job.error || job.message || '')}</p>
        ${chapters ? `<div class="chapter-list">${chapters}</div>` : ''}
        ${download ? `<div class="form-actions" style="padding:0;border:0">${download}</div>` : ''}
      </article>`;
  }

  async function loadJobs() {
    const list = $('#jobs-list');
    if (!list) return;
    try {
      const data = await api('/api/jobs');
      const jobs = data.jobs || [];
      if (!jobs.length) {
        list.innerHTML = '<div class="empty-state card"><h1>Sin trabajos todavía</h1><p class="muted">Genera tu primer audiolibro desde la página principal.</p><a class="btn primary" href="/">Crear audiolibro</a></div>';
        clearTimeout(state.jobsTimer);
        return;
      }
      list.innerHTML = jobs.map(jobCard).join('');
      if (jobs.some((job) => job.status === 'queued' || job.status === 'running')) {
        clearTimeout(state.jobsTimer);
        state.jobsTimer = setTimeout(loadJobs, 2500);
      }
    } catch (error) {
      list.innerHTML = `<div class="alert">${escapeHtml(error.message)}</div>`;
    }
  }

  function initJobs() {
    if (!$('#jobs-list')) return;
    loadJobs();
    $('#refresh-jobs')?.addEventListener('click', loadJobs);
  }

  // ----------------------------------------------------------------- boot
  document.addEventListener('DOMContentLoaded', () => {
    const page = document.body.dataset.page;
    if (page === 'index') initIndex();
    else if (page === 'browser') initBrowser();
    else if (page === 'register') initRegister();
    else if (page === 'jobs') initJobs();
  });
})();
