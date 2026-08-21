"""VoxClone FastAPI：音色复刻 + 文本朗读。"""

from __future__ import annotations

import logging
import os
import shutil
import tempfile
import time
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.concurrency import iterate_in_threadpool
from starlette.types import ASGIApp, Receive, Scope, Send

from .audio_convert import ConvertError, convert_to_ref_wav
from .prompts import CLONE_HINTS, CLONE_SCRIPT
from .tts_engine import SAMPLE_RATE, SPEAKER_DIR_RE, TTSEngine

load_dotenv(".env.local")
load_dotenv(".env")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("voxclone")

ROOT = Path(__file__).resolve().parent.parent
VOICES_DIR = os.environ.get("VOICES_DIR", str(ROOT / "voices"))
MAX_UPLOAD_MB = int(os.environ.get("MAX_UPLOAD_MB", "20"))
STATIC_DIR = ROOT / "static"
# 反代子路径，例如 /xx/voxclone；本地直连留空
BASE_PATH = os.environ.get("BASE_PATH", "").strip().rstrip("/")


engine = TTSEngine(
    model_id=os.environ.get("TTS_MODEL", ""),
    voices_dir=VOICES_DIR,
    device=os.environ.get("TTS_DEVICE", "cuda"),
    cfg_value=float(os.environ.get("TTS_CFG_VALUE", "2.0")),
    inference_timesteps=int(os.environ.get("TTS_INFERENCE_TIMESTEPS", "10")),
    default_speaker=os.environ.get("TTS_DEFAULT_SPEAKER", ""),
)


class TTSRequest(BaseModel):
    text: str = Field(..., min_length=1)
    speaker: str


class StripBasePathMiddleware:
    """nginx 若原样转发 /xx/voxclone/...，剥掉前缀后再走本应用路由。

    必须用纯 ASGI 中间件：BaseHTTPMiddleware 会弄丢 POST body，导致 /api/tts 422。
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and BASE_PATH:
            path = scope.get("path") or ""
            if path == BASE_PATH or path.startswith(BASE_PATH + "/"):
                scope = dict(scope)
                stripped = path[len(BASE_PATH) :] or "/"
                scope["path"] = stripped
                scope["raw_path"] = stripped.encode("utf-8")
        await self.app(scope, receive, send)


def create_app() -> FastAPI:
    api = FastAPI(title="VoxClone", version="0.1.0")
    if BASE_PATH:
        api.add_middleware(StripBasePathMiddleware)

    @api.exception_handler(RequestValidationError)
    async def _validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        logger.warning("422 %s %s detail=%s", request.method, request.url.path, exc.errors())
        return JSONResponse(status_code=422, content={"detail": exc.errors()})

    @api.on_event("startup")
    def _startup() -> None:
        os.makedirs(VOICES_DIR, exist_ok=True)
        logger.info("BASE_PATH=%r", BASE_PATH or "")
        try:
            engine.load()
            logger.info("model ready")
        except Exception:
            logger.exception("model load deferred / failed at startup")

    @api.get("/health")
    def health() -> dict:
        voices = engine.resolve_voices()
        return {
            "status": "ok" if engine.ready else "model_not_ready",
            "sample_rate": 48000,
            "model": engine.model_id,
            "device": engine.device,
            "voices_dir": VOICES_DIR,
            "base_path": BASE_PATH or "",
            "speakers": sorted(voices.keys()),
        }

    @api.get("/api/speakers")
    def list_speakers() -> dict:
        voices = engine.resolve_voices()
        return {
            "speakers": [
                {"name": k, "ref_text": v["ref_text"]} for k, v in voices.items()
            ]
        }

    @api.get("/api/clone-script")
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

    @api.post("/api/speakers")
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

    @api.delete("/api/speakers/{name}")
    def delete_speaker(name: str) -> dict:
        speaker = _validate_speaker_name(name)
        d = Path(VOICES_DIR) / speaker
        if not d.is_dir():
            raise HTTPException(status_code=404, detail=f"speaker {speaker!r} not found")
        shutil.rmtree(d)
        return {"ok": True, "speaker": speaker}

    def _prepare_tts(req: TTSRequest) -> tuple[str, str]:
        text = req.text.strip()
        if not text:
            raise HTTPException(status_code=400, detail="text 不能为空")
        speaker = _validate_speaker_name(req.speaker)
        if not engine.ready:
            try:
                engine.load()
            except Exception as e:
                raise HTTPException(status_code=503, detail=f"模型未就绪: {e}") from e
        voices = engine.resolve_voices()
        if speaker not in voices:
            raise HTTPException(
                status_code=400,
                detail=f"unknown speaker {speaker!r}; available: {sorted(voices.keys())}",
            )
        return text, speaker

    @api.post("/api/tts")
    def tts(req: TTSRequest) -> Response:
        text, speaker = _prepare_tts(req)
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

    @api.post("/api/tts/stream")
    def tts_stream(req: TTSRequest) -> StreamingResponse:
        text, speaker = _prepare_tts(req)

        def _gen():
            first = True
            t0 = time.perf_counter()
            try:
                for pcm in engine.iter_pcm_bytes(text, speaker):
                    if first:
                        first = False
                        logger.info(
                            "tts stream first chunk speaker=%s ms=%.0f",
                            speaker,
                            (time.perf_counter() - t0) * 1000,
                        )
                    yield pcm
            except Exception:
                logger.exception("tts stream failed speaker=%s", speaker)

        return StreamingResponse(
            iterate_in_threadpool(_gen()),
            media_type="application/octet-stream",
            headers={
                "Content-Disposition": 'inline; filename="tts.pcm"',
                "Cache-Control": "no-cache, no-store",
                "X-Accel-Buffering": "no",
                "X-Sample-Rate": str(SAMPLE_RATE),
                "X-Channels": "1",
                "X-Sample-Width": "2",
            },
        )

    if STATIC_DIR.is_dir():

        @api.get("/")
        def index() -> HTMLResponse:
            html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
            html = html.replace("__BASE_PATH__", BASE_PATH)
            return HTMLResponse(html)

        api.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    return api


app = create_app()
