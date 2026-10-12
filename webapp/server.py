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
import re
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import docutil  # noqa: E402 - local module, needs HERE on the path first
import library  # noqa: E402
import synth  # noqa: E402

REPO_HOOKS = os.path.join(os.path.dirname(HERE), "hooks")
HOOKS_DIR = os.path.join(os.path.expanduser("~"), ".claude", "hooks")
CONFIG_PATH = os.path.join(HOOKS_DIR, "voice-config.json")
FLAG_PATH = os.path.join(tempfile.gettempdir(), "claude-voice-enabled")
WORKER = os.path.join(HOOKS_DIR, "speak-worker.ps1")

HOOK_FILES = ("speak-response.ps1", "speak-worker.ps1", "voice-guard.ps1", "tts-server.py")

# Largest document the reader will accept. A 25 MB PDF is already a multi-hour
# listen; anything past that is a mistake, not a document.
MAX_UPLOAD = 25 * 1024 * 1024

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
    # Microsoft neural voices (Andrew, Ava…) via the free read-aloud service.
    # Natural and free, but online.
    "neural": False,
    "neuralVoice": "en-US-AndrewNeural",
    # Piper — neural speech running offline on the CPU.
    "piper": False,
    "piperModel": "",
    "ttsPort": 8771,
    # ---- Document reader --------------------------------------------------- #
    # Deliberately separate keys from the ones above. voice-config.json is
    # machine-wide, so if the reader shared "premium"/"neural"/"piper" then
    # picking a voice to narrate a long document would silently change how
    # Claude speaks to you for the rest of the day. These are read only by the
    # /api/reader routes; engine_of()/apply_engine() still govern Voice Mode
    # alone.
    "readerEngine": "piper",
    "readerNeuralVoice": "en-US-AndrewNeural",
    "readerPiperModel": "",
    "readerVoiceId": "",
    "readerWindowsVoice": "",
    "readerRate": 1.0,
    "readerLaymansTerms": False,
}

# Reader settings, listed once so the settings route cannot drift from the
# defaults above.
READER_KEYS = (
    "readerEngine",
    "readerNeuralVoice",
    "readerPiperModel",
    "readerVoiceId",
    "readerWindowsVoice",
    "readerRate",
    "readerLaymansTerms",
)

# Shown when edge-tts is not importable, so the panel still offers real choices
# instead of an empty list. Kept short — these are the ones worth hearing.
FALLBACK_NEURAL_VOICES = [
    {"name": "en-US-AndrewNeural", "gender": "Male", "tags": "Warm, confident"},
    {"name": "en-US-BrianNeural", "gender": "Male", "tags": "Casual, sincere"},
    {"name": "en-US-ChristopherNeural", "gender": "Male", "tags": "Authoritative"},
    {"name": "en-US-GuyNeural", "gender": "Male", "tags": "Passionate"},
    {"name": "en-US-AvaNeural", "gender": "Female", "tags": "Expressive, caring"},
    {"name": "en-US-EmmaNeural", "gender": "Female", "tags": "Cheerful, clear"},
    {"name": "en-US-JennyNeural", "gender": "Female", "tags": "Friendly"},
    {"name": "en-US-AriaNeural", "gender": "Female", "tags": "Confident"},
]


# --------------------------------------------------------------------------- #
# engines
# --------------------------------------------------------------------------- #
# The worker tries engines in a fixed order and falls through on any failure:
# ElevenLabs, then Microsoft neural, then Piper, then the Windows voice. The
# panel exposes that as a single choice, so the booleans stay coherent — two
# engines "on" at once would silently make the lower one unreachable.
ENGINES = ("elevenlabs", "neural", "piper", "windows")


def engine_of(cfg):
    if cfg.get("premium"):
        return "elevenlabs"
    if cfg.get("neural"):
        return "neural"
    if cfg.get("piper"):
        return "piper"
    return "windows"


def apply_engine(cfg, engine):
    cfg["premium"] = engine == "elevenlabs"
    cfg["neural"] = engine == "neural"
    cfg["piper"] = engine == "piper"
    return cfg


def neural_voices():
    """Every English neural voice the service offers, best effort."""
    try:
        import asyncio

        import edge_tts

        raw = asyncio.new_event_loop().run_until_complete(edge_tts.list_voices())
        out = []
        for v in raw:
            name = v.get("ShortName", "")
            if not name.startswith("en-"):
                continue
            tags = (v.get("VoiceTag") or {}).get("VoicePersonalities") or []
            out.append(
                {
                    "name": name,
                    "gender": v.get("Gender", ""),
                    "tags": ", ".join(tags),
                }
            )
        return sorted(out, key=lambda v: v["name"]) or FALLBACK_NEURAL_VOICES
    except Exception:  # noqa: BLE001 — edge-tts is optional
        return FALLBACK_NEURAL_VOICES


def piper_voices(cfg):
    """Voice models actually sitting on disk, so the panel never offers a lie."""
    folder = cfg.get("piperDir") or os.path.join(HOOKS_DIR, "piper")
    try:
        names = sorted(f for f in os.listdir(folder) if f.endswith(".onnx"))
    except OSError:
        return []
    return [{"name": os.path.splitext(n)[0], "path": os.path.join(folder, n)} for n in names]


def piper_dir(cfg):
    return cfg.get("piperDir") or os.path.join(HOOKS_DIR, "piper")


# --------------------------------------------------------------------------- #
# Piper voice catalog + downloads
# --------------------------------------------------------------------------- #
# install-voices.ps1 fetches a single model, and piper_voices() only ever lists
# what is on disk — so a fresh install shows exactly one offline voice and no
# way to get another without running a script by hand. The catalog below is the
# full list Piper publishes (about 40 English voices), and the panel downloads
# straight into the piper folder so the dropdown grows without leaving the page.
PIPER_CATALOG_URL = "https://huggingface.co/rhasspy/piper-voices/resolve/main/voices.json?download=true"
PIPER_FILE_URL = (
    "https://huggingface.co/rhasspy/piper-voices/resolve/main/"
    "{family}/{code}/{name}/{quality}/{code}-{name}-{quality}{ext}?download=true"
)
PIPER_CATALOG_TTL = 24 * 3600  # the list changes a few times a year at most

# Offered when the catalog cannot be fetched and no cached copy exists. Real
# names from the published list, so a download attempt will actually work once
# the network is back.
FALLBACK_PIPER_CATALOG = [
    ("en_US-ryan-high", "high", 121), ("en_US-ryan-medium", "medium", 63),
    ("en_US-lessac-high", "high", 114), ("en_US-lessac-medium", "medium", 63),
    ("en_US-hfc_female-medium", "medium", 63), ("en_US-hfc_male-medium", "medium", 63),
    ("en_US-amy-medium", "medium", 63), ("en_US-joe-medium", "medium", 63),
    ("en_US-kristin-medium", "medium", 64), ("en_US-john-medium", "medium", 64),
    ("en_US-bryce-medium", "medium", 64), ("en_US-norman-medium", "medium", 64),
    ("en_US-libritts_r-medium", "medium", 79), ("en_US-ljspeech-high", "high", 114),
    ("en_GB-cori-high", "high", 114), ("en_GB-alan-medium", "medium", 63),
    ("en_GB-alba-medium", "medium", 63), ("en_GB-jenny_dioco-medium", "medium", 63),
    ("en_GB-northern_english_male-medium", "medium", 63), ("en_GB-aru-medium", "medium", 77),
]

PIPER_JOBS = {}  # voice key -> {"status", "done", "total", "error"}
PIPER_JOBS_LOCK = threading.Lock()


def _catalog_cache_path(cfg):
    return os.path.join(piper_dir(cfg), "voices-catalog.json")


def _fetch_piper_catalog(cfg):
    """Raw voices.json from Piper's model repo, cached on disk for a day."""
    path = _catalog_cache_path(cfg)
    try:
        if time.time() - os.path.getmtime(path) < PIPER_CATALOG_TTL:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
    except (OSError, json.JSONDecodeError):
        pass
    try:
        req = urllib.request.Request(PIPER_CATALOG_URL, headers={"User-Agent": "claude-voice-mode"})
        with urllib.request.urlopen(req, timeout=20) as r:
            raw = r.read()
        data = json.loads(raw.decode("utf-8"))
        os.makedirs(piper_dir(cfg), exist_ok=True)
        with open(path, "wb") as f:
            f.write(raw)
        return data
    except Exception:  # noqa: BLE001 - offline is normal for an offline engine
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)  # stale beats nothing
        except (OSError, json.JSONDecodeError):
            return None


def piper_catalog(cfg):
    """English voices Piper offers, each marked installed or not.

    Returns {"voices": [...], "source": "live"|"cache"|"fallback"}.
    """
    installed = {v["name"] for v in piper_voices(cfg)}
    raw = _fetch_piper_catalog(cfg)
    out = []
    if raw:
        for key, v in raw.items():
            if not key.startswith("en_"):
                continue
            size = sum(
                f.get("size_bytes", 0) for p, f in (v.get("files") or {}).items() if p.endswith(".onnx")
            )
            lang = v.get("language") or {}
            out.append({
                "key": key,
                "name": v.get("name") or key,
                "quality": v.get("quality") or "",
                "sizeMb": round(size / 1e6),
                "region": lang.get("country_english") or lang.get("region") or "",
                "speakers": v.get("num_speakers") or 1,
            })
        source = "live"
    else:
        out = [
            {"key": k, "name": k.split("-")[1], "quality": q, "sizeMb": mb,
             "region": "United States" if k.startswith("en_US") else "United Kingdom", "speakers": 1}
            for k, q, mb in FALLBACK_PIPER_CATALOG
        ]
        source = "fallback"
    for v in out:
        v["installed"] = v["key"] in installed
    # Best quality first within a region, US before GB — the order you would browse.
    rank = {"high": 0, "medium": 1, "low": 2, "x_low": 3}
    out.sort(key=lambda v: (v["key"][:5] != "en_US", rank.get(v["quality"], 9), v["name"]))
    return {"voices": out, "source": source}


def _piper_urls(key):
    m = re.match(r"^(?P<family>[^_]+)_(?P<region>[^-]+)-(?P<name>[^-]+)-(?P<quality>.+)$", key)
    if not m:
        return None
    args = {
        "family": m.group("family"),
        "code": m.group("family") + "_" + m.group("region"),
        "name": m.group("name"),
        "quality": m.group("quality"),
    }
    return (PIPER_FILE_URL.format(ext=".onnx", **args), PIPER_FILE_URL.format(ext=".onnx.json", **args))


def _download_piper_voice(key, folder):
    """Worker thread body. Writes .part files and renames only when complete,
    so a half-downloaded model never shows up in the voice list."""
    job = PIPER_JOBS[key]
    model_url, cfg_url = _piper_urls(key)
    model_path = os.path.join(folder, key + ".onnx")
    try:
        os.makedirs(folder, exist_ok=True)
        for url, dest in ((cfg_url, model_path + ".json"), (model_url, model_path)):
            req = urllib.request.Request(url, headers={"User-Agent": "claude-voice-mode"})
            with urllib.request.urlopen(req, timeout=60) as r:
                total = int(r.headers.get("Content-Length") or 0)
                if dest == model_path:
                    job["total"] = total
                with open(dest + ".part", "wb") as f:
                    while True:
                        chunk = r.read(1024 * 256)
                        if not chunk:
                            break
                        f.write(chunk)
                        if dest == model_path:
                            job["done"] += len(chunk)
            os.replace(dest + ".part", dest)
        job["status"] = "done"
    except Exception as e:  # noqa: BLE001 - shown in the panel
        job["status"] = "error"
        job["error"] = str(e)
        for p in (model_path + ".part", model_path + ".json.part"):
            try:
                os.remove(p)
            except OSError:
                pass


def start_piper_download(key, cfg):
    if not _piper_urls(key):
        return {"error": "bad_voice_name"}
    with PIPER_JOBS_LOCK:
        job = PIPER_JOBS.get(key)
        if job and job["status"] == "running":
            return {"started": False, "job": job}
        PIPER_JOBS[key] = job = {"status": "running", "done": 0, "total": 0, "error": ""}
    threading.Thread(target=_download_piper_voice, args=(key, piper_dir(cfg)), daemon=True).start()
    return {"started": True, "job": job}


def delete_piper_voice(key, cfg):
    """Remove a downloaded model. Refuses anything outside the piper folder."""
    folder = os.path.abspath(piper_dir(cfg))
    base = os.path.abspath(os.path.join(folder, key + ".onnx"))
    if os.path.dirname(base) != folder or not os.path.isfile(base):
        return False
    for p in (base, base + ".json"):
        try:
            os.remove(p)
        except OSError:
            pass
    # Don't leave the config pointing at a file that is gone.
    changed = False
    for k in ("piperModel", "readerPiperModel"):
        if os.path.abspath(cfg.get(k) or "") == base:
            left = piper_voices(cfg)
            cfg[k] = left[0]["path"] if left else ""
            changed = True
    if changed:
        save_config(cfg)
    return True


# --------------------------------------------------------------------------- #
# engine health: what actually spoke, and whether neural is reachable
# --------------------------------------------------------------------------- #
# The worker tries engines top-down and falls through in silence, so when the
# chosen engine is broken every reply comes out in the fallback voice and the
# panel still shows the pick you made. These two functions make that visible.
DEBUG_LOG = os.path.join(tempfile.gettempdir(), "claude-voice-debug.log")

_NEURAL_HEALTH = {"at": 0.0, "ok": None, "error": ""}
_NEURAL_HEALTH_TTL = 600  # re-probe every ten minutes, or on demand


def last_spoken():
    """Parse the last reply's block of the worker log.

    Returns {"when", "spoke", "voice", "fellBack": [{"engine", "error"}]} or
    None when the log has no header yet (old worker, or never spoken).
    """
    try:
        with open(DEBUG_LOG, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.read().splitlines()[-400:]
    except OSError:
        return None
    start = None
    for i in range(len(lines) - 1, -1, -1):
        if lines[i].startswith("--- "):
            start = i
            break
    if start is None:
        return None
    out = {"when": lines[start].strip("- "), "spoke": "", "voice": "", "fellBack": []}
    for ln in lines[start + 1:]:
        t = ln.strip()
        m = re.match(r"^(\w+) spoke ok=True(?: voice=(.+?))?(?: model=\S+)?$", t, re.I)
        if m:
            eng = m.group(1).lower()
            out["spoke"] = "elevenlabs" if eng == "premium" else eng
            out["voice"] = m.group(2) or ""
            continue
        m = re.match(r"^(\w+) error -> falling back: (.*)$", t, re.I)
        if m:
            eng = m.group(1).lower()
            out["fellBack"].append({
                "engine": "elevenlabs" if eng == "premium" else eng,
                "error": m.group(2),
            })
            continue
        if t.startswith("tts server") or t.endswith("empty audio"):
            out["fellBack"].append({"engine": "local", "error": t})
    return out


def neural_health(force=False):
    """Can Microsoft's read-aloud service be reached right now?

    A real one-word synthesis, not a ping: the voice list stays up even when the
    websocket is refused (which is exactly what happened in October 2026 when
    Microsoft changed its anti-abuse token and every edge-tts install got 403s).
    """
    now = time.time()
    if not force and _NEURAL_HEALTH["ok"] is not None and now - _NEURAL_HEALTH["at"] < _NEURAL_HEALTH_TTL:
        return dict(_NEURAL_HEALTH)
    ok, err = False, ""
    try:
        import asyncio

        import edge_tts

        async def run():
            comm = edge_tts.Communicate("Hi.", DEFAULT_CONFIG["neuralVoice"])
            async for part in comm.stream():
                if part["type"] == "audio" and part["data"]:
                    return True
            return False

        loop = asyncio.new_event_loop()
        try:
            ok = loop.run_until_complete(asyncio.wait_for(run(), timeout=12))
        finally:
            loop.close()
        if not ok:
            err = "no audio returned"
    except ImportError:
        err = "edge-tts is not installed"
    except Exception as e:  # noqa: BLE001 - the message is the point
        err = str(e)
        m = re.search(r"\b(\d{3})\b", err)
        if m and m.group(1) == "403":
            err = ("Microsoft refused the connection (403). This is a known outage: Microsoft changed "
                   "its anti-abuse token on 10 Oct 2026 and every edge-tts install is affected. "
                   "Fix: upgrade edge-tts when a release ships (pip install -U edge-tts). "
                   "Until then pick Piper for offline voices or ElevenLabs.")
    _NEURAL_HEALTH.update({"at": now, "ok": bool(ok), "error": err})
    return dict(_NEURAL_HEALTH)


# --------------------------------------------------------------------------- #
# config helpers
# --------------------------------------------------------------------------- #
def load_config():
    cfg = dict(DEFAULT_CONFIG)
    try:
        # utf-8-sig, not utf-8: stock Windows tools write a byte order mark, and
        # plain utf-8 would fail to parse and silently reset every setting.
        with open(CONFIG_PATH, "r", encoding="utf-8-sig") as f:
            cfg.update(json.load(f))
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    return cfg


def save_config(cfg):
    os.makedirs(HOOKS_DIR, exist_ok=True)
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)


def stale_hooks():
    """Hook scripts whose installed copy differs from this checkout.

    The hooks run from ~/.claude/hooks, outside the repo, so `git pull` alone
    leaves them behind. A stale worker ignores voice-config.json entirely — the
    panel then writes settings nothing reads, and premium silently never fires.
    Returns [] when not running from a checkout (nothing to compare against).
    """
    out = []
    for name in HOOK_FILES:
        try:
            with open(os.path.join(REPO_HOOKS, name), "rb") as f:
                want = f.read()
        except OSError:
            continue
        try:
            with open(os.path.join(HOOKS_DIR, name), "rb") as f:
                have = f.read()
        except OSError:
            out.append(name)
            continue
        if want != have:
            out.append(name)
    return out


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
    return subprocess.Popen(
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

    def _page(self, name):
        with open(os.path.join(HERE, name), "rb") as f:
            return self._send(200, f.read(), "text/html; charset=utf-8")

    # ---- GET ------------------------------------------------------------- #
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        query = urllib.parse.parse_qs(parsed.query)

        if path in ("/", "/index.html"):
            return self._page("index.html")

        if path in ("/reader", "/reader.html"):
            return self._page("reader.html")

        if path.startswith("/api/reader"):
            return self._reader_get(path, query)

        if self.path == "/api/state":
            cfg = load_config()
            safe = dict(cfg)
            safe["hasKey"] = bool(cfg.get("apiKey"))
            safe["keyMasked"] = _mask(cfg.get("apiKey", ""))
            del safe["apiKey"]
            safe["enabled"] = voice_enabled()
            safe["staleHooks"] = stale_hooks()
            safe["engine"] = engine_of(cfg)
            safe["piperInstalled"] = bool(piper_voices(cfg))
            safe["lastSpoken"] = last_spoken()
            # Only probe the service when it is the engine in use; a probe costs
            # a network round trip and the answer is irrelevant otherwise.
            safe["neuralHealth"] = neural_health() if safe["engine"] == "neural" else None
            return self._send(200, safe)

        if path == "/api/neural-health":
            return self._send(200, neural_health(force="force" in query))

        if self.path == "/api/tts-voices":
            cfg = load_config()
            return self._send(
                200, {"neural": neural_voices(), "piper": piper_voices(cfg)}
            )

        if path == "/api/piper/catalog":
            return self._send(200, piper_catalog(load_config()))

        if path == "/api/piper/downloads":
            with PIPER_JOBS_LOCK:
                jobs = {k: dict(v) for k, v in PIPER_JOBS.items()}
            return self._send(200, {"jobs": jobs, "installed": piper_voices(load_config())})

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
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path.startswith("/api/reader"):
            return self._reader_post(parsed.path, urllib.parse.parse_qs(parsed.query))

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
            # Kept for older panels: turning premium on must still turn the
            # other engines off, or the choice would not be a choice.
            apply_engine(cfg, "elevenlabs" if data.get("on") else "windows")
            save_config(cfg)
            return self._send(200, {"premium": cfg["premium"]})

        if self.path == "/api/engine":
            engine = (data.get("engine") or "").strip().lower()
            if engine not in ENGINES:
                return self._send(400, {"error": "unknown_engine"})
            cfg = apply_engine(load_config(), engine)
            save_config(cfg)
            return self._send(200, {"engine": engine_of(cfg)})

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
            if "neuralVoice" in data:
                cfg["neuralVoice"] = data["neuralVoice"]
            if "piperModel" in data:
                cfg["piperModel"] = data["piperModel"]
            save_config(cfg)
            return self._send(200, {"ok": True})

        if self.path == "/api/piper/download":
            res = start_piper_download((data.get("voice") or "").strip(), load_config())
            return self._send(400 if "error" in res else 200, res)

        if self.path == "/api/piper/delete":
            ok = delete_piper_voice((data.get("voice") or "").strip(), load_config())
            return self._send(200 if ok else 404, {"ok": ok})

        if self.path == "/api/test":
            text = data.get("text") or "This is a preview of the selected voice for Claude Voice Mode."
            proc = speak_preview(text)
            # Wait for the worker so the answer can say which engine really spoke.
            # The preview sentence is short; 90 s covers a cold model load plus
            # two online engines timing out before the fallback.
            try:
                proc.wait(timeout=90)
            except subprocess.TimeoutExpired:
                pass
            return self._send(200, {"ok": True, "lastSpoken": last_spoken()})

        return self._send(404, {"error": "not_found"})

    # ---- Document reader -------------------------------------------------- #
    # Kept in its own pair of handlers rather than mixed into the routes above,
    # because the reader is a second product sharing this process and the two
    # should stay easy to tell apart.
    def _reader_get(self, path, query):
        cfg = load_config()

        if path == "/api/reader/state":
            return self._send(200, {
                "settings": {k: cfg.get(k, DEFAULT_CONFIG.get(k)) for k in READER_KEYS},
                "library": library.recent(),
                "cacheBytes": library.cache_size(),
                "hasElevenKey": bool(cfg.get("apiKey")),
                "piperInstalled": bool(piper_voices(cfg)),
                "pdfSupported": bool(docutil.find_pdftotext()),
                "voiceModeEngine": engine_of(cfg),
            })

        if path == "/api/reader/voices":
            out = {
                "neural": neural_voices(),
                "piper": piper_voices(cfg),
                "windows": synth.windows_voices(),
                "elevenlabs": [],
            }
            if cfg.get("apiKey"):
                try:
                    out["elevenlabs"] = el_voices(cfg["apiKey"])
                except Exception:  # noqa: BLE001 - a missing list is not fatal
                    pass
            return self._send(200, out)

        if path == "/api/reader/library":
            return self._send(200, {"items": library.recent()})

        if path == "/api/reader/doc":
            doc = library.load_doc((query.get("id") or [""])[0])
            if not doc:
                return self._send(404, {"error": "unknown_document"})
            entry = library.load_index().get(doc["id"], {})
            doc = dict(doc)
            doc["position"] = entry.get("position", 0)
            doc["estimates"] = {
                e: synth.estimate(doc["chars"], e) for e in synth.ENGINES
            }
            return self._send(200, doc)

        if path == "/api/reader/chunk":
            return self._reader_chunk(cfg, query)

        return self._send(404, {"error": "not_found"})

    def _reader_chunk(self, cfg, query):
        doc_id = (query.get("id") or [""])[0]
        try:
            index = int((query.get("i") or ["-1"])[0])
        except ValueError:
            index = -1

        doc = library.load_doc(doc_id)
        if not doc:
            return self._send(404, {"error": "unknown_document"})
        if index < 0 or index >= len(doc["chunks"]):
            return self._send(404, {"error": "no_such_chunk"})

        engine = ((query.get("engine") or [""])[0] or cfg.get("readerEngine") or "piper").lower()
        if engine not in synth.ENGINES:
            return self._send(400, {"error": "unknown_engine"})
        voice = (query.get("voice") or [""])[0] or reader_voice(cfg, engine)

        _mime, ext = synth.MIME[engine]
        hit = library.cached_audio(doc_id, index, engine, voice, ext)
        if hit:
            with open(hit, "rb") as f:
                return self._send_audio(f.read(), _mime, cached=True)

        text = doc["chunks"][index]["text"]
        if cfg.get("readerLaymansTerms"):
            text = docutil.simplify_to_laymans_terms(text)
        try:
            audio, mime, ext = synth.synthesize(text, engine, voice, cfg)
        except synth.SynthError as e:
            # Deliberately not falling back to another engine. Forty minutes of
            # a document read in a voice you did not choose is worse than an
            # error you can act on.
            return self._send(502, {"error": "synth_failed", "detail": str(e)})

        library.store_audio(doc_id, index, engine, voice, ext, audio)
        return self._send_audio(audio, mime, cached=False)

    def _send_audio(self, data, mime, cached):
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "private, max-age=3600")
        self.send_header("X-Cache", "hit" if cached else "miss")
        self.end_headers()
        self.wfile.write(data)

    def _reader_post(self, path, query):
        if path == "/api/reader/upload":
            return self._reader_upload(query)

        data = self._read_json()
        cfg = load_config()

        if path == "/api/reader/settings":
            for k in READER_KEYS:
                if k in data:
                    cfg[k] = data[k]
            if cfg.get("readerEngine") not in synth.ENGINES:
                return self._send(400, {"error": "unknown_engine"})
            save_config(cfg)
            return self._send(200, {
                "settings": {k: cfg.get(k) for k in READER_KEYS},
                # Proof for the caller that Voice Mode was left alone.
                "voiceModeEngine": engine_of(cfg),
            })

        if path == "/api/reader/progress":
            ok = library.set_position(data.get("id", ""), data.get("i", 0))
            return self._send(200 if ok else 404, {"ok": ok})

        if path == "/api/reader/delete":
            return self._send(200, {"ok": library.delete_doc(data.get("id", ""))})

        if path == "/api/reader/clear-cache":
            library.clear_audio(data.get("id"))
            return self._send(200, {"ok": True, "cacheBytes": library.cache_size()})

        return self._send(404, {"error": "not_found"})

    def _reader_upload(self, query):
        """Raw file body plus an X-Filename header.

        Deliberately not multipart: the browser can post a File object directly
        as the body, which saves parsing multipart in the standard library for
        no benefit.
        """
        name = self.headers.get("X-Filename") or "document.md"
        name = os.path.basename(urllib.parse.unquote(name))
        ext = os.path.splitext(name)[1].lower()
        if ext not in docutil.SUPPORTED:
            return self._send(400, {
                "error": "unsupported_type",
                "detail": "Supported: " + ", ".join(docutil.SUPPORTED),
            })

        size = int(self.headers.get("Content-Length", 0) or 0)
        if size <= 0:
            return self._send(400, {"error": "empty_upload"})
        if size > MAX_UPLOAD:
            return self._send(413, {"error": "too_large"})

        fd, tmp = tempfile.mkstemp(prefix="reader-upload-", suffix=ext)
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(self.rfile.read(size))
            doc = docutil.load_document(tmp, filename=name)
        except Exception as e:  # noqa: BLE001 - surfaced in the page
            return self._send(400, {"error": "extract_failed", "detail": str(e)})
        finally:
            try:
                os.remove(tmp)
            except OSError:
                pass

        if not doc["chunks"]:
            return self._send(400, {
                "error": "nothing_to_read",
                "detail": "No readable prose found in that file.",
            })

        entry = library.save_doc(doc)
        return self._send(200, {"id": doc["id"], "entry": entry})


def reader_voice(cfg, engine):
    """The saved reader voice for an engine.

    Piper falls back to any model on disk so a fresh install can play something
    without making you visit settings first.
    """
    if engine == "neural":
        return cfg.get("readerNeuralVoice") or DEFAULT_CONFIG["readerNeuralVoice"]
    if engine == "elevenlabs":
        return cfg.get("readerVoiceId") or cfg.get("voiceId") or ""
    if engine == "windows":
        return cfg.get("readerWindowsVoice") or cfg.get("windowsVoice") or ""
    model = cfg.get("readerPiperModel") or cfg.get("piperModel") or ""
    if not model or not os.path.isfile(model):
        found = piper_voices(cfg)
        model = found[0]["path"] if found else ""
    return model


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
    port = int(os.environ.get("VOICE_PANEL_PORT", "8772"))
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
