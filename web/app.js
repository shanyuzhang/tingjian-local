import { wavHeader, makeWav } from './audio.mjs';
import { RealtimeClient } from './realtime.mjs';

const $ = (selector) => document.querySelector(selector);
const state = {
  sessions: [], selected: localStorage.getItem('selected-session'), detail: null,
  models: null, recording: null, backup: [], uploads: [], uploading: false,
  tab: 'transcript', signature: '', knownJobs: new Map(), fetching: false,
  realtime: null, mode: localStorage.getItem('record-mode') || 'qwen', starting: false,
};
const languageNames = { en: '英语', zh: '中文', ja: '日语', auto: '自动识别' };
let toastTimer;

function toast(message, error = false) {
  $('#toast').textContent = message;
  $('#toast').classList.toggle('error', error);
  $('#toast').classList.remove('hidden');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => $('#toast').classList.add('hidden'), error ? 13000 : 5000);
}

async function api(path, options = {}) {
  const headers = { ...options.headers };
  if (options.body && !(options.body instanceof FormData)) headers['Content-Type'] = 'application/json';
  let response;
  try { response = await fetch(path, { ...options, headers }); }
  catch { throw new Error('无法连接本地服务。请确认“启动听笺.command”的终端仍在运行。'); }
  if (!response.ok) {
    let message = `请求失败（${response.status}）`;
    try {
      const error = await response.json();
      message = typeof error.detail === 'string' ? error.detail : '输入内容不符合要求，请检查后重试。';
    } catch { /* Keep the HTTP status when no JSON error is available. */ }
    const error = new Error(message);
    error.status = response.status;
    throw error;
  }
  return response.status === 204 ? null : response.json();
}

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function formatTime(seconds) {
  seconds = Math.max(0, Math.floor(seconds || 0));
  const parts = [Math.floor(seconds / 3600), Math.floor(seconds / 60) % 60, seconds % 60];
  return parts.slice(parts[0] ? 0 : 1).map((n) => String(n).padStart(2, '0')).join(':');
}

function renderLibrary() {
  const query = $('#search').value.trim().toLowerCase();
  $('#library-count').textContent = state.sessions.length;
  const rows = state.sessions.filter((row) => `${row.title} ${row.folder}`.toLowerCase().includes(query));
  $('#library').replaceChildren();
  if (!rows.length) $('#library').append(element('div', 'library-empty', query ? '没有匹配的录音' : '你的第一段录音，\n从这里开始。'));
  for (const row of rows) {
    const button = element('button', `library-item${row.id === state.selected ? ' selected' : ''}`);
    button.append(element('strong', '', row.title));
    button.append(element('small', '', `${new Date(row.created_at).toLocaleDateString('zh-CN', { month: 'short', day: 'numeric' })} · ${formatTime(row.duration)} · ${row.segment_count} 段`));
    if (row.folder) button.append(element('span', 'folder-name', row.folder));
    button.onclick = () => selectSession(row.id);
    $('#library').append(button);
  }
}

function renderStatus() {
  if (!state.models) return;
  const { speech, text } = state.models;
  $('#model-dot').classList.toggle('ready', speech.ready && text.ready);
  $('#active-model').textContent = text.ready ? `${text.label} · 仅在本机运行` : '等待配置本地文本模型';
  $('.model-label .status-dot').classList.toggle('ready', text.ready);
  const notice = $('#model-notice');
  notice.replaceChildren();
  if (!speech.ready || !text.ready) {
    notice.append(document.createTextNode(!speech.ready
      ? '转写模型尚未准备好。请先运行“准备语音模型.command”，完成后自动就绪。 '
      : '转写已就绪。配置本地文本模型后，即可使用翻译、笔记和录音问答。 '));
    const button = element('button', '', '查看模型设置');
    button.onclick = openSettings;
    notice.append(button);
  }
  notice.classList.toggle('hidden', speech.ready && text.ready);
  $('#record-mode').value = state.mode;
  const cloud = state.mode === 'qwen';
  $('#mode-description').textContent = cloud
    ? '音频发送至千问 · 双语字幕持续更新 · 笔记在本机处理'
    : '麦克风录音每 15 秒更新 · 音频与模型均在本机';
  $('#cloud-state').textContent = cloud
    ? state.recording?.realtimeClient ? state.recording.stopping ? '正在保存剩余字幕' : '千问实时连接中'
      : state.starting ? '正在连接…' : state.realtime?.ready ? '千问配置已填写，录音时连接' : '千问尚未配置'
    : '离线模式';
  $('.local-badge').lastChild.textContent = cloud ? ' 千问实时 · 本地笔记' : ' 本地处理';
  updateButtons();
}

function renderMarkdown(text) {
  const root = element('div', 'notes-text');
  // Model output stays text; no HTML from transcripts is inserted into the document.
  for (const line of text.split('\n')) {
    const match = line.match(/^(#{1,4})\s+(.*)$/);
    const bullet = line.match(/^(\s*)[-*]\s+(.*)$/);
    const row = element(match ? 'h3' : 'div', bullet ? `notes-bullet${bullet[1].length ? ' nested' : ''}` : '');
    const value = match ? match[2] : bullet ? bullet[2] : line || '\u00a0';
    if (bullet) row.append(document.createTextNode('• '));
    for (const part of value.split(/(\*\*[^*]+\*\*)/g)) {
      if (part.startsWith('**') && part.endsWith('**')) row.append(element('strong', '', part.slice(2, -2)));
      else row.append(document.createTextNode(part));
    }
    root.append(row);
  }
  return root;
}

function updateButtons() {
  const hasText = !!state.detail?.segments.length;
  const busy = state.detail?.jobs.some((job) => ['queued', 'running'].includes(job.status));
  for (const id of ['translate', 'summarize', 'summary-in-notes', 'ask']) {
    const button = $(`#${id}`);
    if (button) button.disabled = !hasText || !state.models?.text.ready || busy || !!state.recording || state.starting || state.detail?.live;
  }
  $('#export').disabled = !state.detail;
  const pendingAudio = state.detail?.jobs.some((job) => job.kind === 'audio' && ['queued', 'running'].includes(job.status));
  $('#import-button').disabled = !!state.recording || pendingAudio || !!state.importing || state.starting || state.detail?.live;
  $('#record-button').disabled = (!state.recording && (pendingAudio || state.detail?.live)) || !!state.importing || state.starting || !!state.recording?.stopping;
  $('#new-session').disabled = !!state.recording || state.starting;
  $('#record-mode').disabled = !!state.recording || state.starting;
  $('#configure-cloud').disabled = !!state.recording || state.starting;
  $('#delete').disabled = !!state.recording || state.starting || state.detail?.live;
}

function renderDetail() {
  const detail = state.detail;
  if (!detail) return;
  $('#session-title').textContent = detail.title;
  $('#breadcrumb-title').textContent = detail.folder || '我的录音';
  $('#session-meta').textContent = `${languageNames[detail.language]} → ${languageNames[detail.target_language]} · ${new Date(detail.created_at).toLocaleString('zh-CN', { month: 'long', day: 'numeric', hour: '2-digit', minute: '2-digit' })}${detail.folder ? ` · ${detail.folder}` : ''}`;
  $('#recording-card .recording-foot > span:first-child').textContent = `${languageNames[detail.language]} → ${languageNames[detail.target_language]}`;
  $('#session-actions').classList.remove('hidden');
  $('#segment-count').textContent = detail.segments.length;
  const signature = JSON.stringify([detail.id, detail.segments, detail.summary, detail.messages]);
  if (signature !== state.signature) {
    state.signature = signature;
    if (detail.segments.length) {
      const atBottom = $('#transcript').scrollHeight - $('#transcript').scrollTop - $('#transcript').clientHeight < 90;
      $('#transcript').replaceChildren();
      detail.segments.forEach((segment, index) => {
        const row = element('article', 'transcript-segment');
        const top = element('div', 'segment-top');
        const timestamp = element('button', 'timestamp', formatTime(segment.start));
        timestamp.title = '回听这一句';
        timestamp.onclick = () => playSegment(segment);
        top.append(timestamp, element('span', 'segment-number', `SEGMENT ${String(index + 1).padStart(2, '0')}${segment.speaker ? ` · 发言人 ${segment.speaker}` : ''}${segment.is_final === 0 ? ' · 草稿' : ''}`));
        row.append(top, element('p', 'original', segment.text), element('p', `translation${segment.translation ? '' : ' missing'}`, segment.translation || '等待生成译文'));
        $('#transcript').append(row);
      });
      if (atBottom) $('#transcript').scrollTop = $('#transcript').scrollHeight;
    } else $('#transcript').replaceChildren(initialTranscript.cloneNode(true));
    if (detail.summary) $('#notes').replaceChildren(renderMarkdown(detail.summary));
    else {
      $('#notes').replaceChildren(initialNotes.cloneNode(true));
      $('#summary-in-notes').onclick = () => runAction('summary');
    }
    $('#messages').replaceChildren();
    if (!detail.messages.length) $('#messages').append(initialChat.cloneNode(true));
    for (const message of detail.messages) {
      $('#messages').append(element('div', 'chat-question', message.question), element('div', 'chat-answer', message.answer));
    }
    $('#messages').scrollTop = $('#messages').scrollHeight;
  }
  const jobs = detail.jobs.filter((job) => ['running', 'queued', 'failed'].includes(job.status));
  $('#jobs').replaceChildren();
  for (const job of jobs.slice(-5)) {
    const row = element('div', `job${job.status === 'failed' ? ' failed' : ''}`);
    row.append(element('span', job.status === 'failed' ? '' : 'spinner', job.status === 'failed' ? '!' : ''));
    row.append(element('span', '', job.status === 'failed' ? job.error : job.status === 'queued' ? '已排队，等待本地处理' : job.progress || '正在加载本地模型，首次使用可能需要一些时间'));
    if (job.status === 'failed') {
      const retry = element('button', 'text-button', '重试');
      retry.onclick = async () => {
        try { await api(`/api/jobs/${job.id}/retry`, { method: 'POST' }); await refresh(); }
        catch (error) { toast(error.message, true); }
      };
      row.append(retry);
    }
    $('#jobs').append(row);
  }
  for (const job of detail.jobs) {
    const previous = state.knownJobs.get(job.id);
    if (previous && previous !== job.status && job.status === 'done') toast(job.progress || '处理完成');
    state.knownJobs.set(job.id, job.status);
  }
  const playable = detail.audio.find((audio) => audio.duration > 0);
  if (playable) {
    $('#player-wrap').classList.remove('hidden');
    if (!$('#player').getAttribute('src')) $('#player').src = `/api/audio/${playable.id}/playback`;
  } else $('#player-wrap').classList.add('hidden');
  updateButtons();
}

async function refresh() {
  if (state.fetching) return;
  state.fetching = true;
  try {
    const [status, sessions] = await Promise.all([api('/api/status'), api('/api/sessions')]);
    state.models = status.models;
    state.realtime = status.realtime;
    state.sessions = sessions;
    if (!state.selected || !sessions.some((s) => s.id === state.selected)) state.selected = sessions[0]?.id || null;
    if (state.selected) {
      const id = state.selected;
      const detail = await api(`/api/sessions/${id}`);
      if (id === state.selected) { state.detail = detail; renderDetail(); }
    }
    renderLibrary();
    renderStatus();
  } catch (error) { toast(error.message, true); }
  finally { state.fetching = false; }
}

async function selectSession(id) {
  if (state.starting || (state.recording && id !== state.recording.sid)) return toast('请先结束当前录音。');
  state.selected = id;
  state.signature = '';
  localStorage.setItem('selected-session', id);
  $('#player').pause();
  $('#player').removeAttribute('src');
  state.detail = await api(`/api/sessions/${id}`);
  renderDetail();
  renderLibrary();
}

async function ensureSession(title = '新的录音') {
  if (state.selected) return state.selected;
  const session = await api('/api/sessions', { method: 'POST', body: JSON.stringify({ title }) });
  state.sessions.unshift({ ...session, segment_count: 0 });
  await selectSession(session.id);
  return session.id;
}

async function playSegment(segment) {
  const source = state.detail.audio.find((a) => a.id === segment.audio_id);
  if (!source) return toast('没有找到原音频。', true);
  const player = $('#player');
  const time = Math.max(0, segment.start - source.offset);
  const seek = () => { player.currentTime = time; player.play().catch(() => toast('请点击播放器的播放按钮。')); };
  if (player.getAttribute('src') !== `/api/audio/${source.id}/playback`) {
    player.src = `/api/audio/${source.id}/playback`;
    player.addEventListener('loadedmetadata', seek, { once: true });
  } else if (player.readyState) seek();
  else { player.addEventListener('loadedmetadata', seek, { once: true }); player.load(); }
  $('#player-label').textContent = `回听 ${formatTime(segment.start)}`;
}

async function runAction(action) {
  if (!state.selected) return;
  try {
    await api(`/api/sessions/${state.selected}/actions/${action}`, { method: 'POST' });
    if (action === 'summary') switchTab('notes');
    await refresh();
  } catch (error) { toast(error.message, true); }
}

function switchTab(tab) {
  state.tab = tab;
  document.querySelectorAll('.tab').forEach((button) => button.classList.toggle('active', button.dataset.tab === tab));
  $('#transcript').classList.toggle('hidden', tab !== 'transcript');
  $('#notes').classList.toggle('hidden', tab !== 'notes');
}

function openSettings() {
  $('#speech-model').value = state.models?.speech.path || '';
  $('#text-model').value = state.models?.text.path || '';
  $('#speech-status').textContent = state.models?.speech.ready ? '转写模型文件已就绪' : '若尚未下载，请双击项目中的“准备语音模型.command”。';
  $('#cloud-region').value = state.realtime?.region || 'cn-beijing';
  $('#cloud-workspace').value = state.realtime?.workspace_id || '';
  $('#cloud-key-status').textContent = state.realtime?.key_configured
    ? 'API Key 已由本机环境变量提供，不会发送到浏览器。'
    : '尚未检测到 API Key。请按项目“实时API配置.md”在启动终端设置 DASHSCOPE_API_KEY，然后重启服务。';
  $('#settings-dialog').showModal();
}

function flushRecording(count) {
  const record = state.recording;
  if (!record || !count) return;
  const combined = new Float32Array(record.buffered);
  let position = 0;
  for (const part of record.buffers) { combined.set(part, position); position += part.length; }
  const blob = makeWav(combined.subarray(0, count));
  const offset = record.offset + record.framesSent / 16000;
  const key = `${record.id}-${record.framesSent}`;
  record.framesSent += count;
  record.buffers = combined.length > count ? [combined.slice(count)] : [];
  record.buffered -= count;
  state.backup.push(blob);
  state.uploads.push({ blob, offset, key, sid: record.sid });
  $('#backup').classList.remove('hidden');
  processUploads();
}

async function processUploads() {
  if (state.uploading) return;
  state.uploading = true;
  try {
    while (state.uploads.length) {
      const item = state.uploads[0];
      const form = new FormData();
      form.append('file', item.blob, 'microphone.wav');
      form.append('offset', item.offset);
      form.append('client_key', item.key);
      form.append('translate', 'true');
      try {
        await api(`/api/sessions/${item.sid}/audio`, { method: 'POST', body: form });
        state.uploads.shift();
      } catch (error) {
        if (error.status === 429) { await new Promise((resolve) => setTimeout(resolve, 2000)); continue; }
        if (state.recording) await stopRecording();
        toast(`${error.message} 录音仍在当前页面，请保存录音备份，稍后重新导入。`, true);
        break;
      }
    }
  } finally { state.uploading = false; refresh(); }
}

async function startRecording() {
  const cloud = state.mode === 'qwen';
  if (cloud ? !state.realtime?.ready : !state.models?.speech.ready) return openSettings();
  if (state.uploads.length) return toast('还有未保存的录音，请先保存备份并重新导入。', true);
  if (state.detail?.jobs.some((job) => job.kind === 'audio' && ['queued', 'running'].includes(job.status))) return toast('请先等待已有音频处理完成，再继续录音。');
  let stream, context, realtimeClient;
  state.starting = true;
  updateButtons();
  try {
    const sid = await ensureSession(`录音 · ${new Date().toLocaleString('zh-CN', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' })}`);
    stream = await navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true } });
    context = new AudioContext({ sampleRate: 16000 });
    if (context.sampleRate !== 16000) throw new Error('当前浏览器无法以 16kHz 采集，请使用 Chrome。');
    let ready;
    if (cloud) {
      $('#recording-description').textContent = '正在连接千问实时翻译…';
      realtimeClient = new RealtimeClient({
        onSegment(segment) {
          if (state.selected !== sid || !state.detail) return;
          const index = state.detail.segments.findIndex((s) => s.id === segment.id);
          if (index < 0) state.detail.segments.push(segment);
          else state.detail.segments[index] = segment;
          state.detail.segments.sort((a, b) => a.start - b.start);
          renderDetail();
        },
        onError(message) {
          toast(message, true);
          if (state.recording && !state.recording.stopping) stopRecording();
        },
      });
      const url = new URL(`/api/sessions/${sid}/realtime`, location.href);
      url.protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
      ready = await realtimeClient.connect(url.href);
    }
    await context.audioWorklet.addModule('/recorder-worklet.js');
    const source = context.createMediaStreamSource(stream);
    const node = new AudioWorkletNode(context, 'pcm-recorder');
    const silent = context.createGain(); silent.gain.value = 0;
    source.connect(node); node.connect(silent); silent.connect(context.destination);
    const existingEnd = ready?.offset ?? Math.max(0, ...state.detail.audio.map((a) => a.offset + a.duration), ...state.detail.segments.map((s) => s.end));
    state.recording = { id: crypto.randomUUID(), sid, stream, context, node, source, silent,
      buffers: [], buffered: 0, framesSent: 0, offset: existingEnd, started: performance.now(), realtimeClient };
    stream.getAudioTracks()[0].addEventListener('ended', () => {
      if (state.recording && !state.recording.stopping) {
        toast('麦克风已断开，正在保存已录制的内容。', true);
        stopRecording();
      }
    });
    state.backup = [];
    node.port.onmessage = ({ data }) => {
      const record = state.recording;
      if (!record) return;
      if (data.kind === 'flushed') { record.flushDone?.(); return; }
      const samples = data.samples;
      if (record.realtimeClient) {
        state.backup.push(makeWav(samples));
        $('#backup').classList.remove('hidden');
        try { record.realtimeClient.send(samples); }
        catch (error) {
          toast(error.message, true);
          if (!record.stopping) stopRecording();
        }
        $('#level').value = Math.min(1, Math.sqrt(samples.reduce((sum, x) => sum + x * x, 0) / samples.length) * 5);
        return;
      }
      record.buffers.push(samples); record.buffered += samples.length;
      $('#level').value = Math.min(1, Math.sqrt(samples.reduce((sum, x) => sum + x * x, 0) / samples.length) * 5);
      if (record.buffered >= 15 * 16000) flushRecording(15 * 16000);
    };
    await context.resume();
    $('#recording-card').classList.add('recording');
    $('#record-button-text').textContent = '结束录音';
    $('#recording-title').textContent = '正在聆听，安心表达。';
    $('#recording-description').textContent = cloud ? '千问已连接，原文与译文正在实时呈现。' : '录音分段保存，转写与翻译会逐步呈现。';
    switchTab('transcript');
    $('#record-clock').classList.remove('hidden'); $('#level').classList.remove('hidden');
    $('#record-clock').textContent = '00:00';
    state.recording.timer = setInterval(() => {
      const seconds = (performance.now() - state.recording.started) / 1000;
      $('#record-clock').textContent = formatTime(seconds);
      if (seconds >= 10800) stopRecording();
    }, 1000);
    updateButtons();
  } catch (error) {
    realtimeClient?.abort();
    stream?.getTracks().forEach((track) => track.stop());
    if (context && context.state !== 'closed') await context.close();
    if (state.recording?.timer) clearInterval(state.recording.timer);
    state.recording = null;
    $('#recording-description').textContent = '未开始录音，请检查配置和麦克风权限后重试。';
    toast(error.name === 'NotAllowedError' ? '请允许麦克风访问；也可以先导入音频。' : error.message, true);
  } finally { state.starting = false; updateButtons(); }
}

async function stopRecording() {
  const record = state.recording;
  if (!record || record.stopping) return;
  record.stopping = true;
  clearInterval(record.timer);
  await new Promise((resolve) => {
    record.flushDone = resolve;
    record.node.port.postMessage('flush');
    setTimeout(resolve, 800);
  });
  record.stream.getTracks().forEach((track) => track.stop());
  record.source.disconnect(); record.node.disconnect();
  await record.context.close();
  if (record.buffered) flushRecording(record.buffered);
  if (record.realtimeClient) {
    $('#recording-description').textContent = '正在保存最后一句字幕，请稍候…';
    updateButtons();
    try { await record.realtimeClient.finish(); }
    catch (error) { toast(error.message, true); }
  }
  state.recording = null;
  $('#recording-card').classList.remove('recording');
  $('#record-button-text').textContent = '继续录音';
  $('#recording-title').textContent = '声音已留下，文字正在整理。';
  $('#recording-description').textContent = record.realtimeClient ? '录音已结束。可查看已保存字幕，或继续录制新的一段。' : '本地处理完成后，可以继续生成译文、笔记和问答。';
  $('#record-clock').classList.add('hidden'); $('#level').classList.add('hidden');
  updateButtons();
  refresh();
}

function saveBlob(blob, name) {
  const url = URL.createObjectURL(blob), link = element('a');
  link.href = url; link.download = name; link.click();
  setTimeout(() => URL.revokeObjectURL(url), 15000);
}

const initialTranscript = $('#transcript .empty-state').cloneNode(true);
const initialNotes = $('#notes .empty-state').cloneNode(true);
const initialChat = $('#messages .chat-placeholder').cloneNode(true);
$('#search').oninput = renderLibrary;
$('#new-session').onclick = () => { $('#create-form').reset(); $('#new-dialog').showModal(); };
$('#settings-button').onclick = openSettings;
$('#configure-cloud').onclick = openSettings;
$('#record-mode').onchange = (event) => {
  state.mode = event.target.value;
  localStorage.setItem('record-mode', state.mode);
  renderStatus();
};
document.querySelectorAll('.close-dialog').forEach((button) => { button.onclick = () => button.closest('dialog').close(); });
document.querySelectorAll('.tab').forEach((button) => { button.onclick = () => switchTab(button.dataset.tab); });
$('#record-button').onclick = async () => {
  $('#record-button').disabled = true;
  try { await (state.recording ? stopRecording() : startRecording()); }
  finally { $('#record-button').disabled = false; updateButtons(); }
};
$('#backup').onclick = () => {
  if (!state.backup.length) return;
  const samples = state.backup.reduce((total, blob) => total + (blob.size - 44) / 2, 0);
  saveBlob(new Blob([wavHeader(samples), ...state.backup.map((b) => b.slice(44))], { type: 'audio/wav' }), `听笺录音-${Date.now()}.wav`);
};
$('#import-button').onclick = () => state.models?.speech.ready ? $('#audio-file').click() : openSettings();
$('#audio-file').onchange = async () => {
  const file = $('#audio-file').files[0];
  if (!file) return;
  state.importing = true;
  updateButtons();
  try {
    if (file.size > 500 * 1024 * 1024) throw new Error('第一版支持最大 500MB 的文件。');
    const sid = await ensureSession(file.name.replace(/\.[^.]+$/, ''));
    const form = new FormData(); form.append('file', file); form.append('client_key', crypto.randomUUID());
    form.append('offset', Math.max(0, ...state.detail.audio.map((a) => a.offset + a.duration)));
    await api(`/api/sessions/${sid}/audio`, { method: 'POST', body: form });
    toast('音频已保存到本机，正在排队转写。');
    await refresh();
  } catch (error) { toast(error.message, true); }
  finally { $('#audio-file').value = ''; state.importing = false; updateButtons(); }
};
$('#create-form').onsubmit = async (event) => {
  event.preventDefault();
  try {
    const body = Object.fromEntries(new FormData(event.target));
    const session = await api('/api/sessions', { method: 'POST', body: JSON.stringify(body) });
    state.sessions.unshift({ ...session, segment_count: 0 });
    $('#new-dialog').close();
    await selectSession(session.id);
  } catch (error) { toast(error.message, true); }
};
$('#settings-form').onsubmit = async (event) => {
  event.preventDefault();
  try {
    await api('/api/settings', { method: 'PUT', body: JSON.stringify(Object.fromEntries(new FormData(event.target))) });
    $('#settings-dialog').close(); toast('模型设置已保存。'); await refresh();
  } catch (error) { toast(error.message, true); }
};
$('#cloud-settings-form').onsubmit = async (event) => {
  event.preventDefault();
  try {
    state.realtime = await api('/api/realtime/settings', {
      method: 'PUT', body: JSON.stringify(Object.fromEntries(new FormData(event.target))),
    });
    renderStatus();
    $('#settings-dialog').close();
    toast(state.realtime.ready ? '千问配置已保存。录音时将连接 API。' : '地域与业务空间已保存，还需设置 API Key 并重启服务。');
  } catch (error) { toast(error.message, true); }
};
$('#rename').onclick = () => {
  const form = $('#rename-form'); form.elements.title.value = state.detail.title;
  form.elements.folder.value = state.detail.folder; $('#rename-dialog').showModal();
};
$('#rename-form').onsubmit = async (event) => {
  event.preventDefault();
  try {
    await api(`/api/sessions/${state.selected}`, { method: 'PATCH', body: JSON.stringify(Object.fromEntries(new FormData(event.target))) });
    $('#rename-dialog').close(); await refresh();
  } catch (error) { toast(error.message, true); }
};
$('#delete').onclick = async () => {
  if (state.recording) return toast('请先结束录音。');
  if (!confirm(`删除“${state.detail.title}”及其本地音频和笔记？此操作无法撤销。`)) return;
  try {
    await api(`/api/sessions/${state.selected}`, { method: 'DELETE' });
    state.selected = null; state.detail = null; state.signature = '';
    localStorage.removeItem('selected-session'); $('#player').pause(); $('#player').removeAttribute('src');
    await refresh();
    if (!state.selected) location.reload();
  } catch (error) { toast(error.message, true); }
};
$('#export').onclick = () => {
  if (state.selected) location.href = `/api/sessions/${state.selected}/export/${$('#export-format').value}`;
};
$('#translate').onclick = () => runAction('translation');
$('#summarize').onclick = () => runAction('summary');
$('#summary-in-notes').onclick = () => runAction('summary');
$('#question-form').onsubmit = async (event) => {
  event.preventDefault();
  const question = $('#question').value.trim();
  if (!question || !state.selected) return;
  try {
    await api(`/api/sessions/${state.selected}/questions`, { method: 'POST', body: JSON.stringify({ question }) });
    $('#question').value = ''; toast('正在阅读这段录音…'); await refresh();
  } catch (error) { toast(error.message, true); }
};
window.addEventListener('beforeunload', (event) => {
  if (state.recording || state.uploads.length) { event.preventDefault(); event.returnValue = ''; }
});
refresh();
setInterval(refresh, 1800);
