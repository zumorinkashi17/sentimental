"""
Converts caller and responder WebM audio tracks into 16 kHz mono WAV files
for speech-to-text processing. Uses imageio-ffmpeg for decoding and an
explicit decoder to avoid requiring ffprobe.
"""

import io
import logging
import warnings
from typing import NamedTuple, Optional

logger = logging.getLogger(__name__)

# Checks for ffmpeg and warns if it is missing from PATH.
with warnings.catch_warnings():
    warnings.simplefilter("ignore", RuntimeWarning)
    from pydub import AudioSegment
    from pydub.audio_segment import CouldntDecodeError

_CONVERTER_CONFIGURED = False


# Sets pydub to use the bundled ffmpeg, or falls back to PATH.
def configure_converter():
    """Point pydub at an ffmpeg binary, preferring the pip-bundled one."""
    global _CONVERTER_CONFIGURED
    if _CONVERTER_CONFIGURED:
        return AudioSegment.converter

    try:
        import imageio_ffmpeg

        AudioSegment.converter = imageio_ffmpeg.get_ffmpeg_exe()
        logger.info("pydub using bundled ffmpeg: %s", AudioSegment.converter)
    except Exception as exc:  # pragma: no cover - depends on local install
        # Fall back to whatever ffmpeg/avconv is on PATH, which pydub probes for.
        logger.warning(
            "imageio-ffmpeg unavailable (%s); falling back to system ffmpeg", exc
        )
        AudioSegment.converter = "ffmpeg"

    _CONVERTER_CONFIGURED = True
    return AudioSegment.converter


configure_converter()


# 16 kHz mono 16-bit PCM Standard audio format for speech-to-text APIs.
STT_SAMPLE_RATE = 16000
STT_CHANNELS = 1
STT_SAMPLE_WIDTH = 2

MIME_WAV = "audio/wav"

# Supported audio formats to try.
_CODEC_CANDIDATES = {
    "webm": ("opus", "vorbis"),
    "ogg": ("opus", "vorbis"),
    "oga": ("opus", "vorbis"),
    "opus": ("opus",),
    "mp4": ("aac",),
    "m4a": ("aac",),
    "mp3": ("mp3",),
    "wav": (),  # WAV files can be read directly without a converter.
}

SUPPORTED_FORMATS = tuple(_CODEC_CANDIDATES)

# Speech level targets
TARGET_SPEECH_DBFS = -20.0
PEAK_CEILING_DBFS = -1.5
NOISE_FLOOR_DBFS = -55.0
MAX_BOOST_DB = 30.0
MAX_CUT_DB = -20.0


class NormalizedTrack(NamedTuple):
    """Stores the processed audio track and its measurements."""

    wav: bytes
    duration_ms: int
    input_dbfs: Optional[float] = None
    input_peak_dbfs: Optional[float] = None
    output_dbfs: Optional[float] = None
    output_peak_dbfs: Optional[float] = None
    gain_db: float = 0.0

    # Saves track measurements for the call_setup's Track Levels panel.
    def as_levels(self):
        return {
            "input_dbfs": self.input_dbfs,
            "input_peak_dbfs": self.input_peak_dbfs,
            "output_dbfs": self.output_dbfs,
            "output_peak_dbfs": self.output_peak_dbfs,
            "gain_db": self.gain_db,
        }


class AudioProcessingError(Exception):
    """Raised when audio decoding or conversion fails."""


# Decodes WebM/Opus using ffmpeg without requiring ffprobe.
def _decode(audio_bytes, source_format, codec):
    """Decodes audio bytes into an AudioSegment using ffmpeg only."""

    kwargs = {"format": source_format}
    if codec:
        kwargs["codec"] = codec
    return AudioSegment.from_file(io.BytesIO(audio_bytes), **kwargs)


# Converts audio to 16 kHz mono 16-bit PCM WAV. The format every STT backend expects.
def _to_stt_format(segment):
    """Converts audio to the standard format for speech-to-text."""
    segment = segment.set_frame_rate(STT_SAMPLE_RATE)
    segment = segment.set_channels(STT_CHANNELS)
    segment = segment.set_sample_width(STT_SAMPLE_WIDTH)

    buffer = io.BytesIO()
    try:
        segment.export(buffer, format="wav")
    except Exception as exc:
        raise AudioProcessingError(
            f"Could not encode the track as WAV: {exc}"
        ) from exc

    return buffer.getvalue()


# Adjusts audio volume while preventing silence and clipping and Returns the adjusted audio and applied gain in dB.
def normalize_speech_level(
    segment,
    target_dbfs=TARGET_SPEECH_DBFS,
    max_boost_db=MAX_BOOST_DB,
    max_cut_db=MAX_CUT_DB,
):
    """
    Adjusts audio volume to a consistent speech level while avoiding noise
    amplification and clipping. Returns the adjusted audio and gain in dB.
    """

    if len(segment) == 0:
        return segment, 0.0

    measured = segment.dBFS
    if measured == float("-inf") or measured <= NOISE_FLOOR_DBFS:
        # Skips silent or very quiet audio to avoid amplifying noise.
        logger.info("Skipping normalization: track is at the noise floor (%.1f dBFS)", measured)
        return segment, 0.0

    gain = max(max_cut_db, min(max_boost_db, target_dbfs - measured))
    if abs(gain) < 0.5:
        return segment, 0.0

    leveled = segment.apply_gain(gain)

    # Skips near-silent audio to avoid amplifying background noise. Reduces volume if boosting would cause clipping.
    peak = leveled.max_dBFS
    if peak != float("-inf") and peak > PEAK_CEILING_DBFS:
        leveled = leveled.apply_gain(PEAK_CEILING_DBFS - peak)
        gain += PEAK_CEILING_DBFS - peak

    logger.info("Normalized track: %.1f -> %.1f dBFS (%+.1f dB)", measured, leveled.dBFS, gain)
    return leveled, gain


# Measures audio volume and peak levels, returning None for silence.
def _measure(segment):
    """Return (rms_dbfs, peak_dbfs) for a segment, or (None, None) if silent."""
    if len(segment) == 0:
        return None, None
    rms = segment.dBFS
    peak = segment.max_dBFS
    if rms == float("-inf"):
        return None, None
    return round(rms, 1), round(peak, 1)


# MAIN-PYDUB: Decodes, converts, adjusts volume, and exports audio as WAV.
def to_stt_wav(audio_bytes, source_format="webm", codec=None, normalize=True):
    """Converts a track to normalized 16 kHz mono WAV for speech-to-text."""
    if not audio_bytes:
        raise AudioProcessingError("Track is empty.")

    configure_converter()
    source_format = (source_format or "webm").lower().lstrip(".")

    if codec:
        candidates = (codec,)
    else:
        candidates = _CODEC_CANDIDATES.get(source_format, ("opus", "vorbis"))

    # None lets pydub auto-detect the format, which requires ffprobe.
    attempts = list(candidates)
    if not attempts:
        attempts = [None]

    errors = []
    for candidate in attempts:
        try:
            segment = _decode(audio_bytes, source_format, candidate)
        except CouldntDecodeError as exc:
            errors.append(f"{candidate or 'auto'}: {exc}")
            continue
        except Exception as exc:
            errors.append(f"{candidate or 'auto'}: {exc}")
            continue

        if len(segment) == 0:
            errors.append(f"{candidate or 'auto'}: decoded to zero audio")
            continue

        # Convert first so volume adjustments match the audio sent to the AI.
        segment = segment.set_frame_rate(STT_SAMPLE_RATE)
        segment = segment.set_channels(STT_CHANNELS)
        segment = segment.set_sample_width(STT_SAMPLE_WIDTH)

        duration_ms = len(segment)
        input_dbfs, input_peak = _measure(segment)

        if normalize:
            segment, gain_db = normalize_speech_level(segment)
        else:
            gain_db = 0.0

        output_dbfs, output_peak = _measure(segment)

        buffer = io.BytesIO()
        try:
            segment.export(buffer, format="wav")
        except Exception as exc:
            raise AudioProcessingError(
                f"Could not encode the track as WAV: {exc}"
            ) from exc

        return NormalizedTrack(
            wav=buffer.getvalue(),
            duration_ms=duration_ms,
            input_dbfs=input_dbfs,
            input_peak_dbfs=input_peak,
            output_dbfs=output_dbfs,
            output_peak_dbfs=output_peak,
            gain_db=round(gain_db, 1),
        )

    raise AudioProcessingError(
        f"Could not decode the {source_format} track. " + " | ".join(errors)
    )


# Audio duration in milliseconds; uses decoded audio, or 0 if unknown.
def get_duration_ms(audio_bytes, source_format="webm", codec=None):
    """Return the decoded length of a track in milliseconds, or 0 if unknown."""
    if not audio_bytes:
        return 0

    try:
        return to_stt_wav(
            audio_bytes, source_format=source_format, codec=codec, normalize=False
        ).duration_ms
    except AudioProcessingError as exc:
        logger.warning("Duration probe failed for %s track: %s", source_format, exc)
        return 0
