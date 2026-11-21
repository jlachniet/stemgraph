import math
import re
import struct

import numpy as np
import pytest
import soundfile

import audio
from editor import AUDIO_FILTER


def direct_resample(x: np.ndarray, rate_in: int, rate_out: int) -> np.ndarray:
    """The Whittaker–Shannon sum evaluated term by term: the definition resample() must match."""
    g = math.gcd(rate_in, rate_out)
    up, down = rate_out // g, rate_in // g
    fc = min(1.0, up / down)
    k = np.arange(len(x))
    out = np.empty((audio.resampled_length(len(x), rate_in, rate_out), x.shape[1]))
    for n in range(len(out)):
        out[n] = fc * np.sinc(fc * (n * down / up - k)) @ x
    return out


# --- Resampling ---


@pytest.mark.parametrize("rate_in", [8000, 22050, 32000, 48000, 88200, 96000])
def test_resample_matches_the_direct_sinc_sum(rate_in):
    x = np.random.default_rng(rate_in).uniform(-1, 1, (1500, 2))  # white noise: energy right up to Nyquist
    y = audio.resample(x, rate_in, audio.RATE)
    assert y.shape == (audio.resampled_length(1500, rate_in, audio.RATE), 2)
    assert np.max(np.abs(y - direct_resample(x, rate_in, audio.RATE))) < 1e-11


def test_resample_handles_files_shorter_than_the_near_window():
    x = np.random.default_rng(0).uniform(-1, 1, (5, 2))
    assert np.allclose(audio.resample(x, 48000, audio.RATE), direct_resample(x, 48000, audio.RATE), atol=1e-12)


def test_upsampling_by_two_keeps_the_original_samples_exactly():
    x = np.random.default_rng(1).uniform(-1, 1, (1000, 2))
    y = audio.resample(x, 22050, 44100)
    assert np.array_equal(y[0::2], x)


def test_resampling_to_the_same_rate_copies():
    x = np.ones((10, 2))
    y = audio.resample(x, audio.RATE, audio.RATE)
    assert np.array_equal(y, x) and y is not x


def test_resampled_length_covers_the_same_duration():
    assert audio.resampled_length(48000, 48000, 44100) == 44100
    assert audio.resampled_length(1, 48000, 44100) == 1
    assert audio.resampled_length(161, 48000, 44100) == 148  # 160 input samples = 147 output samples


def test_resample_can_be_cancelled():
    with pytest.raises(audio.Cancelled):
        audio.resample(np.zeros((1000, 2)), 48000, audio.RATE, cancelled=lambda: True)


# --- Mid/side ---


def test_mid_plus_side_gives_back_the_input_exactly():
    x = np.random.default_rng(2).uniform(-1, 1, (10000, 2)).astype(np.float32).astype(np.float64)
    mid, side = audio.split_mid_side(x)
    assert np.array_equal(mid + side, x)
    assert np.array_equal(mid[:, 0], mid[:, 1])         # mid is centred
    assert np.array_equal(side[:, 0], -side[:, 1])      # side is the out-of-phase part
    assert np.array_equal(mid[:, 0], (x[:, 0] + x[:, 1]) / 2)


def test_mono_material_has_no_side():
    x = np.repeat(np.linspace(-1, 1, 100)[:, None], 2, axis=1)
    mid, side = audio.split_mid_side(x)
    assert np.array_equal(mid, x) and not side.any()


# --- Reading ---


def audio_extensions() -> list[str]:
    """The extensions the file picker offers."""
    return re.findall(r"\*\.(\w+)", AUDIO_FILTER.split(";;")[0])


WRITE_FORMATS = {  # how to make a test file for each extension
    "aif": ("AIFF", "PCM_16", 44100),
    "aiff": ("AIFF", "PCM_24", 44100),
    "flac": ("FLAC", "PCM_16", 44100),
    "mp3": ("MP3", "MPEG_LAYER_III", 44100),
    "ogg": ("OGG", "VORBIS", 44100),
    "opus": ("OGG", "OPUS", 48000),
    "wav": ("WAV", "FLOAT", 44100),
}


def test_every_offered_format_has_a_read_test():
    assert sorted(audio_extensions()) == sorted(WRITE_FORMATS)


@pytest.mark.parametrize("extension", sorted(WRITE_FORMATS))
def test_every_offered_format_can_be_read(tmp_path, extension):
    file_format, subtype, rate = WRITE_FORMATS[extension]
    path = tmp_path / f"tone.{extension}"
    t = np.arange(rate) / rate
    tone = 0.5 * np.column_stack((np.sin(2 * np.pi * 440 * t), np.sin(2 * np.pi * 660 * t)))
    soundfile.write(path, tone, rate, format=file_format, subtype=subtype)

    assert audio.info(str(path)) == (rate, 2)
    data, read_rate, channels = audio.read(str(path))
    assert read_rate == rate and channels == 2 and data.dtype == np.float64 and data.shape[1] == 2
    assert 0.3 < np.max(np.abs(data)) < 0.7  # the tone, not silence or garbage


def test_mono_files_are_copied_to_both_channels(tmp_path):
    path = tmp_path / "mono.wav"
    soundfile.write(path, np.linspace(-0.5, 0.5, 100), 44100, subtype="FLOAT")
    data, _, channels = audio.read(str(path))
    assert channels == 1 and np.array_equal(data[:, 0], data[:, 1])


def test_rf64_wavs_can_be_read(tmp_path):
    path = tmp_path / "long.wav"  # RF64 files keep the .wav extension
    samples = np.random.default_rng(5).uniform(-1, 1, (1000, 2))
    soundfile.write(path, samples, 48000, format="RF64", subtype="FLOAT")
    assert audio.info(str(path)) == (48000, 2)
    data, rate, channels = audio.read(str(path))
    assert rate == 48000 and channels == 2
    assert np.array_equal(data, samples.astype(np.float32))


def test_more_than_two_channels_is_an_error(tmp_path):
    path = tmp_path / "surround.wav"
    soundfile.write(path, np.zeros((100, 6)), 44100)
    with pytest.raises(audio.AudioError, match=re.escape("too many channels: (has 6, expected 1 or 2)")):
        audio.read(str(path))


@pytest.mark.parametrize("extension", ["wav", "aiff", "ogg"])  # the formats libsndfile opens when empty
def test_files_with_no_samples_are_an_error(tmp_path, extension):
    file_format, subtype, rate = WRITE_FORMATS[extension]
    path = tmp_path / f"empty.{extension}"
    soundfile.write(path, np.zeros((0, 2)), rate, format=file_format, subtype=subtype)
    with pytest.raises(audio.AudioError, match="couldn't be read as audio"):
        audio.info(str(path))
    with pytest.raises(audio.AudioError, match="couldn't be read as audio"):
        audio.read(str(path))


def test_non_audio_files_are_an_error(tmp_path):
    path = tmp_path / "notes.wav"
    path.write_text("not audio")
    with pytest.raises(audio.AudioError):
        audio.info(str(path))
    with pytest.raises(audio.AudioError):
        audio.read(str(path))


# --- Writing ---


def chunks(data: bytes) -> list[tuple[bytes, bytes]]:
    assert data[:4] == b"RIFF" and data[8:12] == b"WAVE"
    assert struct.unpack("<I", data[4:8])[0] == len(data) - 8
    found, pos = [], 12
    while pos < len(data):
        chunk_id, size = data[pos:pos + 4], struct.unpack("<I", data[pos + 4:pos + 8])[0]
        found.append((chunk_id, data[pos + 8:pos + 8 + size]))
        pos += 8 + size + size % 2
    return found


def test_wav_is_32_bit_float_with_no_metadata(tmp_path):
    samples = np.random.default_rng(3).uniform(-2, 2, (1000, 2))
    path = tmp_path / "out.wav"
    audio.write_wav(str(path), samples)

    found = chunks(path.read_bytes())
    assert [c for c, _ in found] == [b"fmt ", b"fact", b"data"]
    fmt = struct.unpack("<HHIIHHH", found[0][1])
    assert fmt == (audio.WAVE_FORMAT_IEEE_FLOAT, 2, 44100, 44100 * 8, 8, 32, 0)
    assert struct.unpack("<I", found[1][1]) == (1000,)

    data, rate = soundfile.read(path, dtype="float32")
    assert rate == 44100
    assert np.array_equal(data, samples.astype(np.float32))  # rounded once, and nothing clipped


def rf64_chunks(data: bytes) -> list[tuple[bytes, bytes]]:
    """Chunks of an RF64 file, with the "data" chunk's real size taken from ds64."""
    assert data[:4] == b"RF64" and data[4:8] == b"\xff\xff\xff\xff" and data[8:12] == b"WAVE"
    found, pos, data_size = [], 12, None
    while pos < len(data):
        chunk_id, size = data[pos:pos + 4], struct.unpack("<I", data[pos + 4:pos + 8])[0]
        if chunk_id == b"data":
            assert size == 0xFFFFFFFF
            size = data_size
        found.append((chunk_id, data[pos + 8:pos + 8 + size]))
        if chunk_id == b"ds64":
            riff_size, data_size, frames, table = struct.unpack("<QQQI", found[-1][1])
            assert riff_size == len(data) - 8 and table == 0
        pos += 8 + size + size % 2
    return found


def test_wavs_too_big_for_32_bit_sizes_are_written_as_rf64(tmp_path, monkeypatch):
    samples = np.random.default_rng(4).uniform(-1, 1, (1000, 2))
    monkeypatch.setattr(audio, "MAX_WAV_DATA", 1000 * 8 - 1)  # as if 1000 frames were over 4 GB
    path = tmp_path / "big.wav"
    audio.write_wav(str(path), samples)

    found = rf64_chunks(path.read_bytes())
    assert [c for c, _ in found] == [b"ds64", b"fmt ", b"fact", b"data"]
    assert struct.unpack("<QQQI", found[0][1])[1:3] == (8000, 1000)
    assert struct.unpack("<HHIIHHH", found[1][1])[0] == audio.WAVE_FORMAT_IEEE_FLOAT
    assert struct.unpack("<I", found[2][1]) == (1000,)

    data, rate = soundfile.read(path, dtype="float32")
    assert rate == 44100 and soundfile.info(path).format == "RF64"
    assert np.array_equal(data, samples.astype(np.float32))


def test_wavs_that_fit_stay_plain_wav(tmp_path, monkeypatch):
    monkeypatch.setattr(audio, "MAX_WAV_DATA", 1000 * 8)  # exactly at the limit
    path = tmp_path / "out.wav"
    audio.write_wav(str(path), np.zeros((1000, 2)))
    assert path.read_bytes()[:4] == b"RIFF"


def test_peak_dbfs():
    assert audio.peak_dbfs(np.array([[0.5, -1.0]])) == 0
    assert audio.peak_dbfs(np.array([[2.0, 0.0]])) == pytest.approx(6.0206, abs=1e-4)
    assert audio.peak_dbfs(np.zeros((4, 2))) == -math.inf
