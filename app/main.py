"""VoxClone FastAPI：音色复刻 + 文本朗读。"""

from __future__ import annotations

import logging
import os
import shutil
import tempfile
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .audio_convert import ConvertError, convert_to_ref_wav
from .prompts import CLONE_HINTS, CLONE_SCRIPT
from .tts_engine import SPEAKER_DIR_RE, TTSEngine

load_dotenv(".env.local")
load_dotenv(".env")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("voxclone")

ROOT = Path(__file__).resolve().parent.parent
VOICES_DIR = os.environ.get("VOICES_DIR", str(ROOT / "voices"))
MAX_UPLOAD_MB = int(os.environ.get("MAX_UPLOAD_MB", "20"))
STATIC_DIR = ROOT / "static"

engine = TTSEngine(
    model_id=os.environ.get("TTS_MODEL", ""),
    voices_dir=VOICES_DIR,
    device=os.environ.get("TTS_DEVICE", "cuda"),
    cfg_value=float(os.environ.get("TTS_CFG_VALUE", "2.0")),
    inference_timesteps=int(os.environ.get("TTS_INFERENCE_TIMESTEPS", "10")),
    default_speaker=os.environ.get("TTS_DEFAULT_SPEAKER", ""),
)

app = FastAPI(title="VoxClone", version="0.1.0")


@app.on_event("startup")
def _startup() -> None:
    os.makedirs(VOICES_DIR, exist_ok=True)
    try:
        engine.load()
        logger.info("model ready")
    except Exception:
        # 允许先起服务再配模型；/health 会反映状态
        logger.exception("model load deferred / failed at startup")


@app.get("/health")
def health() -> dict:
    voices = engine.resolve_voices()
    return {
        "status": "ok" if engine.ready else "model_not_ready",
        "sample_rate": 48000,
        "model": engine.model_id,
        "device": engine.device,
        "voices_dir": VOICES_DIR,
        "speakers": sorted(voices.keys()),
    }


@app.get("/api/speakers")
def list_speakers() -> dict:
    voices = engine.resolve_voices()
    return {
        "speakers": [
            {"name": k, "ref_text": v["ref_text"]} for k, v in voices.items()
        ]
    }


@app.get("/api/clone-script")
def clone_script() -> dict:
    return {"script": CLONE_SCRIPT, "hints": CLONE_HINTS}


def _validate_speaker_name(name: str) -> str:
    name = name.strip()
    if not SPEAKER_DIR_RE.match(name):
        raise HTTPException(
            status_code=400,
            detail="音色名仅允许字母、数字、下划线、短横线（如 xiaoming）",
        )
    return name


@app.post("/api/speakers")
async def create_speaker(
    name: str = Form(...),
    audio: UploadFile = File(...),
    transcript: str | None = Form(None),
) -> dict:
    speaker = _validate_speaker_name(name)
    text = (transcript or "").strip() or CLONE_SCRIPT
    if not text:
        raise HTTPException(status_code=400, detail="transcript 不能为空")

    data = await audio.read()
    if not data:
        raise HTTPException(status_code=400, detail="空音频文件")
    if len(data) > MAX_UPLOAD_MB * 1024 * 1024:
        raise HTTPException(
            status_code=400, detail=f"文件过大，上限 {MAX_UPLOAD_MB}MB"
        )

    suffix = Path(audio.filename or "upload.bin").suffix.lower() or ".bin"
    out_dir = Path(VOICES_DIR) / speaker
    out_dir.mkdir(parents=True, exist_ok=True)
    ref_wav = out_dir / "ref.wav"
    ref_txt = out_dir / "ref.txt"

    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / f"upload{suffix}"
        src.write_bytes(data)
        try:
            dur = convert_to_ref_wav(str(src), str(ref_wav))
        except ConvertError as e:
            # 清理半成品
            if ref_wav.exists():
                ref_wav.unlink()
            raise HTTPException(status_code=400, detail=str(e)) from e

    ref_txt.write_text(text, encoding="utf-8")
    warn = None
    if dur < 8:
        warn = f"时长偏短（{dur:.1f}s），建议 8–30 秒"
    elif dur > 30:
        warn = f"时长偏长（{dur:.1f}s），建议 8–30 秒"

    return {
        "ok": True,
        "speaker": speaker,
        "duration_sec": round(dur, 2),
        "warning": warn,
        "ref_text": text,
    }


@app.delete("/api/speakers/{name}")
def delete_speaker(name: str) -> dict:
    speaker = _validate_speaker_name(name)
    d = Path(VOICES_DIR) / speaker
    if not d.is_dir():
        raise HTTPException(status_code=404, detail=f"speaker {speaker!r} not found")
    shutil.rmtree(d)
    return {"ok": True, "speaker": speaker}


class TTSRequest(BaseModel):
    text: str = Field(..., min_length=1)
    speaker: str


@app.post("/api/tts")
def tts(req: TTSRequest) -> Response:
    text = req.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="text 不能为空")
    speaker = _validate_speaker_name(req.speaker)
    if not engine.ready:
        try:
            engine.load()
        except Exception as e:
            raise HTTPException(status_code=503, detail=f"模型未就绪: {e}") from e
    try:
        wav = engine.synthesize_wav(text, speaker)
    except KeyError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        logger.exception("tts failed")
        raise HTTPException(status_code=500, detail=f"合成失败: {e}") from e
    return Response(
        content=wav,
        media_type="audio/wav",
        headers={"Content-Disposition": 'inline; filename="tts.wav"'},
    )


# 静态页放最后，避免盖住 API
if STATIC_DIR.is_dir():
    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
