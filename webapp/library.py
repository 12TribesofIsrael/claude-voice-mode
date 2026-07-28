#!/usr/bin/env python3
"""
Claude Voice Mode - document reader: the library on disk.

Three things have to survive the browser tab being closed:

  the document   Extracting and chunking a PDF is not free, and the text is what
                 the player renders, so it is stored once and reloaded by id.
  the audio      Generating a forty minute document costs real time, and on
                 ElevenLabs real money. Nobody should pay for the same paragraph
                 twice, so every chunk is cached keyed by engine and voice.
  the position   The whole point of an audiobook is stopping halfway.

Everything lives under one folder that is git-ignored, so a document you were
reading never turns up in a commit.
"""
import json
import os
import re
import shutil
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, ".reader")
DOCS = os.path.join(ROOT, "docs")
AUDIO = os.path.join(ROOT, "audio")
INDEX = os.path.join(ROOT, "library.json")

# Ids are hashes we generate, but they arrive back from the browser as URL path
# segments, so they get validated before touching the filesystem regardless.
_ID_OK = re.compile(r"^[a-f0-9]{8,64}$")


def _ensure():
    for d in (ROOT, DOCS, AUDIO):
        os.makedirs(d, exist_ok=True)


def valid_id(doc_id):
    return bool(doc_id and _ID_OK.match(doc_id))


# --------------------------------------------------------------------------- #
# documents
# --------------------------------------------------------------------------- #
def save_doc(doc):
    _ensure()
    with open(os.path.join(DOCS, doc["id"] + ".json"), "w", encoding="utf-8") as f:
        json.dump(doc, f)

    lib = load_index()
    entry = lib.get(doc["id"], {})
    entry.update({
        "id": doc["id"],
        "title": doc["title"],
        "filename": doc["filename"],
        "chars": doc["chars"],
        "chunks": len(doc["chunks"]),
        "opened": time.time(),
    })
    entry.setdefault("position", 0)
    lib[doc["id"]] = entry
    save_index(lib)
    return entry


def load_doc(doc_id):
    if not valid_id(doc_id):
        return None
    try:
        with open(os.path.join(DOCS, doc_id + ".json"), "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def delete_doc(doc_id):
    if not valid_id(doc_id):
        return False
    try:
        os.remove(os.path.join(DOCS, doc_id + ".json"))
    except OSError:
        pass
    shutil.rmtree(os.path.join(AUDIO, doc_id), ignore_errors=True)
    lib = load_index()
    lib.pop(doc_id, None)
    save_index(lib)
    return True


# --------------------------------------------------------------------------- #
# library index (titles + saved positions)
# --------------------------------------------------------------------------- #
def load_index():
    try:
        with open(INDEX, "r", encoding="utf-8-sig") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def save_index(lib):
    _ensure()
    with open(INDEX, "w", encoding="utf-8") as f:
        json.dump(lib, f, indent=2)


def set_position(doc_id, chunk_index):
    lib = load_index()
    if doc_id in lib:
        lib[doc_id]["position"] = int(chunk_index)
        lib[doc_id]["opened"] = time.time()
        save_index(lib)
        return True
    return False


def recent(limit=25):
    lib = load_index()
    items = sorted(lib.values(), key=lambda e: e.get("opened", 0), reverse=True)
    return items[:limit]


# --------------------------------------------------------------------------- #
# audio cache
# --------------------------------------------------------------------------- #
def _voice_key(voice):
    """A voice can be a file path (Piper) or an id with punctuation, neither of
    which is safe as a filename. Reduce it to something that is, keeping enough
    of the original that a cache folder is still readable by a human."""
    stem = os.path.splitext(os.path.basename(str(voice or "default")))[0]
    return re.sub(r"[^A-Za-z0-9._-]", "_", stem)[:60] or "default"


def audio_path(doc_id, index, engine, voice, ext):
    _ensure()
    folder = os.path.join(AUDIO, doc_id, "%s-%s" % (engine, _voice_key(voice)))
    os.makedirs(folder, exist_ok=True)
    return os.path.join(folder, "%05d%s" % (int(index), ext))


def cached_audio(doc_id, index, engine, voice, ext):
    path = audio_path(doc_id, index, engine, voice, ext)
    if os.path.isfile(path) and os.path.getsize(path) > 400:
        return path
    return None


def store_audio(doc_id, index, engine, voice, ext, data):
    path = audio_path(doc_id, index, engine, voice, ext)
    # Write beside the target and rename, so a browser that requests the same
    # chunk twice at once can never read a half-written file.
    tmp = path + ".part"
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, path)
    return path


def cache_size():
    total = 0
    for base, _dirs, files in os.walk(AUDIO):
        for name in files:
            try:
                total += os.path.getsize(os.path.join(base, name))
            except OSError:
                pass
    return total


def clear_audio(doc_id=None):
    target = os.path.join(AUDIO, doc_id) if doc_id and valid_id(doc_id) else AUDIO
    shutil.rmtree(target, ignore_errors=True)
    _ensure()
