"""Read aai-cli's version-1 XChaCha20-Poly1305 store during a stopped-pod handoff.

The format is pinned with the CLI image dependency and checked against real CLI stores.
Only the SharePoint entry is returned; callers never persist the key or whole store.
"""

import base64
import json

from nacl.bindings import crypto_aead_xchacha20poly1305_ietf_decrypt


def sharepoint_refresh_token(store_json: str, key_text: str) -> str:
    store = json.loads(store_json)
    if store["version"] != 1:
        raise ValueError("Unsupported aai-cli store")
    key = base64.b64decode(key_text.strip(), validate=True)
    nonce = base64.b64decode(store["nonce"], validate=True)
    if len(key) != 32 or len(nonce) != 24:
        raise ValueError("Invalid aai-cli store")
    plaintext = crypto_aead_xchacha20poly1305_ietf_decrypt(
        base64.b64decode(store["ciphertext"], validate=True), None, nonce, key
    )
    value = json.loads(plaintext).get("microsoft.sharepoint_refresh_token")
    if not isinstance(value, str) or not value:
        raise ValueError("SharePoint refresh token missing")
    return value
