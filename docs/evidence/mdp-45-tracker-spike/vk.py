"""Tiny Vikunja API helper for the MDP-45 spike (local throwaway instance)."""
import json, sys, urllib.request, urllib.error, uuid

BASE = __import__("os").environ.get("VK_BASE", "http://127.0.0.1:13456/api/v1")

def call(method, path, token=None, body=None, raw=None, ctype=None):
    data, headers = None, {}
    if body is not None:
        data, headers["Content-Type"] = json.dumps(body).encode(), "application/json"
    if raw is not None:
        data, headers["Content-Type"] = raw, ctype
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(BASE + path, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req) as r:
            payload = r.read()
            ct = r.headers.get("Content-Type", "")
            return r.status, (json.loads(payload) if "json" in ct and payload else payload)
    except urllib.error.HTTPError as e:
        payload = e.read()
        try:
            return e.code, json.loads(payload)
        except Exception:
            return e.code, payload[:300]

def multipart(field, filename, content, mime="application/pdf"):
    b = uuid.uuid4().hex
    body = (f"--{b}\r\nContent-Disposition: form-data; name=\"{field}\"; filename=\"{filename}\"\r\n"
            f"Content-Type: {mime}\r\n\r\n").encode() + content + f"\r\n--{b}--\r\n".encode()
    return body, f"multipart/form-data; boundary={b}"

def login():
    s, r = call("POST", "/login", body={"username": "agentbarn-svc", "password": "spike-local-pass"})
    assert s == 200, (s, r)
    return r["token"]
