#!/usr/bin/env python3
"""
Claude Voice Mode — local speech server for the two natural voice engines.

Why this exists: speak-worker.ps1 is launched fresh for every reply, so anything
it does per reply is paid for on every reply. Loading a Piper voice model costs
about three quarters of a second while synthesizing a sentence costs about two
tenths, and spinning up Python costs about half a second. Paying those once per
session instead of once per reply is the whole difference between speech that
feels instant and speech that feels laggy. This process stays warm and answers
over loopback HTTP.

It serves two engines:

  piper   — Neural voice running fully offline on the CPU. Free forever, works
            with no internet, and is safe to ship in a commercial product. This
            is also the engine you would later fine-tune on your own recorded
            voice, at which point it just starts sounding like you.

  neural  — Microsoft's online neural voices, the same Andrew and Ava you
            installed for Narrator. The copies Windows downloads for Narrator
            ship model data but no speech engine and register no COM class, so
            no third-party app can drive them. These are the same voices reached
            through Microsoft's public read-aloud service instead, which needs
            no API key. It does need internet, and it is an undocumented
            endpoint, so treat it as a convenience rather than a foundation.

Started automatically by speak-worker.ps1 on first use; you should never need to
run it by hand. It exits on its own after an idle period rather than sitting
resident forever.

Endpoints (bound to 127.0.0.1 only):
  GET  /health -> {"ok": true, "piper": "<model or null>", "neural": true/false}
  POST /say    <- {"text": "...", "engine": "piper"|"neural", "voice": "..."}
                  -> audio/wav for piper, audio/mpeg for neural
"""
import asyncio
import io
import json
import os
import sys
import threading
import time
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HOOKS_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(HOOKS_DIR, "voice-config.json")

DEFAULT_PORT = 8771
DEFAULT_IDLE_TIMEOUT = 1800  # seconds without a request before we exit
DEFAULT_NEURAL_VOICE = "en-US-AndrewNeural"

# Longest text we synthesize in one call. Spoken replies are short; this only
# stops a runaway paste from pinning the CPU for minutes.
MAX_CHARS = 8000

LAST_USED = time.time()


def load_config():
    # utf-8-sig, not utf-8: every stock Windows tool that touches this file
    # (Set-Content, Notepad) writes a byte order mark, and plain utf-8 would
    # then fail to parse and silently leave us with no config at all.
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8-sig") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def resolve_model(cfg):
    """Path to the .onnx Piper voice, or None.

    Prefers whatever the control panel saved, then falls back to any model
    sitting in the piper folder, so a hand-dropped voice works without anyone
    having to edit config first.
    """
    explicit = (cfg.get("piperModel") or "").strip()
    if explicit and os.path.isfile(explicit):
        return explicit

    voices_dir = cfg.get("piperDir") or os.path.join(HOOKS_DIR, "piper")
    if os.path.isdir(voices_dir):
        found = sorted(f for f in os.listdir(voices_dir) if f.endswith(".onnx"))
        if found:
            return os.path.join(voices_dir, found[0])
    return None


class PiperSpeaker:
    """Owns the loaded Piper voice. One model, one CPU job at a time."""

    def __init__(self, model_path):
        from piper import PiperVoice  # imported late so a failed import is catchable

        self.model_path = model_path
        self.name = os.path.splitext(os.path.basename(model_path))[0]
        self.voice = PiperVoice.load(model_path)
        self._lock = threading.Lock()

    def synthesize(self, text):
        buf = io.BytesIO()
        with self._lock:
            with wave.open(buf, "wb") as wf:
                self.voice.synthesize_wav(text, wf)
        return buf.getvalue()


class NeuralSpeaker:
    """Microsoft's online neural voices, via the free read-aloud service.

    edge_tts is async and we are inside a threaded blocking server, so each call
    gets its own event loop. That is cheap next to the network round trip.
    """

    def __init__(self, default_voice):
        import edge_tts  # noqa: F401 — presence check only

        self.default_voice = default_voice

    def synthesize(self, text, voice=None):
        import edge_tts

        async def run():
            chunks = []
            comm = edge_tts.Communicate(text, voice or self.default_voice)
            async for part in comm.stream():
                if part["type"] == "audio":
                    chunks.append(part["data"])
            return b"".join(chunks)

        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(run())
        finally:
            loop.close()


PIPER = None
NEURAL = None


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass  # stay quiet; this runs hidden

    def _send(self, code, body, ctype="application/json"):
        if not isinstance(body, bytes):
            body = json.dumps(body).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/health":
            return self._send(
                200,
                {
                    "ok": True,
                    "piper": PIPER.name if PIPER else None,
                    "neural": NEURAL is not None,
                },
            )
        return self._send(404, {"error": "not_found"})

    def do_POST(self):
        global LAST_USED
        if self.path != "/say":
            return self._send(404, {"error": "not_found"})

        n = int(self.headers.get("Content-Length", 0) or 0)
        try:
            data = json.loads(self.rfile.read(n).decode("utf-8")) if n else {}
        except (json.JSONDecodeError, UnicodeDecodeError):
            return self._send(400, {"error": "bad_json"})

        text = (data.get("text") or "").strip()
        if not text:
            return self._send(400, {"error": "empty_text"})
        text = text[:MAX_CHARS]
        LAST_USED = time.time()

        engine = (data.get("engine") or "piper").lower()
        try:
            if engine == "neural":
                if not NEURAL:
                    return self._send(503, {"error": "neural_unavailable"})
                audio = NEURAL.synthesize(text, data.get("voice"))
                ctype = "audio/mpeg"
            else:
                if not PIPER:
                    return self._send(503, {"error": "piper_unavailable"})
                audio = PIPER.synthesize(text)
                ctype = "audio/wav"
        except Exception as e:  # noqa: BLE001 — worker falls back to the Windows voice
            return self._send(500, {"error": str(e)})

        LAST_USED = time.time()
        if not audio:
            return self._send(500, {"error": "empty_audio"})
        return self._send(200, audio, ctype)


def idle_watchdog(srv, timeout):
    """Exit once nothing has asked us to speak for `timeout` seconds."""
    while True:
        time.sleep(30)
        if time.time() - LAST_USED > timeout:
            srv.shutdown()
            return


def main():
    global PIPER, NEURAL
    cfg = load_config()

    model = resolve_model(cfg)
    if model:
        try:
            PIPER = PiperSpeaker(model)
        except Exception as e:  # noqa: BLE001
            print(f"Piper unavailable ({e})", file=sys.stderr)

    try:
        NEURAL = NeuralSpeaker(cfg.get("neuralVoice") or DEFAULT_NEURAL_VOICE)
    except Exception as e:  # noqa: BLE001
        print(f"Neural voices unavailable ({e})", file=sys.stderr)

    if not PIPER and not NEURAL:
        print("No usable engine. Run install-voices.ps1 first.", file=sys.stderr)
        return 2

    port = int(os.environ.get("TTS_PORT") or cfg.get("ttsPort") or DEFAULT_PORT)
    idle = int(cfg.get("ttsIdleTimeout") or DEFAULT_IDLE_TIMEOUT)

    try:
        srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    except OSError:
        # Someone beat us to the port — almost certainly another copy of this
        # server, which is exactly what the caller wanted anyway.
        print(f"Port {port} already in use; assuming a server is already up.")
        return 0

    threading.Thread(target=idle_watchdog, args=(srv, idle), daemon=True).start()
    print(
        f"TTS server ready on 127.0.0.1:{port} "
        f"(piper={PIPER.name if PIPER else 'off'}, neural={'on' if NEURAL else 'off'})"
    )
    srv.serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
