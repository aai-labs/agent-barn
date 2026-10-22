import argparse
import errno
import hashlib
import json
import os
import shutil
import tempfile
import threading
import time
import unicodedata
import urllib.error
import urllib.request

DEFAULT_RULES_PATH = "/app/config/file-sync-rules.json"
DEFAULT_STATE_PATH = "/tmp/file-sync-state.json"
CHUNK_BYTES = 32 * 327_680
HASH_BLOCK_BYTES = 1024 * 1024
SETTLE_SECONDS = 5
MAX_PATH_LENGTH = 1024
MAX_ENTRIES = 10_000
TEMP_PREFIX = ".file-sync-"
INGEST_TIMEOUT_SECONDS = 30
TRANSFER_TIMEOUT_SECONDS = 120
DEFAULT_INTERVAL_SECONDS = 15
DEFAULT_ONCE_TIMEOUT_SECONDS = 60
DONE = "done"
SKIPPED_NO_SPACE = "skipped_no_space"
FAILED = "failed"
LOCAL_CHANGED = "local_changed"


class Unauthorized(Exception):
    pass


class IngestRefused(Exception):
    def __init__(self, status, retry_after):
        super().__init__(status)
        self.status = status
        self.retry_after = retry_after


def log(message):
    print(f"[file-sync] {message}", flush=True)


def _under(rel_path, entry):
    return rel_path == entry or rel_path.startswith(f"{entry}/")


def synced(rel_path, rules):
    if not rel_path or rel_path.startswith("/") or "\\" in rel_path:
        return False
    if any(ord(char) < 32 or ord(char) == 127 for char in rel_path):
        return False
    segments = rel_path.split("/")
    if any(segment in ("", ".", "..") for segment in segments):
        return False
    if segments[0] == rules["not_synced_dir"] or any(segment in rules["skip_dir_names"] for segment in segments):
        return False
    if rel_path in rules["memory"] or any(_under(rel_path, entry) for entry in rules["config"]):
        return True
    return _under(rel_path, rules["skills"]) or rel_path.startswith(f"{rules['workspace']}/")


def _worth_entering(rel_dir, rules):
    if _under(rel_dir, rules["workspace"]):
        return True
    return any(entry.startswith(f"{rel_dir}/") for entry in [*rules["memory"], *rules["config"]])


def sha256_of(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while block := handle.read(HASH_BLOCK_BYTES):
            digest.update(block)
    return digest.hexdigest()


def _local_files(rules):
    found = []
    complete = True
    pending = [(rules["root"], "")]
    while pending:
        directory, rel_dir = pending.pop()
        try:
            with os.scandir(directory) as listing:
                items = list(listing)
        except OSError:
            complete = False
            continue
        for item in items:
            rel_path = f"{rel_dir}/{item.name}" if rel_dir else item.name
            if unicodedata.normalize("NFC", item.name) != item.name or item.is_symlink():
                continue
            try:
                if item.is_dir(follow_symlinks=False):
                    if item.name not in rules["skip_dir_names"] and _worth_entering(rel_path, rules):
                        pending.append((item.path, rel_path))
                elif (
                    item.is_file(follow_symlinks=False)
                    and not item.name.startswith(TEMP_PREFIX)
                    and len(rel_path) <= MAX_PATH_LENGTH
                    and synced(rel_path, rules)
                ):
                    found.append((item.path, rel_path, item.stat(follow_symlinks=False)))
            except OSError:
                complete = False
    return found, complete


def scan(rules, cache):
    found, complete = _local_files(rules)
    entries = []
    fresh_cache = {}
    now = time.time()
    for path, rel_path, info in sorted(found, key=lambda found_file: found_file[1]):
        cached = cache.get(rel_path)
        stamp = [info.st_size, info.st_mtime_ns]
        if cached is not None and cached[:2] == stamp:
            digest = cached[2]
        elif now - info.st_mtime_ns / 1e9 < SETTLE_SECONDS:
            digest = None
        else:
            try:
                digest = sha256_of(path)
                after = os.stat(path, follow_symlinks=False)
            except OSError:
                complete = False
                continue
            if [after.st_size, after.st_mtime_ns] != stamp:
                digest = None
        if digest is None:
            if cached is None:
                complete = False
                continue
            fresh_cache[rel_path] = cached
            entries.append({"path": rel_path, "size": cached[0], "sha256": cached[2]})
            continue
        fresh_cache[rel_path] = [*stamp, digest]
        entries.append({"path": rel_path, "size": info.st_size, "sha256": digest})
    if len(entries) > MAX_ENTRIES:
        entries = entries[:MAX_ENTRIES]
        complete = False
    return entries, complete, fresh_cache


def load_state(path):
    try:
        with open(path, encoding="utf-8") as handle:
            files = json.load(handle).get("files", {})
    except (OSError, ValueError, AttributeError):
        return {}
    return files if isinstance(files, dict) else {}


def save_state(path, files):
    temp = f"{path}.tmp"
    try:
        with open(temp, "w", encoding="utf-8") as handle:
            json.dump({"files": files}, handle)
        os.replace(temp, path)
    except OSError as error:
        log(f"could not save the scan cache: {type(error).__name__}")


def _put(url, data, content_range):
    request = urllib.request.Request(url, data=data, method="PUT", headers={"Content-Range": content_range})
    with urllib.request.urlopen(request, timeout=TRANSFER_TIMEOUT_SECONDS) as response:
        return response.status


def upload_file(path, url, sha256):
    try:
        if sha256_of(path) != sha256:
            return False
        digest = hashlib.sha256()
        with open(path, "rb") as handle:
            size = os.fstat(handle.fileno()).st_size
            if size == 0:
                return False
            offset = 0
            while offset < size:
                data = handle.read(min(CHUNK_BYTES, size - offset))
                if not data:
                    return False
                digest.update(data)
                _put(url, data, f"bytes {offset}-{offset + len(data) - 1}/{size}")
                offset += len(data)
    except (OSError, urllib.error.URLError) as error:
        log(f"upload failed: {type(error).__name__}")
        return False
    return digest.hexdigest() == sha256


def _free_bytes(directory):
    return shutil.disk_usage(directory).free


def _matches(path, sha256):
    try:
        return sha256 is not None and sha256_of(path) == sha256
    except OSError:
        return False


def download_file(local, url, reported_sha256):
    if not _matches(local, reported_sha256):
        return LOCAL_CHANGED, None, None
    directory = os.path.dirname(local)
    temp = None
    try:
        with urllib.request.urlopen(url, timeout=TRANSFER_TIMEOUT_SECONDS) as response:
            if _free_bytes(directory) <= int(response.headers.get("Content-Length") or 0):
                return SKIPPED_NO_SPACE, None, None
            descriptor, temp = tempfile.mkstemp(prefix=TEMP_PREFIX, suffix=".tmp", dir=directory)
            digest = hashlib.sha256()
            size = 0
            with os.fdopen(descriptor, "wb") as handle:
                while block := response.read(HASH_BLOCK_BYTES):
                    handle.write(block)
                    digest.update(block)
                    size += len(block)
                handle.flush()
                os.fsync(handle.fileno())
        if not _matches(local, reported_sha256):
            return LOCAL_CHANGED, None, None
        shutil.copymode(local, temp)
        os.replace(temp, local)
        temp = None
        return DONE, digest.hexdigest(), size
    except OSError as error:
        if error.errno == errno.ENOSPC:
            return SKIPPED_NO_SPACE, None, None
        log(f"download failed: {type(error).__name__}")
        return FAILED, None, None
    except ValueError as error:
        log(f"download failed: {type(error).__name__}")
        return FAILED, None, None
    finally:
        if temp is not None:
            try:
                os.remove(temp)
            except OSError:
                pass


def _retry_after(raw):
    try:
        seconds = int(raw)
    except (TypeError, ValueError):
        return None
    return seconds if seconds >= 0 else None


class Ingest:
    def __init__(self, base_url, agent_id, key):
        self.base_url = f"{base_url.rstrip('/')}/agents/{agent_id}/file-sync"
        self.key = key
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def post(self, path, payload):
        return self._send("POST", path, json.dumps(payload).encode())

    def get(self, path):
        return self._send("GET", path, None)

    def _send(self, method, path, data):
        headers = {"Authorization": f"Bearer {self.key}"}
        if data is not None:
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(f"{self.base_url}/{path}", data=data, method=method, headers=headers)
        try:
            with self.opener.open(request, timeout=INGEST_TIMEOUT_SECONDS) as response:
                body = response.read()
        except urllib.error.HTTPError as error:
            if error.code == 401:
                raise Unauthorized from None
            raise IngestRefused(error.code, _retry_after(error.headers.get("Retry-After"))) from None
        return json.loads(body) if body else None


def _local_path(rules, rel_path):
    return os.path.join(rules["root"], *rel_path.split("/"))


def _apply(ingest, rules, reported, operation, cache):
    rel_path = operation.get("path")
    if not isinstance(rel_path, str) or not synced(rel_path, rules):
        log("ignored a job outside the sync rules")
        return
    local = _local_path(rules, rel_path)
    entry = reported.get(rel_path)
    if operation.get("action") == "reupload":
        if entry is not None and upload_file(local, operation["url"], entry["sha256"]):
            ingest.post("uploads/complete", {"path": rel_path})
        else:
            ingest.post("operations/result", {"path": rel_path, "outcome": FAILED})
        return
    if operation.get("action") != "download":
        return
    version = operation.get("version")
    if version is None:
        ingest.post("operations/result", {"path": rel_path, "outcome": FAILED})
        return
    outcome, sha256, size = download_file(local, operation["url"], entry["sha256"] if entry else None)
    result = {"path": rel_path, "outcome": outcome}
    if outcome == DONE:
        result.update(version=version, sha256=sha256, size=size)
        try:
            written = os.stat(local, follow_symlinks=False)
            cache[rel_path] = [written.st_size, written.st_mtime_ns, sha256]
        except OSError:
            cache.pop(rel_path, None)
    ingest.post("operations/result", result)


def run_cycle(ingest, rules, state_path):
    entries, complete, cache = scan(rules, load_state(state_path))
    save_state(state_path, cache)
    answer = ingest.post("changes", {"complete": complete, "entries": entries})
    reported = {entry["path"]: entry for entry in entries}
    for upload in (answer or {}).get("uploads", []):
        entry = reported.get(upload.get("path"))
        if entry is None:
            continue
        if upload_file(_local_path(rules, entry["path"]), upload["url"], entry["sha256"]):
            ingest.post("uploads/complete", {"path": entry["path"]})
    try:
        for operation in (ingest.get("operations") or {}).get("operations", []):
            _apply(ingest, rules, reported, operation, cache)
    finally:
        save_state(state_path, cache)


def _settings():
    agent_id = os.environ.get("AGENT_ID")
    base_url = os.environ.get("INGEST_URL")
    key = os.environ.get("INGEST_API_KEY")
    if not agent_id or not base_url or not key:
        log("not configured; file sync is off")
        return None
    try:
        with open(os.environ.get("FILE_SYNC_RULES", DEFAULT_RULES_PATH), encoding="utf-8") as handle:
            rules = json.load(handle)
    except (OSError, ValueError) as error:
        log(f"could not read the sync rules: {type(error).__name__}")
        return None
    return Ingest(base_url, agent_id, key), rules, os.environ.get("FILE_SYNC_STATE", DEFAULT_STATE_PATH)


def run_once(timeout_seconds):
    settings = _settings()
    if settings is None:
        return 0

    def attempt():
        try:
            run_cycle(*settings)
        except Unauthorized:
            log("ingest refused the key; skipping")
        except Exception as error:
            log(f"sync before start failed: {type(error).__name__}")

    worker = threading.Thread(target=attempt, daemon=True)
    worker.start()
    worker.join(timeout_seconds)
    if worker.is_alive():
        log("sync before start is taking too long; continuing")
    return 0


def run_loop(interval_seconds):
    settings = _settings()
    if settings is None:
        return 0
    while True:
        wait = interval_seconds
        try:
            run_cycle(*settings)
        except Unauthorized:
            log("ingest refused the key; stopping")
            return 0
        except IngestRefused as error:
            log(f"ingest answered {error.status}")
            if error.retry_after is not None:
                wait = max(error.retry_after, interval_seconds)
        except Exception as error:
            log(f"sync failed: {type(error).__name__}")
        time.sleep(wait)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--timeout", type=float, default=DEFAULT_ONCE_TIMEOUT_SECONDS)
    parser.add_argument("--interval", type=float, default=DEFAULT_INTERVAL_SECONDS)
    arguments = parser.parse_args()
    if arguments.once:
        return run_once(arguments.timeout)
    return run_loop(arguments.interval)


if __name__ == "__main__":
    raise SystemExit(main())
