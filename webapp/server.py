#!/usr/bin/env python3
"""
Claude Voice Mode — control panel server.

A tiny, dependency-free (stdlib only) local web server that lets you:
  * turn spoken replies on/off,
  * switch between the free Windows voice and the premium ElevenLabs voice,
  * pick which ElevenLabs voice reads your content (by voice ID),
  * see your ElevenLabs plan + remaining credits,
  * preview any voice out loud before you commit.

Nothing leaves your machine except calls to the ElevenLabs API using your own
key. The key is stored locally in ~/.claude/hooks/voice-config.json (outside
this git repo), never committed.

Run:  python webapp/server.py   (or use start-webapp.ps1)
"""
import json
import os
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
HOOKS_DIR = os.path.join(os.path.expanduser("~"), ".claude", "hooks")
CONFIG_PATH = os.path.join(HOOKS_DIR, "voice-config.json")
FLAG_PATH = os.path.join(tempfile.gettempdir(), "claude-voice-enabled")
WORKER = os.path.join(HOOKS_DIR, "speak-worker.ps1")

EL_BASE = "https://api.elevenlabs.io"

DEFAULT_CONFIG = {
    "premium": False,
    "apiKey": "",
    "voiceId": "",
    "voiceName": "",
    "modelId": "eleven_turbo_v2_5",
    "stability": 0.5,
    "similarity": 0.75,
    "windowsVoice": "Zira",
}


# --------------------------------------------------------------------------- #
# config helpers
# --------------------------------------------------------------------------- #
def load_config():
    cfg = dict(DEFAULT_CONFIG)
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            cfg.update(json.load(f))
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    return cfg


def save_config(cfg):
    os.makedirs(HOOKS_DIR, exist_ok=True)
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)


def voice_enabled():
    return os.path.exists(FLAG_PATH)


def set_voice_enabled(on):
    if on:
        open(FLAG_PATH, "a").close()
    else:
        try:
            os.remove(FLAG_PATH)
        except FileNotFoundError:
            pass


# --------------------------------------------------------------------------- #
# ElevenLabs API (stdlib urllib)
# --------------------------------------------------------------------------- #
def el_get(path, api_key):
    req = urllib.request.Request(EL_BASE + path, headers={"xi-api-key": api_key})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def el_voices(api_key):
    data = el_get("/v1/voices", api_key)
    out = []
    for v in data.get("voices", []):
        labels = v.get("labels") or {}
        out.append(
            {
                "voice_id": v.get("voice_id"),
                "name": v.get("name"),
                "category": v.get("category"),
                "description": v.get("description") or "",
                "preview_url": v.get("preview_url") or "",
                "labels": labels,
            }
        )
    return out


def el_subscription(api_key):
    s = el_get("/v1/user/subscription", api_key)
    used = s.get("character_count", 0)
    limit = s.get("character_limit", 0)
    return {
        "tier": s.get("tier", "unknown"),
        "used": used,
        "limit": limit,
        "remaining": max(0, limit - used),
        "next_reset_unix": s.get("next_character_count_reset_unix"),
        "currency": s.get("currency"),
    }


# --------------------------------------------------------------------------- #
# speak a preview through the real pipeline (respects current config)
# --------------------------------------------------------------------------- #
def speak_preview(text):
    """Write text to a temp file and launch the same worker the hook uses."""
    fd, path = tempfile.mkstemp(prefix="claude-voice-", suffix=".txt")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)
    subprocess.Popen(
        [
            "powershell.exe",
            "-NoProfile",
            "-WindowStyle",
            "Hidden",
            "-File",
            WORKER,
            path,
        ],
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


# --------------------------------------------------------------------------- #
# HTTP handler
# --------------------------------------------------------------------------- #
class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass  # keep the console quiet

    def _send(self, code, obj, ctype="application/json"):
        body = obj if isinstance(obj, bytes) else json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self):
        n = int(self.headers.get("Content-Length", 0))
        if not n:
            return {}
        try:
            return json.loads(self.rfile.read(n).decode("utf-8"))
        except json.JSONDecodeError:
            return {}

    # ---- GET ------------------------------------------------------------- #
    def do_GET(self):
        if self.path in ("/", "/index.html"):
            with open(os.path.join(HERE, "index.html"), "rb") as f:
                return self._send(200, f.read(), "text/html; charset=utf-8")

        if self.path == "/api/state":
            cfg = load_config()
            safe = dict(cfg)
            safe["hasKey"] = bool(cfg.get("apiKey"))
            safe["keyMasked"] = _mask(cfg.get("apiKey", ""))
            del safe["apiKey"]
            safe["enabled"] = voice_enabled()
            return self._send(200, safe)

        if self.path == "/api/voices":
            cfg = load_config()
            if not cfg.get("apiKey"):
                return self._send(400, {"error": "no_api_key"})
            try:
                return self._send(200, {"voices": el_voices(cfg["apiKey"])})
            except urllib.error.HTTPError as e:
                return self._send(e.code, {"error": "elevenlabs", "detail": e.read().decode("utf-8", "ignore")})
            except Exception as e:  # noqa
                return self._send(502, {"error": str(e)})

        if self.path == "/api/credits":
            cfg = load_config()
            if not cfg.get("apiKey"):
                return self._send(400, {"error": "no_api_key"})
            try:
                return self._send(200, el_subscription(cfg["apiKey"]))
            except urllib.error.HTTPError as e:
                # 401 here usually means the key works but lacks "User: Read" —
                # voices and speech are unaffected, only the billing view is.
                err = "no_user_scope" if e.code == 401 else "elevenlabs"
                return self._send(e.code, {"error": err, "detail": e.read().decode("utf-8", "ignore")})
            except Exception as e:  # noqa
                return self._send(502, {"error": str(e)})

        return self._send(404, {"error": "not_found"})

    # ---- POST ------------------------------------------------------------ #
    def do_POST(self):
        data = self._read_json()

        if self.path == "/api/key":
            key = (data.get("key") or "").strip()
            cfg = load_config()
            cfg["apiKey"] = key
            save_config(cfg)
            ok = False
            voice_count = 0
            note = ""
            info = {}
            if key:
                # Judge the key by what this app needs it to do — read voices and
                # speak. Billing access is a separate scope a working key may lack.
                try:
                    voice_count = len(el_voices(key))
                    ok = True
                except urllib.error.HTTPError as e:
                    info = {"error": "HTTP %d" % e.code}
                except Exception as e:  # noqa
                    info = {"error": str(e)}
                if ok:
                    try:
                        info = el_subscription(key)
                    except urllib.error.HTTPError as e:
                        note = "no_user_scope" if e.code == 401 else "no_billing"
                    except Exception:  # noqa
                        note = "no_billing"
            return self._send(
                200,
                {"saved": True, "valid": ok, "voices": voice_count, "note": note, "subscription": info},
            )

        if self.path == "/api/premium":
            cfg = load_config()
            cfg["premium"] = bool(data.get("on"))
            save_config(cfg)
            return self._send(200, {"premium": cfg["premium"]})

        if self.path == "/api/enabled":
            set_voice_enabled(bool(data.get("on")))
            return self._send(200, {"enabled": voice_enabled()})

        if self.path == "/api/voice":
            cfg = load_config()
            if "voiceId" in data:
                cfg["voiceId"] = data["voiceId"]
            if "voiceName" in data:
                cfg["voiceName"] = data["voiceName"]
            if "modelId" in data:
                cfg["modelId"] = data["modelId"]
            if "stability" in data:
                cfg["stability"] = float(data["stability"])
            if "similarity" in data:
                cfg["similarity"] = float(data["similarity"])
            if "windowsVoice" in data:
                cfg["windowsVoice"] = data["windowsVoice"]
            save_config(cfg)
            return self._send(200, {"ok": True})

        if self.path == "/api/test":
            text = data.get("text") or "This is a preview of the selected voice for Claude Voice Mode."
            speak_preview(text)
            return self._send(200, {"ok": True})

        return self._send(404, {"error": "not_found"})


def _mask(key):
    if not key:
        return ""
    if len(key) <= 8:
        return "•" * len(key)
    return key[:4] + "…" + key[-4:]


class PanelServer(ThreadingHTTPServer):
    # Without this, Windows lets a second launch bind the same port and steal
    # connections from the first — two panels, one port, confusing results.
    # Refusing to reuse makes a duplicate launch fail loudly instead.
    allow_reuse_address = False


def main():
    port = int(os.environ.get("VOICE_PANEL_PORT", "8770"))
    # make sure a config exists so the worker/panel agree on defaults
    if not os.path.exists(CONFIG_PATH):
        save_config(dict(DEFAULT_CONFIG))
    url = f"http://127.0.0.1:{port}/"
    try:
        srv = PanelServer(("127.0.0.1", port), Handler)
    except OSError:
        print(f"A Claude Voice Mode panel is already running at {url}")
        print("Open that address in your browser, or close the other panel first.")
        return
    print(f"Claude Voice Mode panel running at {url}")
    print("Press Ctrl+C to stop.")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
