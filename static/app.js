const BASE = (window.VOXCLONE_BASE || "").replace(/\/$/, "");
const url = (path) => BASE + (path.startsWith("/") ? path : "/" + path);

const $ = (id) => document.getElementById(id);

const statusEl = $("status");
const speakerSelect = $("speakerSelect");
const ttsText = $("ttsText");
const btnSpeak = $("btnSpeak");
const player = $("player");
const downloadLink = $("downloadLink");
const ttsMsg = $("ttsMsg");
const ttsTiming = $("ttsTiming");
const cloneHints = $("cloneHints");
const cloneScript = $("cloneScript");
const transcript = $("transcript");
const btnCopyScript = $("btnCopyScript");
const btnClone = $("btnClone");
const cloneMsg = $("cloneMsg");

let lastBlobUrl = null;
let speakAbort = null;
let audioCtx = null;
let activeSources = [];
const SAMPLE_RATE_FALLBACK = 48000;

function setTiming(firstMs, doneMs) {
  if (!firstMs && !doneMs) {
    ttsTiming.hidden = true;
    ttsTiming.innerHTML = "";
    return;
  }
  const bits = [];
  if (firstMs != null) {
    bits.push(`<span><span class="k">首包</span> <span class="v">${Math.round(firstMs)} ms</span></span>`);
  }
  if (doneMs != null) {
    bits.push(`<span><span class="k">收完</span> <span class="v">${(doneMs / 1000).toFixed(2)} s</span></span>`);
  } else {
    bits.push(`<span class="k">流式播放中…</span>`);
  }
  ttsTiming.innerHTML = bits.join("");
  ttsTiming.hidden = false;
}

function stopStreamPlayback() {
  for (const src of activeSources) {
    try {
      src.stop();
    } catch {
      /* already stopped */
    }
  }
  activeSources = [];
}

function pcm16ToWavBlob(pcm, sampleRate) {
  const header = new ArrayBuffer(44);
  const v = new DataView(header);
  const writeStr = (offset, s) => {
    for (let i = 0; i < s.length; i++) v.setUint8(offset + i, s.charCodeAt(i));
  };
  writeStr(0, "RIFF");
  v.setUint32(4, 36 + pcm.byteLength, true);
  writeStr(8, "WAVE");
  writeStr(12, "fmt ");
  v.setUint32(16, 16, true);
  v.setUint16(20, 1, true);
  v.setUint16(22, 1, true);
  v.setUint32(24, sampleRate, true);
  v.setUint32(28, sampleRate * 2, true);
  v.setUint16(32, 2, true);
  v.setUint16(34, 16, true);
  writeStr(36, "data");
  v.setUint32(40, pcm.byteLength, true);
  return new Blob([header, pcm], { type: "audio/wav" });
}

function schedulePcm(ctx, pcmView, sampleRate, nextTime) {
  const samples = pcmView.byteLength / 2;
  if (!samples) return nextTime;
  const dv = new DataView(pcmView.buffer, pcmView.byteOffset, pcmView.byteLength);
  const f32 = new Float32Array(samples);
  for (let i = 0; i < samples; i++) {
    f32[i] = dv.getInt16(i * 2, true) / 32768;
  }
  const buffer = ctx.createBuffer(1, f32.length, sampleRate);
  buffer.copyToChannel(f32, 0);
  const src = ctx.createBufferSource();
  src.buffer = buffer;
  src.connect(ctx.destination);
  const startAt = Math.max(nextTime, ctx.currentTime + 0.02);
  src.start(startAt);
  activeSources.push(src);
  return startAt + buffer.duration;
}

function setMsg(el, text, kind = "") {
  el.textContent = text || "";
  el.className = "msg" + (kind ? ` ${kind}` : "");
}

function errDetail(err) {
  if (typeof err?.detail === "string") return err.detail;
  if (Array.isArray(err?.detail)) {
    return err.detail.map((d) => d.msg || JSON.stringify(d)).join("; ");
  }
  return null;
}

async function refreshSpeakers(prefer) {
  const res = await fetch(url("/api/speakers"));
  const data = await res.json();
  const list = data.speakers || [];
  speakerSelect.innerHTML = "";
  if (!list.length) {
    const opt = document.createElement("option");
    opt.value = "";
    opt.textContent = "暂无音色，请先在下方复刻";
    speakerSelect.appendChild(opt);
    return;
  }
  for (const s of list) {
    const opt = document.createElement("option");
    opt.value = s.name;
    opt.textContent = s.name;
    speakerSelect.appendChild(opt);
  }
  if (prefer && list.some((s) => s.name === prefer)) {
    speakerSelect.value = prefer;
  }
}

async function boot() {
  try {
    const [health, script] = await Promise.all([
      fetch(url("/health")).then((r) => r.json()),
      fetch(url("/api/clone-script")).then((r) => r.json()),
    ]);
    const speakers = (health.speakers || []).join(", ") || "无";
    const baseHint = health.base_path ? ` · base=${health.base_path}` : "";
    statusEl.textContent = `模型: ${health.status} · device=${health.device}${baseHint} · speakers=[${speakers}]`;
    cloneScript.textContent = script.script || "";
    cloneHints.textContent = script.hints || "";
    transcript.value = script.script || "";
    await refreshSpeakers();
  } catch (e) {
    statusEl.textContent = "无法连接服务: " + e;
  }
}

btnCopyScript.addEventListener("click", async () => {
  const t = cloneScript.textContent || "";
  try {
    await navigator.clipboard.writeText(t);
    setMsg(cloneMsg, "文案已复制", "ok");
  } catch {
    setMsg(cloneMsg, "复制失败，请手动选中文案", "error");
  }
});

btnSpeak.addEventListener("click", async () => {
  const speaker = speakerSelect.value;
  const text = ttsText.value.trim();
  if (!speaker) {
    setMsg(ttsMsg, "请先复刻并选择音色", "error");
    return;
  }
  if (!text) {
    setMsg(ttsMsg, "请输入要朗读的文本", "error");
    return;
  }
  if (speakAbort) speakAbort.abort();
  speakAbort = new AbortController();
  stopStreamPlayback();
  btnSpeak.disabled = true;
  setTiming();
  setMsg(ttsMsg, "正在出首包…");
  const t0 = performance.now();
  let firstMs = null;
  try {
    if (!audioCtx) audioCtx = new AudioContext({ sampleRate: SAMPLE_RATE_FALLBACK });
    await audioCtx.resume();
    const res = await fetch(url("/api/tts/stream"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text, speaker }),
      signal: speakAbort.signal,
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(errDetail(err) || `HTTP ${res.status}`);
    }
    if (!res.body) throw new Error("浏览器不支持流式读取");
    const sampleRate = Number(res.headers.get("X-Sample-Rate")) || SAMPLE_RATE_FALLBACK;
    const reader = res.body.getReader();
    const parts = [];
    let leftover = new Uint8Array(0);
    let nextTime = audioCtx.currentTime + 0.05;
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      if (!value || !value.length) continue;
      if (firstMs == null) {
        firstMs = performance.now() - t0;
        setTiming(firstMs);
        setMsg(ttsMsg, "首包已到，继续生成…");
      }
      const merged = new Uint8Array(leftover.length + value.length);
      merged.set(leftover, 0);
      merged.set(value, leftover.length);
      const n = merged.length & ~1;
      if (n) {
        const even = merged.subarray(0, n);
        parts.push(even.slice());
        nextTime = schedulePcm(audioCtx, even, sampleRate, nextTime);
      }
      leftover = merged.subarray(n);
    }
    const doneMs = performance.now() - t0;
    setTiming(firstMs, doneMs);
    const extra = leftover.length >= 2 ? leftover.subarray(0, leftover.length & ~1) : null;
    const total = parts.reduce((acc, p) => acc + p.length, extra ? extra.length : 0);
    const pcm = new Uint8Array(total);
    let offset = 0;
    for (const p of parts) {
      pcm.set(p, offset);
      offset += p.length;
    }
    if (extra) pcm.set(extra, offset);
    const blob = pcm16ToWavBlob(pcm, sampleRate);
    if (lastBlobUrl) URL.revokeObjectURL(lastBlobUrl);
    lastBlobUrl = URL.createObjectURL(blob);
    player.src = lastBlobUrl;
    downloadLink.href = lastBlobUrl;
    downloadLink.hidden = false;
    const firstText = firstMs != null ? `首包 ${Math.round(firstMs)} ms` : "无首包";
    setMsg(ttsMsg, `${firstText} · 收完 ${(doneMs / 1000).toFixed(2)} s`, "ok");
  } catch (e) {
    if (e.name === "AbortError") return;
    setMsg(ttsMsg, String(e.message || e), "error");
  } finally {
    btnSpeak.disabled = false;
  }
});

btnClone.addEventListener("click", async () => {
  const name = $("newName").value.trim();
  const file = $("audioFile").files[0];
  if (!name) {
    setMsg(cloneMsg, "请填写音色名", "error");
    return;
  }
  if (!file) {
    setMsg(cloneMsg, "请上传音频文件", "error");
    return;
  }
  const fd = new FormData();
  fd.append("name", name);
  fd.append("audio", file);
  fd.append("transcript", transcript.value.trim() || cloneScript.textContent || "");
  btnClone.disabled = true;
  setMsg(cloneMsg, "上传并转码中…");
  try {
    const res = await fetch(url("/api/speakers"), { method: "POST", body: fd });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(errDetail(data) || `HTTP ${res.status}`);
    let msg = `已保存音色「${data.speaker}」（${data.duration_sec}s）`;
    if (data.warning) msg += " · " + data.warning;
    setMsg(cloneMsg, msg, "ok");
    await refreshSpeakers(data.speaker);
  } catch (e) {
    setMsg(cloneMsg, String(e.message || e), "error");
  } finally {
    btnClone.disabled = false;
  }
});

boot();
