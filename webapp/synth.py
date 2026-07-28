#!/usr/bin/env python3
"""
Claude Voice Mode - document reader: one way to turn text into audio bytes.

Everywhere else in this project, speech is something that happens: the worker
picks an engine, plays a sound, and returns nothing. The reader needs the
opposite - audio as a file the browser can put in a player, seek inside, and
replay from cache without paying for it twice.

So this module exposes a single call:

    synthesize(text, engine, voice, cfg) -> (bytes, mimetype, extension)

covering all four engines the control panel offers:

  piper       Offline neural, on the CPU. Free, unlimited, no network.
  neural      Microsoft's online neural voices (Andrew, Ava and ~45 others).
  elevenlabs  The best quality, and the only one that costs money per character.
  windows     System.Speech. Robotic, but offline, unlimited and cannot fail.

Piper and neural are done in this process rather than by calling the speech
server on port 8771. That is deliberate: the server loads exactly one Piper model
chosen by voice-config.json, so proxying to it would silently collapse the
reader's model picker down to a single choice. Doing it here lets the reader use
any voice on disk, and keeps hooks/tts-server.py - an installed file - untouched.
If the imports are missing from this interpreter we fall back to the server, so a
half-installed machine still gets sound.

Standard library only, apart from the optional piper / edge_tts imports that the
engines themselves need.
"""
import json
import os
import subprocess
import tempfile
import threading
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
SAPI_SCRIPT = os.path.join(HERE, "sapi-to-wav.ps1")

EL_BASE = "https://api.elevenlabs.io"
DEFAULT_NEURAL_VOICE = "en-US-AndrewNeural"

ENGINES = ("piper", "neural", "elevenlabs", "windows")

MIME = {
    "piper": ("audio/wav", ".wav"),
    "neural": ("audio/mpeg", ".mp3"),
    "elevenlabs": ("audio/mpeg", ".mp3"),
    "windows": ("audio/wav", ".wav"),
}

# Seconds of synthesis per second of audio, measured on this machine rather than
# guessed. Used only to warn how long a long document will take to generate
# before you commit to it. Network engines will vary with the connection.
REALTIME_FACTOR = {
    "piper": 0.15,       # 20.6s to produce 138s of audio, offline
    "neural": 0.29,      # 62.1s to produce 213s of audio, online
    "elevenlabs": 0.15,  # fastest of the online engines on turbo, but billed
    "windows": 0.06,     # nothing to load, nothing to fetch
}

# Characters per second of speech, for turning a document length into a duration
# estimate. Close enough for a progress warning, not a promise.
CHARS_PER_SECOND = 15.0


class SynthError(Exception):
    """Engine could not produce audio. Carries a message fit to show a user."""


# --------------------------------------------------------------------------- #
# piper - offline, in this process
# --------------------------------------------------------------------------- #
_PIPER_CACHE = {}
_PIPER_LOCK = threading.Lock()


def _piper_voice(model_path):
    """Load a Piper model once and keep it. Loading costs ~0.75s; speaking a
    sentence costs ~0.2s, so caching is the difference between a reader that
    stutters between paragraphs and one that does not."""
    with _PIPER_LOCK:
        if model_path not in _PIPER_CACHE:
            from piper import PiperVoice

            _PIPER_CACHE[model_path] = PiperVoice.load(model_path)
        return _PIPER_CACHE[model_path]


def _piper(text, model_path):
    import io
    import wave

    if not model_path or not os.path.isfile(model_path):
        raise SynthError("No Piper voice model selected.")
    voice = _piper_voice(model_path)
    buf = io.BytesIO()
    # One model, one CPU job at a time - Piper is not reentrant.
    with _PIPER_LOCK:
        with wave.open(buf, "wb") as wf:
            voice.synthesize_wav(text, wf)
    return buf.getvalue()


# --------------------------------------------------------------------------- #
# neural - Microsoft's online voices, in this process
# --------------------------------------------------------------------------- #
def _neural(text, voice):
    import asyncio

    import edge_tts

    async def run():
        parts = []
        comm = edge_tts.Communicate(text, voice or DEFAULT_NEURAL_VOICE)
        async for part in comm.stream():
            if part["type"] == "audio":
                parts.append(part["data"])
        return b"".join(parts)

    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(run())
    finally:
        loop.close()


# --------------------------------------------------------------------------- #
# elevenlabs - the paid one
# --------------------------------------------------------------------------- #
def _elevenlabs(text, voice_id, cfg):
    api_key = (cfg or {}).get("apiKey") or ""
    if not api_key:
        raise SynthError("No ElevenLabs API key saved. Add one in the control panel.")
    if not voice_id:
        raise SynthError("No ElevenLabs voice selected.")

    body = json.dumps(
        {
            "text": text,
            "model_id": cfg.get("modelId") or "eleven_turbo_v2_5",
            "voice_settings": {
                "stability": float(cfg.get("stability", 0.5)),
                "similarity_boost": float(cfg.get("similarity", 0.75)),
            },
        }
    ).encode("utf-8")

    req = urllib.request.Request(
        EL_BASE + "/v1/text-to-speech/" + voice_id + "?output_format=mp3_44100_128",
        data=body,
        headers={
            "xi-api-key": api_key,
            "Content-Type": "application/json",
            "Accept": "audio/mpeg",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return resp.read()
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "ignore")[:300]
        raise SynthError("ElevenLabs returned HTTP %d: %s" % (e.code, detail))


# --------------------------------------------------------------------------- #
# windows - System.Speech, via a named helper script
# --------------------------------------------------------------------------- #
def _windows(text, voice_name):
    txt = tempfile.mktemp(prefix="reader-", suffix=".txt")
    wav = tempfile.mktemp(prefix="reader-", suffix=".wav")
    try:
        with open(txt, "w", encoding="utf-8") as f:
            f.write(text)
        cmd = [
            "powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
            "-File", SAPI_SCRIPT,
            "-TextFile", txt,
            "-OutFile", wav,
        ]
        if voice_name:
            cmd += ["-Voice", voice_name]
        proc = subprocess.run(
            cmd,
            capture_output=True,
            timeout=300,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if proc.returncode != 0 or not os.path.isfile(wav):
            err = (proc.stderr or b"").decode("utf-8", "ignore").strip()[:300]
            raise SynthError("Windows voice failed: " + (err or "no audio produced"))
        with open(wav, "rb") as f:
            return f.read()
    finally:
        for p in (txt, wav):
            try:
                os.remove(p)
            except OSError:
                pass


def windows_voices():
    """Installed System.Speech voices. Shelled out because Python has no way to
    enumerate SAPI without a COM binding we deliberately do not depend on."""
    ps = (
        "Add-Type -AssemblyName System.Speech; "
        "(New-Object System.Speech.Synthesis.SpeechSynthesizer).GetInstalledVoices() "
        "| Where-Object { $_.Enabled } "
        "| ForEach-Object { $_.VoiceInfo.Name } | ConvertTo-Json -Compress"
    )
    try:
        proc = subprocess.run(
            ["powershell.exe", "-NoProfile", "-Command", ps],
            capture_output=True,
            timeout=30,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        out = (proc.stdout or b"").decode("utf-8", "ignore").strip()
        names = json.loads(out) if out else []
        if isinstance(names, str):
            names = [names]
        return [{"name": n} for n in names]
    except Exception:  # noqa: BLE001 - an empty picker is better than a crash
        return []


# --------------------------------------------------------------------------- #
# fallback: the speech server the Stop hook uses
# --------------------------------------------------------------------------- #
def _via_server(text, engine, voice, cfg):
    """Used only when piper / edge_tts are not importable here but the hook's
    server is already running with them. Voice choice is whatever that server
    was started with."""
    port = int((cfg or {}).get("ttsPort") or 8771)
    payload = {"text": text, "engine": engine}
    if engine == "neural" and voice:
        payload["voice"] = voice
    req = urllib.request.Request(
        "http://127.0.0.1:%d/say" % port,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=180) as resp:
        return resp.read()


# --------------------------------------------------------------------------- #
# the one entry point
# --------------------------------------------------------------------------- #
def synthesize(text, engine, voice=None, cfg=None):
    """Text to audio bytes.

    Returns (audio_bytes, mimetype, file_extension). Raises SynthError with a
    message worth showing the user - the reader surfaces it in the page rather
    than silently falling back, because a document read in the wrong voice for
    forty minutes is worse than an error you can act on.
    """
    cfg = cfg or {}
    engine = (engine or "piper").lower()
    if engine not in ENGINES:
        raise SynthError("Unknown engine: %s" % engine)

    text = (text or "").strip()
    if not text:
        raise SynthError("Nothing to speak.")

    try:
        if engine == "piper":
            try:
                audio = _piper(text, voice)
            except ImportError:
                audio = _via_server(text, "piper", None, cfg)
        elif engine == "neural":
            try:
                audio = _neural(text, voice)
            except ImportError:
                audio = _via_server(text, "neural", voice, cfg)
        elif engine == "elevenlabs":
            audio = _elevenlabs(text, voice, cfg)
        else:
            audio = _windows(text, voice)
    except SynthError:
        raise
    except Exception as e:  # noqa: BLE001
        raise SynthError("%s: %s" % (engine, e))

    if not audio or len(audio) < 400:
        raise SynthError("%s produced no audio." % engine)

    mime, ext = MIME[engine]
    return audio, mime, ext


def estimate(chars, engine):
    """How long this document is to listen to, and to generate. Shown before you
    press play so a sixty-page document on a slow engine is a choice."""
    audio_seconds = chars / CHARS_PER_SECOND
    return {
        "audioSeconds": int(audio_seconds),
        "generateSeconds": int(audio_seconds * REALTIME_FACTOR.get(engine, 0.3)),
        "chars": chars,
    }
