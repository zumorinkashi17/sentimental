"""
pydub setup and helpers for turning the browser's isolated WebM tracks
(caller-only / responder-only) into speech-to-text friendly audio.

The browser hands us raw WebM/Opus chunks produced by MediaRecorder. Those are
stripped-down containers that speech-to-text models handle inconsistently, and
their container often carries no duration metadata at all. We therefore use
pydub to decode each track and re-encode it as 16 kHz mono 16-bit PCM WAV,
which is the format every STT backend expects and which decodes deterministically
so the timestamps the model reports line up with the call timeline.

A note on binaries: pydub shells out to ffmpeg (to decode) and ffprobe (to read
container metadata). We ship the ffmpeg binary through the imageio-ffmpeg wheel
so nothing has to be installed by hand, and we avoid needing ffprobe at all by
passing an explicit decoder to pydub, which makes it skip the metadata probe.
"""

import io
import logging
import warnings
from typing import NamedTuple, Optional

logger = logging.getLogger(__name__)

# pydub probes for ffmpeg at import time and warns when it is not on PATH. We
# supply the binary ourselves immediately afterwards, so the import happens with
# that one probe warning silenced.
with warnings.catch_warnings():
    warnings.simplefilter("ignore", RuntimeWarning)
    from pydub import AudioSegment
    from pydub.audio_segment import CouldntDecodeError

# pydub shells out to ffmpeg. Rather than require every developer and every
# deployment to install it separately, we use the ffmpeg binary that ships with
# the imageio-ffmpeg wheel and point pydub at it.
_CONVERTER_CONFIGURED = False


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


# 16 kHz mono 16-bit PCM is the common denominator for speech-to-text APIs.
STT_SAMPLE_RATE = 16000
STT_CHANNELS = 1
STT_SAMPLE_WIDTH = 2

MIME_WAV = "audio/wav"

# Decoders to try per container, best first. MediaRecorder emits Opus almost
# everywhere, but Safari-style MP4/AAC uploads show up too.
_CODEC_CANDIDATES = {
    "webm": ("opus", "vorbis"),
    "ogg": ("opus", "vorbis"),
    "oga": ("opus", "vorbis"),
    "opus": ("opus",),
    "mp4": ("aac",),
    "m4a": ("aac",),
    "mp3": ("mp3",),
    "wav": (),  # pydub reads PCM WAV natively, no converter involved
}

SUPPORTED_FORMATS = tuple(_CODEC_CANDIDATES)

# --- Speech level targets -------------------------------------------------
# Roughly -20 dBFS RMS: comfortably above the noise floor of most office gear
# while leaving plenty of headroom, which is where speech-to-text models are
# happiest.
TARGET_SPEECH_DBFS = -20.0
# Never let a boost push the loudest sample into clipping.
PEAK_CEILING_DBFS = -1.5
# Anything quieter than this is treated as silence/room tone, not speech, and is
# deliberately left alone. Boosting it would only amplify hiss.
NOISE_FLOOR_DBFS = -55.0
# Bounds so a pathological track cannot be swung to an absurd level.
MAX_BOOST_DB = 30.0
MAX_CUT_DB = -20.0


class NormalizedTrack(NamedTuple):
    """A decoded, leveled track plus the measurements taken along the way."""

    wav: bytes
    duration_ms: int
    input_dbfs: Optional[float] = None
    input_peak_dbfs: Optional[float] = None
    output_dbfs: Optional[float] = None
    output_peak_dbfs: Optional[float] = None
    gain_db: float = 0.0

    def as_levels(self):
        return {
            "input_dbfs": self.input_dbfs,
            "input_peak_dbfs": self.input_peak_dbfs,
            "output_dbfs": self.output_dbfs,
            "output_peak_dbfs": self.output_peak_dbfs,
            "gain_db": self.gain_db,
        }


class AudioProcessingError(Exception):
    """Raised when a track cannot be decoded or re-encoded."""


def _decode(audio_bytes, source_format, codec):
    """
    Decode raw track bytes into an AudioSegment.

    Passing an explicit ``codec`` makes pydub skip the ffprobe metadata call,
    so the bundled ffmpeg is the only external binary we depend on.
    """
    kwargs = {"format": source_format}
    if codec:
        kwargs["codec"] = codec
    return AudioSegment.from_file(io.BytesIO(audio_bytes), **kwargs)


def _to_stt_format(segment):
    """Force a segment into the layout every STT backend expects."""
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


def normalize_speech_level(
    segment,
    target_dbfs=TARGET_SPEECH_DBFS,
    max_boost_db=MAX_BOOST_DB,
    max_cut_db=MAX_CUT_DB,
):
    """
    Bring a track up to a consistent speech loudness.

    The two sides of a call arrive at wildly different levels: a USB dongle
    carrying a phone line is hot, while a desk mic that the browser's echo
    canceller has already attenuated can be 30-40 dB down. Relying on the
    hand-tuned gain values in the browser graph to fix that is fragile, because
    it depends entirely on which microphone happens to be plugged in. Measuring
    the track and correcting it here means the AI hears both sides equally well
    regardless of hardware.

    RMS is used rather than peak, since peak normalisation would just track
    whatever transient happens to be loudest. Two guards keep this from making
    things worse: a noise floor (so near-silence is not amplified into a wall
    of hiss) and a peak ceiling (so boosting cannot introduce clipping).

    Returns ``(segment, gain_db)``; ``gain_db`` is 0.0 when no change was made.
    """
    if len(segment) == 0:
        return segment, 0.0

    measured = segment.dBFS
    if measured == float("-inf") or measured <= NOISE_FLOOR_DBFS:
        # Silence or noise only. Boosting this would just amplify hiss.
        logger.info("Skipping normalization: track is at the noise floor (%.1f dBFS)", measured)
        return segment, 0.0

    gain = max(max_cut_db, min(max_boost_db, target_dbfs - measured))
    if abs(gain) < 0.5:
        return segment, 0.0

    leveled = segment.apply_gain(gain)

    # Boosting can push peaks past full scale; pull the whole track back just
    # enough to keep the loudest sample below clipping.
    peak = leveled.max_dBFS
    if peak != float("-inf") and peak > PEAK_CEILING_DBFS:
        leveled = leveled.apply_gain(PEAK_CEILING_DBFS - peak)
        gain += PEAK_CEILING_DBFS - peak

    logger.info("Normalized track: %.1f -> %.1f dBFS (%+.1f dB)", measured, leveled.dBFS, gain)
    return leveled, gain


def _measure(segment):
    """Return (rms_dbfs, peak_dbfs) for a segment, or (None, None) if silent."""
    if len(segment) == 0:
        return None, None
    rms = segment.dBFS
    peak = segment.max_dBFS
    if rms == float("-inf"):
        return None, None
    return round(rms, 1), round(peak, 1)


def to_stt_wav(audio_bytes, source_format="webm", codec=None, normalize=True):
    """
    Decode raw track bytes, level them, and re-encode as 16 kHz mono 16-bit WAV.

    Returns a :class:`NormalizedTrack`. ``duration_ms`` is measured from the
    decoded audio rather than the container, because MediaRecorder output
    frequently reports a zero or absent duration.

    ``codec`` should be the audio codec the browser reported for the track; when
    omitted the usual decoders for the container are tried in turn.

    ``normalize`` applies speech-level correction. Pass False to inspect a track
    at its original level.
    """
    if not audio_bytes:
        raise AudioProcessingError("Track is empty.")

    configure_converter()
    source_format = (source_format or "webm").lower().lstrip(".")

    if codec:
        candidates = (codec,)
    else:
        candidates = _CODEC_CANDIDATES.get(source_format, ("opus", "vorbis"))

    # A None entry means "let pydub auto-detect", which needs ffprobe, so it is
    # only used when the container is one pydub can read on its own.
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

        # Convert first, then level: the dBFS math and the noise/peak guards
        # should run against exactly the samples that get sent to the AI.
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
