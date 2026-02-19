"""Audio transcoding utilities for Twilio <-> OpenAI Realtime.

Twilio sends mu-law 8kHz audio; OpenAI Realtime expects PCM16 16kHz.
Pure-Python implementation (no audioop, removed in Python 3.13).
"""

import base64
import struct

# mu-law decoding table (ITU-T G.711)
_MULAW_DECODE_TABLE = [
    -32124, -31100, -30076, -29052, -28028, -27004, -25980, -24956,
    -23932, -22908, -21884, -20860, -19836, -18812, -17788, -16764,
    -15996, -15484, -14972, -14460, -13948, -13436, -12924, -12412,
    -11900, -11388, -10876, -10364, -9852, -9340, -8828, -8316,
    -7932, -7676, -7420, -7164, -6908, -6652, -6396, -6140,
    -5884, -5628, -5372, -5116, -4860, -4604, -4348, -4092,
    -3900, -3772, -3644, -3516, -3388, -3260, -3132, -3004,
    -2876, -2748, -2620, -2492, -2364, -2236, -2108, -1980,
    -1884, -1820, -1756, -1692, -1628, -1564, -1500, -1436,
    -1372, -1308, -1244, -1180, -1116, -1052, -988, -924,
    -876, -844, -812, -780, -748, -716, -684, -652,
    -620, -588, -556, -524, -492, -460, -428, -396,
    -372, -356, -340, -324, -308, -292, -276, -260,
    -244, -228, -212, -196, -180, -164, -148, -132,
    -120, -112, -104, -96, -88, -80, -72, -64,
    -56, -48, -40, -32, -24, -16, -8, 0,
    32124, 31100, 30076, 29052, 28028, 27004, 25980, 24956,
    23932, 22908, 21884, 20860, 19836, 18812, 17788, 16764,
    15996, 15484, 14972, 14460, 13948, 13436, 12924, 12412,
    11900, 11388, 10876, 10364, 9852, 9340, 8828, 8316,
    7932, 7676, 7420, 7164, 6908, 6652, 6396, 6140,
    5884, 5628, 5372, 5116, 4860, 4604, 4348, 4092,
    3900, 3772, 3644, 3516, 3388, 3260, 3132, 3004,
    2876, 2748, 2620, 2492, 2364, 2236, 2108, 1980,
    1884, 1820, 1756, 1692, 1628, 1564, 1500, 1436,
    1372, 1308, 1244, 1180, 1116, 1052, 988, 924,
    876, 844, 812, 780, 748, 716, 684, 652,
    620, 588, 556, 524, 492, 460, 428, 396,
    372, 356, 340, 324, 308, 292, 276, 260,
    244, 228, 212, 196, 180, 164, 148, 132,
    120, 112, 104, 96, 88, 80, 72, 64,
    56, 48, 40, 32, 24, 16, 8, 0,
]

_MULAW_BIAS = 0x84
_MULAW_CLIP = 32635


def _linear_to_mulaw(sample: int) -> int:
    """Encode a single 16-bit signed PCM sample to mu-law."""
    sign = 0
    if sample < 0:
        sign = 0x80
        sample = -sample
    sample = min(sample, _MULAW_CLIP)
    sample += _MULAW_BIAS

    exponent = 7
    mask = 0x4000
    while exponent > 0 and not (sample & mask):
        exponent -= 1
        mask >>= 1

    mantissa = (sample >> (exponent + 3)) & 0x0F
    return ~(sign | (exponent << 4) | mantissa) & 0xFF


def _ulaw_to_linear(data: bytes) -> bytes:
    """Convert mu-law bytes to PCM16 LE bytes."""
    samples = []
    for b in data:
        samples.append(_MULAW_DECODE_TABLE[b])
    return struct.pack(f"<{len(samples)}h", *samples)


def _linear_to_ulaw(data: bytes) -> bytes:
    """Convert PCM16 LE bytes to mu-law bytes."""
    n_samples = len(data) // 2
    samples = struct.unpack(f"<{n_samples}h", data)
    return bytes(_linear_to_mulaw(s) for s in samples)


def _upsample_2x(data: bytes) -> bytes:
    """Upsample PCM16 LE by 2x with linear interpolation (8kHz -> 16kHz)."""
    n_samples = len(data) // 2
    if n_samples == 0:
        return b""
    samples = struct.unpack(f"<{n_samples}h", data)
    out = []
    for i in range(n_samples - 1):
        out.append(samples[i])
        out.append((samples[i] + samples[i + 1]) // 2)
    out.append(samples[-1])
    out.append(samples[-1])
    return struct.pack(f"<{len(out)}h", *out)


def _downsample_2x(data: bytes) -> bytes:
    """Downsample PCM16 LE by 2x (16kHz -> 8kHz) — take every other sample."""
    n_samples = len(data) // 2
    samples = struct.unpack(f"<{n_samples}h", data)
    out = samples[::2]
    return struct.pack(f"<{len(out)}h", *out)


def mulaw_to_pcm16(mulaw_b64: str) -> str:
    """Convert mu-law 8kHz base64 audio to PCM16 16kHz base64.

    Steps:
    1. Decode base64 mu-law
    2. Convert mu-law -> linear PCM16 at 8kHz
    3. Upsample 8kHz -> 16kHz
    4. Encode to base64
    """
    mulaw_bytes = base64.b64decode(mulaw_b64)
    pcm_8k = _ulaw_to_linear(mulaw_bytes)
    pcm_16k = _upsample_2x(pcm_8k)
    return base64.b64encode(pcm_16k).decode("ascii")


def pcm16_to_mulaw(pcm16_b64: str) -> str:
    """Convert PCM16 16kHz base64 audio to mu-law 8kHz base64.

    Steps:
    1. Decode base64 PCM16
    2. Downsample 16kHz -> 8kHz
    3. Convert linear PCM16 -> mu-law
    4. Encode to base64
    """
    pcm_bytes = base64.b64decode(pcm16_b64)
    pcm_8k = _downsample_2x(pcm_bytes)
    mulaw_bytes = _linear_to_ulaw(pcm_8k)
    return base64.b64encode(mulaw_bytes).decode("ascii")
