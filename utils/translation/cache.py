# utils/translation/cache.py
import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Optional


class Translation_Cache:
    """Per-thread JSON cache under assets/temp/{thread_id}/translation_cache.json.

    Key: SHA-256 hex digest of:
        f"{thread_id}|{sha256(text_utf8)}|{target_lang}|{model_id}"
    Value: the translated string.

    Writes are atomic (temp file + os.replace). Reads tolerate missing files
    and corrupt JSON (treated as empty cache). The cache stores no metadata
    about translation success or failure; only successful translations are
    written (Req 7.4).
    """

    _CACHE_FILENAME = "translation_cache.json"

    def __init__(self, base_dir: str = "assets/temp") -> None:
        self._base = Path(base_dir)
        # In-memory miss bloom set per (thread_id, target_lang, model_id) tuple
        # so we don't re-read the cache once we've established it's empty
        # for a given triple within a run (Req 7.3).
        self._known_empty: set[tuple[str, str, str]] = set()

    @staticmethod
    def _hash_text(text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    @staticmethod
    def _cache_key(thread_id: str, text: str, target_lang: str, model_id: str) -> str:
        composite = f"{thread_id}|{Translation_Cache._hash_text(text)}|{target_lang}|{model_id}"
        return hashlib.sha256(composite.encode("utf-8")).hexdigest()

    def _path(self, thread_id: str) -> Path:
        return self._base / thread_id / self._CACHE_FILENAME

    def _read(self, thread_id: str) -> dict:
        p = self._path(thread_id)
        if not p.exists():
            return {}
        try:
            with p.open("r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return {}

    def get(self, *, thread_id: str, text: str, target_lang: str, model_id: str) -> Optional[str]:
        triple = (thread_id, target_lang, model_id)
        if triple in self._known_empty:
            return None
        data = self._read(thread_id)
        if not data:
            self._known_empty.add(triple)
            return None
        key = self._cache_key(thread_id, text, target_lang, model_id)
        return data.get(key)

    def put(self, *, thread_id: str, text: str, target_lang: str, model_id: str, translation: str) -> None:
        """Atomic write: read-modify-tempfile-rename.

        Raises OSError on persistent I/O failure; Translation_Service catches
        and warns (Req 7.5).

        Note: ValueError from invalid path characters (e.g. null bytes in
        thread_id) is re-raised as OSError so the caller's OSError handler
        can treat it as a cache write failure and continue.
        """
        path = self._path(thread_id)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
        except ValueError as exc:
            raise OSError(f"Invalid cache path for thread_id {thread_id!r}: {exc}") from exc

        data = self._read(thread_id)
        key = self._cache_key(thread_id, text, target_lang, model_id)
        data[key] = translation

        # Atomic write
        fd, tmp_path = tempfile.mkstemp(prefix=".trcache.", dir=str(path.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as tmp:
                json.dump(data, tmp, ensure_ascii=False, indent=2)
            os.replace(tmp_path, path)
        except OSError:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

        # Once we've written, the triple is no longer "known empty"
        self._known_empty.discard((thread_id, target_lang, model_id))
