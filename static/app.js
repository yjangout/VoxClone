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
const cloneHints = $("cloneHints");
const cloneScript = $("cloneScript");
const transcript = $("transcript");
const btnCopyScript = $("btnCopyScript");
const btnClone = $("btnClone");
const cloneMsg = $("cloneMsg");

let lastBlobUrl = null;

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
  btnSpeak.disabled = true;
  setMsg(ttsMsg, "合成中，请稍候…");
  try {
    const res = await fetch(url("/api/tts"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text, speaker }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(errDetail(err) || `HTTP ${res.status}`);
    }
    const blob = await res.blob();
    if (lastBlobUrl) URL.revokeObjectURL(lastBlobUrl);
    lastBlobUrl = URL.createObjectURL(blob);
    player.src = lastBlobUrl;
    downloadLink.href = lastBlobUrl;
    downloadLink.hidden = false;
    await player.play().catch(() => {});
    setMsg(ttsMsg, "完成", "ok");
  } catch (e) {
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
