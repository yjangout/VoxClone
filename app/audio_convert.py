"""用 ffmpeg 把 mp3/m4a/wav 等转成克隆用的单声道 PCM16 WAV。"""

from __future__ import annotations

import os
import shutil
import subprocess
import wave

MIN_DUR, MAX_DUR = 8.0, 30.0


class ConvertError(RuntimeError):
    pass


def ensure_ffmpeg() -> str:
    path = shutil.which("ffmpeg")
    if not path:
        raise ConvertError(
            "未找到 ffmpeg。请先安装（macOS: brew install ffmpeg；Linux: apt install ffmpeg）"
        )
    return path


def convert_to_ref_wav(
    input_path: str,
    output_path: str,
    *,
    sample_rate: int = 24000,
    start: float | None = None,
    duration: float | None = None,
) -> float:
    """转码并返回时长（秒）。"""
    if not os.path.exists(input_path):
        raise ConvertError(f"输入文件不存在: {input_path}")
    ffmpeg = ensure_ffmpeg()
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

    cmd = [ffmpeg, "-y"]
    if start is not None:
        cmd += ["-ss", str(start)]
    cmd += ["-i", input_path]
    if duration is not None:
        cmd += ["-t", str(duration)]
    cmd += ["-ac", "1", "-ar", str(sample_rate), "-c:a", "pcm_s16le", output_path]

    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise ConvertError(f"ffmpeg 失败: {proc.stderr[-500:]}")

    with wave.open(output_path, "rb") as w:
        frames, rate = w.getnframes(), w.getframerate()
    dur = frames / float(rate)
    return dur
