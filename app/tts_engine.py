"""VoxCPM2 引擎：扫描 voices/、加载模型、合成 WAV。"""

from __future__ import annotations

import io
import logging
import os
import re
import wave
from typing import Any

import numpy as np

from .audio_utils import float_to_int16_bytes, tame_head_harshness
from .text_utils import DEFAULT_MAX_CHARS, split_text_for_tts

logger = logging.getLogger(__name__)

SAMPLE_RATE = 48000
SPEAKER_DIR_RE = re.compile(r"^[A-Za-z0-9_-]+$")


class TTSEngine:
    def __init__(
        self,
        *,
        model_id: str,
        voices_dir: str = "voices",
        device: str = "cuda",
        cfg_value: float = 2.0,
        inference_timesteps: int = 10,
        max_chars: int = DEFAULT_MAX_CHARS,
        default_speaker: str = "",
    ) -> None:
        self.model_id = model_id
        self.voices_dir = voices_dir
        self.device = device
        self.cfg_value = cfg_value
        self.inference_timesteps = inference_timesteps
        self.max_chars = max_chars
        self.default_speaker = default_speaker
        self._model: Any = None

    @property
    def ready(self) -> bool:
        return self._model is not None

    def resolve_voices(self) -> dict[str, dict[str, str]]:
        voices: dict[str, dict[str, str]] = {}
        root = self.voices_dir
        if not os.path.isdir(root):
            return voices
        for name in sorted(os.listdir(root)):
            if not SPEAKER_DIR_RE.match(name):
                continue
            d = os.path.join(root, name)
            if not os.path.isdir(d):
                continue
            ref_wav = os.path.join(d, "ref.wav")
            ref_txt = os.path.join(d, "ref.txt")
            if not (os.path.exists(ref_wav) and os.path.exists(ref_txt)):
                continue
            with open(ref_txt, encoding="utf-8") as f:
                text = f.read().strip()
            if not text:
                continue
            voices[name] = {"ref_wav": ref_wav, "ref_text": text}
        return voices

    def load(self) -> None:
        if self._model is not None:
            return
        if not self.model_id or self.model_id.startswith("/path/to"):
            raise RuntimeError("请设置 TTS_MODEL 为有效的 VoxCPM2 模型路径")

        from voxcpm import VoxCPM

        voices = self.resolve_voices()
        logger.info(
            "loading VoxCPM2 model=%s device=%s voices=%s",
            self.model_id,
            self.device,
            sorted(voices.keys()),
        )
        self._model = VoxCPM.from_pretrained(
            self.model_id, load_denoiser=False, optimize=False
        )

        # 有音色才热身；没有也允许启动（先上传复刻）
        if voices:
            warm_key = (
                self.default_speaker
                if self.default_speaker in voices
                else next(iter(voices))
            )
            warm = voices[warm_key]
            for _ in self._model.generate_streaming(
                text="你好。",
                prompt_wav_path=warm["ref_wav"],
                prompt_text=warm["ref_text"],
                reference_wav_path=warm["ref_wav"],
                cfg_value=self.cfg_value,
                inference_timesteps=self.inference_timesteps,
            ):
                pass

    def synthesize_wav(self, text: str, speaker: str) -> bytes:
        self.load()
        assert self._model is not None
        voices = self.resolve_voices()
        if speaker not in voices:
            raise KeyError(
                f"unknown speaker {speaker!r}; available: {sorted(voices.keys())}"
            )
        voice = voices[speaker]

        chunks: list[np.ndarray] = []
        first = True
        silence = np.zeros(int(0.25 * SAMPLE_RATE), dtype=np.float32)
        for piece in split_text_for_tts(text, max_chars=self.max_chars):
            for audio_chunk in self._model.generate_streaming(
                text=piece,
                prompt_wav_path=voice["ref_wav"],
                prompt_text=voice["ref_text"],
                reference_wav_path=voice["ref_wav"],
                cfg_value=self.cfg_value,
                inference_timesteps=self.inference_timesteps,
            ):
                chunk = np.asarray(audio_chunk, dtype=np.float32)
                if first:
                    first = False
                    chunk = tame_head_harshness(chunk, SAMPLE_RATE)
                    chunk = np.concatenate([silence, chunk])
                chunks.append(chunk)
        if not chunks:
            chunks.append(silence)
        else:
            chunks.append(silence)

        audio = np.concatenate(chunks)
        pcm = float_to_int16_bytes(audio)
        return _pcm16_to_wav_bytes(pcm, SAMPLE_RATE)


def _pcm16_to_wav_bytes(pcm: bytes, sample_rate: int) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(pcm)
    return buf.getvalue()
