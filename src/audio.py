"""Audio processing: reading files, exact resampling, the mid/side split and writing WAVs. No Qt.

Audio is handled as float64 arrays of shape (frames, 2) at RATE. It is rounded to float32 only once, when written.
"""

import math
import struct
from collections.abc import Callable
from pathlib import Path

import numpy as np
import soundfile

import strings

RATE = 44100
CHANNELS = 2

# Resampling: input samples within NEAR of an output time are summed directly; the rest through TERMS terms of a
# series whose ratio is below 1/NEAR, so the series is truncated at under NEAR**-TERMS (about 1e-18) relative.
NEAR = 32
TERMS = 12
NEAR_BLOCK = 8192  # output frames per block of the direct sum

WAVE_FORMAT_IEEE_FLOAT = 3
NO_SIZE = 0xFFFFFFFF  # the largest 32-bit size; RF64 files put it where the real size is too big
MAX_WAV_DATA = NO_SIZE - 50  # the most audio a plain WAV holds: its RIFF size also counts 50 bytes of header


class AudioError(Exception):
    """A file that can't be read or written. The message is shown to the user."""


class Cancelled(Exception):
    """Raised by long operations when their `cancelled` callback returns True."""


# --- Reading ---

def info(path: str) -> tuple[int, int]:
    """(sample rate, channel count) of an audio file.

    Raises AudioError if it can't be read as audio, which includes files with no samples.
    """
    try:
        details = soundfile.info(path)
    except (soundfile.LibsndfileError, RuntimeError, OSError):
        details = None
    if details is None or details.frames <= 0:
        raise AudioError(strings.AUDIO_UNREADABLE.format(file=Path(path).name))
    return details.samplerate, details.channels


def read(path: str) -> tuple[np.ndarray, int, int]:
    """Read an audio file as float64 stereo. Returns (frames × 2 array, sample rate, channels in the file).

    Mono files are copied to both channels. Raises AudioError for unreadable files (including files with no
    samples) or more than 2 channels.
    """
    try:
        data, rate = soundfile.read(path, dtype="float64", always_2d=True)
    except (soundfile.LibsndfileError, RuntimeError, OSError):
        data = None
    if data is None or len(data) == 0:
        raise AudioError(strings.AUDIO_UNREADABLE.format(file=Path(path).name))
    channels = data.shape[1]
    if channels == 1:
        data = np.repeat(data, 2, axis=1)
    elif channels != 2:
        raise AudioError(strings.AUDIO_TOO_MANY_CHANNELS.format(file=Path(path).name, channels=channels))
    return np.ascontiguousarray(data), rate, channels


# --- Resampling ---

def _cos_sin_pi(numerator: np.ndarray, denominator: int) -> tuple[np.ndarray, np.ndarray]:
    """cos and sin of π·numerator/denominator for integer numerators, reduced exactly before the float maths.

    Multiples of a quarter turn come out exact (0 and ±1).
    """
    turns = np.mod(numerator, 2 * denominator)  # angle = π·turns/denominator, in [0, 2π)
    angle = np.pi * turns / denominator
    cos, sin = np.cos(angle), np.sin(angle)
    quarter = (2 * turns) % denominator == 0
    index = (2 * turns[quarter]) // denominator  # 0..3
    cos[quarter] = np.array([1.0, 0.0, -1.0, 0.0])[index]
    sin[quarter] = np.array([0.0, 1.0, 0.0, -1.0])[index]
    return cos, sin


def _fast_length(n: int) -> int:
    """The smallest number ≥ n with no prime factor above 5, which FFTs handle quickly."""
    best = 1 << max(0, (n - 1).bit_length())
    five = 1
    while five < best:
        three = five
        while three < best:
            length = three
            while length < n:
                length *= 2
            best = min(best, length)
            three *= 3
        five *= 5
    return best


def resampled_length(frames: int, rate_in: int, rate_out: int) -> int:
    """Output frames covering the same duration: every output time n/rate_out before frames/rate_in."""
    return -(-frames * rate_out // rate_in)


def resample(x: np.ndarray, rate_in: int, rate_out: int, cancelled: Callable[[], bool] | None = None) -> np.ndarray:
    """Resample (frames × channels) audio by ideal band-limited interpolation.

    This evaluates the Whittaker–Shannon sum over every input sample, with no windowing or periodic wrap-around:

        y(t) = Σ_k x[k] · sin(π·fc·(t − k)) / (π·(t − k))      t in input samples

    where fc = min(1, rate_out / rate_in): a brick-wall low-pass at the lower of the two Nyquist frequencies,
    which also removes anything that would alias when going down. Samples outside the file count as silence.

    Computing it directly takes frames² operations, so it's rearranged without approximation. Splitting the sine,
    sin(π·fc·(t − k)) = sin(π·fc·t)·cos(π·fc·k) − cos(π·fc·t)·sin(π·fc·k), leaves two sums of the form
    Σ_k b[k] / (t − k). With t − k = j + φ (j whole, 0 ≤ φ < 1), terms with |j| < NEAR are added directly; for
    the rest 1/(j + φ) = Σ_r (−φ)^r / j^(r+1), and each power is an exact linear convolution done by FFT. The
    result matches the direct sum to float64 rounding.

    Raises Cancelled if `cancelled` returns True while it runs.
    """
    if rate_in == rate_out:
        return x.copy()
    frames, channels = x.shape
    g = math.gcd(rate_in, rate_out)
    up, down = rate_out // g, rate_in // g
    fc_num, fc_den = (up, down) if up < down else (1, 1)
    fc = fc_num / fc_den

    m = resampled_length(frames, rate_in, rate_out)
    position = np.arange(m, dtype=np.int64) * down  # output time × up, in input samples
    q = position // up                               # whole part of each output time
    phi = (position % up) / up                       # fractional part
    cos_t, sin_t = _cos_sin_pi(position * fc_num, fc_den * up)
    cos_k, sin_k = _cos_sin_pi(np.arange(frames, dtype=np.int64) * fc_num, fc_den)

    # Rows: x·cos(π·fc·k) and x·sin(π·fc·k) for each channel (rows keep each FFT on contiguous memory).
    b = np.empty((2 * channels, frames))
    b[0::2] = x.T * cos_k
    b[1::2] = x.T * sin_k

    # Near: j = q − k in (−NEAR, NEAR), in blocks of outputs. Padding with NEAR zeros each side keeps every k in
    # range; window i of `windows` holds padded[i : i + 2·NEAR − 1], which is k = q + NEAR − 1 down to q − NEAR + 1
    # for i = q + 1, i.e. j = −NEAR + 1 up to NEAR − 1 after reversing.
    padded = np.zeros((2 * channels, frames + 2 * NEAR))
    padded[:, NEAR:NEAR + frames] = b
    windows = np.lib.stride_tricks.sliding_window_view(padded, 2 * NEAR - 1, axis=1)[:, :, ::-1]
    js = np.arange(-NEAR + 1, NEAR)
    total = np.empty((2 * channels, m))
    for start in range(0, m, NEAR_BLOCK):
        if cancelled and cancelled():
            raise Cancelled
        block = slice(start, start + NEAR_BLOCK)
        offsets = js + phi[block, None]
        offsets[offsets == 0] = np.inf  # t = k exactly: that term is added at the end
        total[:, block] = np.einsum("cbj,bj->cb", windows[:, q[block] + 1], 1 / offsets)

    # Far: |j| ≥ NEAR, as circular convolutions long enough (≥ 2·frames − 1) that nothing wraps around.
    if frames > NEAR:
        size = _fast_length(2 * frames - 1)
        spectrum = np.fft.rfft(b, size)
        offsets = np.arange(NEAR, frames, dtype=np.float64)
        horner = np.zeros((2 * channels, m))
        for r in reversed(range(TERMS)):
            if cancelled and cancelled():
                raise Cancelled
            kernel = np.zeros(size)
            power = offsets ** -(r + 1)
            kernel[NEAR:frames] = power
            kernel[size - frames + 1:size - NEAR + 1] = ((-1) ** (r + 1) * power)[::-1]
            far = np.fft.irfft(spectrum * np.fft.rfft(kernel), size)
            horner *= -phi
            horner += far[:, q]
            del far
        total += horner

    y = ((sin_t * total[0::2] - cos_t * total[1::2]) / np.pi).T
    exact = phi == 0  # output times that fall on an input sample: the k = t term is fc·x[k]
    y[exact] += fc * x[q[exact]]
    return np.ascontiguousarray(y)


# --- Processing ---

def split_mid_side(x: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Split stereo audio into mid (M, M) and side (S, −S), where M = (L + R)/2 and S = (L − R)/2.

    Mid + side gives back L on the left and R on the right exactly. The halving is exact in floating point.
    """
    left, right = x[:, 0], x[:, 1]
    mid = (left + right) / 2
    side = (left - right) / 2
    return np.column_stack((mid, mid)), np.column_stack((side, -side))


def peak_dbfs(samples: np.ndarray) -> float:
    """The highest absolute sample value in dBFS (−inf for silence)."""
    peak = float(np.max(np.abs(samples))) if samples.size else 0.0
    return 20 * math.log10(peak) if peak > 0 else -math.inf


# --- Writing ---

def to_float32(x: np.ndarray) -> np.ndarray:
    """Round audio to float32, as it will be written."""
    return np.ascontiguousarray(x, dtype="<f4")


def write_wav(path: str, samples: np.ndarray, rate: int = RATE) -> None:
    """Write float32 (frames × channels) audio as a 32-bit float WAV with no metadata.

    The file holds only the chunks the format needs: "fmt " (IEEE float), "fact" (required for non-PCM WAVs)
    and "data". A plain WAV's sizes are 32-bit, so audio too big for one is written as RF64 (EBU Tech 3306)
    instead: "RF64" in place of "RIFF", the 32-bit sizes set to 0xFFFFFFFF, and a "ds64" chunk first that holds
    the real 64-bit sizes. Raises OSError if the file can't be written.
    """
    samples = to_float32(samples)
    frames, channels = samples.shape
    data_size = samples.nbytes
    block = 4 * channels
    fmt = struct.pack("<HHIIHHH", WAVE_FORMAT_IEEE_FLOAT, channels, rate, rate * block, block, 32, 0)
    ds64_size = 28
    rf64 = data_size > MAX_WAV_DATA
    chunks_size = (8 + len(fmt)) + (8 + 4) + (8 + data_size) + ((8 + ds64_size) if rf64 else 0)
    riff_size = 4 + chunks_size  # "WAVE" and the chunks
    with open(path, "wb") as file:
        if rf64:
            file.write(b"RF64" + struct.pack("<I", NO_SIZE) + b"WAVE")
            # riff size, data size, sample count (frames), then an empty table of other chunks' sizes
            file.write(b"ds64" + struct.pack("<IQQQI", ds64_size, riff_size, data_size, frames, 0))
        else:
            file.write(b"RIFF" + struct.pack("<I", riff_size) + b"WAVE")
        file.write(b"fmt " + struct.pack("<I", len(fmt)) + fmt)
        file.write(b"fact" + struct.pack("<II", 4, min(frames, NO_SIZE)))
        file.write(b"data" + struct.pack("<I", NO_SIZE if rf64 else data_size))
        samples.tofile(file)
