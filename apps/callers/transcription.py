"""
Speech-to-text for the isolated caller / responder tracks.

Each track is transcribed on its own so the model only ever has to identify one
speaker, and we ask for structured output (start second, end second, text)
rather than prose. The two segment lists are then merged and ordered by start
time to rebuild the original conversation.
"""

import base64
import json
import logging
from concurrent.futures import ThreadPoolExecutor

import requests
from django.conf import settings

from .audio import MIME_WAV, SUPPORTED_FORMATS, AudioProcessingError, to_stt_wav

logger = logging.getLogger(__name__)

GEMINI_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
REQUEST_TIMEOUT = 300

CALLER = "Caller"
RESPONDER = "Responder"
TRANSCRIPT_HEADER = "------- Sentimental Conversation Transcript ------"

# Forces the model to answer with a JSON array of utterance objects instead of
# prose, which is what makes the timestamps usable.
RESPONSE_SCHEMA = {
    "type": "ARRAY",
    "items": {
        "type": "OBJECT",
        "properties": {
            "start": {
                "type": "NUMBER",
                "description": "Second in the recording where the utterance begins.",
            },
            "end": {
                "type": "NUMBER",
                "description": "Second in the recording where the utterance finishes.",
            },
            "text": {
                "type": "STRING",
                "description": "Verbatim words spoken, in the original language.",
            },
        },
        "required": ["start", "end", "text"],
    },
}


class TranscriptionError(Exception):
    """Raised when a track could not be transcribed."""


def get_model_name():
    return getattr(settings, "GEMINI_TRANSCRIBE_MODEL", "gemini-3.5-flash-lite")


def build_prompt(speaker):
    return (
        f"Transcribe the speech in this audio clip. The clip contains only the "
        f"{speaker} of a phone call, so every utterance belongs to the same "
        f"speaker. The language is a mix of Cebuano (Bisaya) and English.\n\n"
        f"Rules:\n"
        f"- Break the audio into individual utterances, one object per utterance.\n"
        f"- 'start' and 'end' are the precise second offsets in this clip where "
        f"each utterance begins and ends. Never leave them as 0; they must "
        f"increase across the clip and stay within its duration.\n"
        f"- 'text' must be a verbatim transcription. Never translate, summarise, "
        f"correct, or add words that were not spoken.\n"
        f"- If the clip contains no speech at all, return an empty array []."
    )


def _parse_segments(raw_text, speaker):
    """Coerce the model's JSON reply into a clean, sorted list of segments."""
    if raw_text is None:
        return []

    text = raw_text.strip()
    if not text:
        return []

    # Some responses arrive wrapped in a markdown fence despite the schema.
    if text.startswith("```"):
        text = text.split("\n", 1)[-1]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()

    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise TranscriptionError(
            f"{speaker} track returned malformed JSON: {exc}"
        ) from exc

    # The schema asks for an array, but a bare object still means one utterance.
    if isinstance(data, dict):
        data = [data]
    if not isinstance(data, list):
        raise TranscriptionError(
            f"{speaker} track returned {type(data).__name__}, expected a list of segments."
        )

    segments = []
    for item in data:
        if not isinstance(item, dict):
            continue
        spoken = str(item.get("text") or "").strip()
        if not spoken:
            continue
        try:
            start = float(item.get("start", 0) or 0)
        except (TypeError, ValueError):
            start = 0.0
        try:
            end = float(item.get("end", 0) or 0)
        except (TypeError, ValueError):
            end = start
        if end < start:
            end = start
        segments.append({"speaker": speaker, "start": start, "end": end, "text": spoken})

    segments.sort(key=lambda seg: seg["start"])
    return segments


def transcribe_track(wav_bytes, speaker, api_key):
    """Send one normalized WAV track to Gemini and return its segments."""
    if not api_key:
        raise TranscriptionError(
            "Gemini API key is not configured. Add GEMINI_API_KEY=AIza... to your .env file."
        )
    if not wav_bytes:
        raise TranscriptionError(f"No audio received for the {speaker.lower()} track.")

    payload = {
        "contents": [
            {
                "parts": [
                    {"text": build_prompt(speaker)},
                    {
                        "inlineData": {
                            "mimeType": MIME_WAV,
                            "data": base64.b64encode(wav_bytes).decode("ascii"),
                        }
                    },
                ]
            }
        ],
        "generationConfig": {
            "responseMimeType": "application/json",
            "responseSchema": RESPONSE_SCHEMA,
            "temperature": 0,
        },
    }

    url = GEMINI_ENDPOINT.format(model=get_model_name())
    try:
        response = requests.post(
            url,
            params={"key": api_key},
            json=payload,
            timeout=REQUEST_TIMEOUT,
        )
    except requests.RequestException as exc:
        raise TranscriptionError(
            f"Could not reach the transcription service for the {speaker.lower()} track: {exc}"
        ) from exc

    if not response.ok:
        detail = ""
        try:
            detail = response.json().get("error", {}).get("message", "")
        except ValueError:
            detail = response.text[:300]
        raise TranscriptionError(
            f"{speaker} track failed ({response.status_code}): {detail or 'no details returned'}"
        )

    try:
        body = response.json()
        raw_text = body["candidates"][0]["content"]["parts"][0]["text"]
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        raise TranscriptionError(
            f"Unexpected response shape from the transcription service: {exc}"
        ) from exc

    return _parse_segments(raw_text, speaker)


def merge_segments(caller_segments, responder_segments):
    """Interleave both sides into one conversation ordered by start time."""
    return sorted(
        list(caller_segments) + list(responder_segments),
        key=lambda seg: (seg["start"], seg["end"]),
    )


def render_transcript(segments):
    """
    Build the plain-text conversation shown to the responder.

    Example:
        ------- Sentimental Conversation Transcript ------
        [Caller] Hi, I need help.
        [Responder] Sure, SentiMental is here for you.
    """
    if not segments:
        return f"{TRANSCRIPT_HEADER}\n(no speech detected)"

    lines = [TRANSCRIPT_HEADER]
    for seg in segments:
        lines.append(f"[{seg['speaker']}] {seg['text']}")
    return "\n".join(lines)


def transcribe_tracks(caller_wav, responder_wav, api_key):
    """
    Transcribe both tracks concurrently, then return the merged conversation.

    Raises TranscriptionError if either track fails, so a partial conversation
    is never presented as if it were the whole call.
    """
    with ThreadPoolExecutor(max_workers=2) as pool:
        caller_future = pool.submit(transcribe_track, caller_wav, CALLER, api_key)
        responder_future = pool.submit(
            transcribe_track, responder_wav, RESPONDER, api_key
        )
        caller_segments = caller_future.result()
        responder_segments = responder_future.result()

    segments = merge_segments(caller_segments, responder_segments)
    return segments, render_transcript(segments)


def normalize_track(uploaded_file, label, codec=None, normalize=True):
    """
    Read an uploaded track and return a :class:`NormalizedTrack`.

    ``codec`` is the audio codec the browser reported for the blob. Passing it
    through lets pydub decode without shelling out to ffprobe.
    """
    uploaded_file.seek(0)
    raw = uploaded_file.read()
    source_format = (getattr(uploaded_file, "name", "") or "").rsplit(".", 1)[-1].lower()
    if source_format not in SUPPORTED_FORMATS:
        source_format = "webm"
    try:
        return to_stt_wav(
            raw, source_format=source_format, codec=codec, normalize=normalize
        )
    except AudioProcessingError:
        logger.warning("Failed to normalize %s track", label)
        raise
