"""音频辅助：float→int16、起音高频软化。"""

from __future__ import annotations

import numpy as np

_INT16_FULL_SCALE = 32767


def float_to_int16_bytes(audio: np.ndarray) -> bytes:
    samples = np.asarray(audio, dtype=np.float32)
    if samples.size == 0:
        return b""
    clipped = np.clip(samples, -1.0, 1.0)
    return (clipped * _INT16_FULL_SCALE).astype(np.int16).tobytes()


def tame_head_harshness(
    audio: np.ndarray,
    sample_rate: int,
    *,
    tame_ms: int = 120,
    cutoff_hz: float = 7000.0,
) -> np.ndarray:
    samples = np.asarray(audio, dtype=np.float32)
    n = min(samples.size, int(sample_rate * tame_ms / 1000))
    if n <= 1:
        return samples
    alpha = 1.0 - float(np.exp(-2.0 * np.pi * cutoff_hz / sample_rate))
    head = samples[:n]
    try:
        from scipy.signal import lfilter

        smoothed = lfilter([alpha], [1.0, alpha - 1.0], head)
    except ImportError:
        smoothed = np.empty_like(head)
        acc = np.float32(0.0)
        for i, x in enumerate(head):
            acc += alpha * (x - acc)
            smoothed[i] = acc
    wet = np.linspace(1.0, 0.0, n, dtype=np.float32)
    out = samples.copy()
    out[:n] = smoothed * wet + head * (1.0 - wet)
    return out
