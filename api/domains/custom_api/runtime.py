"""Custom API artifacts use the same start generation as built-in integrations."""

import hashlib
import json
import secrets
from uuid import UUID

from api.domains.custom_api.models import CustomApiConnection
from api.domains.custom_api.repository import CustomApiRepository
from api.domains.custom_api.request import credential_headers, parse_url
from api.domains.integrations.plugins.base import RuntimeArtifacts
from api.infrastructure.crypto import decrypt_token


def connection_snapshot(rows: list[CustomApiConnection]) -> dict:
    return {
        "custom_api:" + row.slug: {
            "binding_id": str(row.id),
            "base_url": row.base_url,
            "isolated": row.isolated,
            "revision": hashlib.sha256(row.credentials_encrypted.encode()).hexdigest(),
        }
        for row in rows
    }


def materialize_custom_api(
    rows: list[CustomApiConnection],
    encryption_key: str,
    gateway_url: str,
    repository: CustomApiRepository,
    generation: UUID | None = None,
    *,
    home_dir: str = "/home/node",
    store_dir: str | None = None,
) -> RuntimeArtifacts:
    """Append CLI profiles and reconcile their namespaced encrypted-store entries.

    Only references enter the ConfigMap. Startup transfers values from the pod Secret
    over stdin, so terminal tools work even when the runtime filters its environment.
    The manifest survives restarts and removes former direct credentials on isolation,
    auth changes, header removal, and connection deletion.
    """
    config_dir = f"{home_dir}/.config/aai-cli"
    store = store_dir or config_dir
    config_path = f"{config_dir}/config.toml"
    manifest = f"{store}/custom-api-secrets.list"
    blocks: list[str] = []
    env: dict[str, str] = {}
    entries: list[tuple[str, str]] = []
    policy_lines: list[str] = []

    def secret_ref(row: CustomApiConnection, field: str, value: str) -> str:
        name = f"custom-api.{row.id.hex}.{field}"
        variable = "AAI_CUSTOM_API_" + row.id.hex.upper() + "_" + field.upper()
        entries.append((name, variable))
        env[variable] = value
        return json.dumps(name)

    for row in rows:
        credentials = json.loads(decrypt_token(row.credentials_encrypted, encryption_key))
        credential_headers(credentials)
        parse_url(row.base_url, base=True)
        profile = "custom-api-" + row.slug
        lines = [f"[profiles.{profile}]", 'provider = "custom_api"', f"base_url = {json.dumps(row.base_url)}"]
        if row.isolated:
            if not gateway_url:
                raise ValueError("Custom API isolation requires a credential gateway")
            token = secrets.token_urlsafe(32) if generation else "preflight"
            lines += [
                'auth_type = "none"',
                f"gateway_url = {json.dumps(gateway_url.rstrip('/') + '/custom-api/request')}",
                f"gateway_token_secret = {secret_ref(row, 'gateway', token)}",
            ]
            if generation:
                row.token_hash = hashlib.sha256(token.encode()).hexdigest()
        else:
            auth = credentials.get("auth", {"type": "none"})
            auth_type = auth["type"]
            lines.append(
                f"auth_type = {json.dumps({'bearer': 'bearer_token', 'api_key': 'api_key_header'}.get(auth_type, auth_type))}"
            )
            if auth_type == "bearer":
                lines.append(f"token_secret = {secret_ref(row, 'token', auth['token'])}")
            elif auth_type == "api_key":
                lines += [
                    f"api_key_header = {json.dumps(auth['header_name'])}",
                    f"api_token_secret = {secret_ref(row, 'token', auth['token'])}",
                ]
            elif auth_type == "basic":
                lines += [
                    f"username_secret = {secret_ref(row, 'username', auth['username'])}",
                    f"password_secret = {secret_ref(row, 'password', auth['password'])}",
                ]
            for index, header in enumerate(credentials.get("headers", [])):
                lines += [
                    f"[[profiles.{profile}.headers]]",
                    f"name = {json.dumps(header['name'])}",
                    (
                        f"value_secret = {secret_ref(row, f'header_{index}', header['value'])}"
                        if header["value"]
                        else 'value = ""'
                    ),
                    f"secret = {str(header.get('secret', False)).lower()}",
                ]
            row.token_hash = None
        if generation:
            row.generation = generation
            repository.save(row)
        blocks.append("\n".join(lines))
        policy_lines.append(f"- {row.slug}: {row.name} ({row.base_url}), `--profile {profile}`")

    setup = [
        f"mkdir -p {config_dir} {store}",
        # This also installs an empty profile set after the final connection is removed.
        f"cp /app/config/aai-cli-config.toml {config_path}",
        f"if [ -f {manifest} ]; then",
        "  while IFS= read -r custom_api_secret; do",
        '    case "$custom_api_secret" in',
        "      custom-api.*) aai-cli --config " + config_path + ' secrets remove "$custom_api_secret" ;;',
        "    esac",
        f"  done < {manifest}",
        "fi",
        # Record all intended entries before writing any, making partial startup retryable.
        f": > {manifest}",
    ]
    for name, _ in entries:
        setup.append(f"printf '%s\\n' '{name}' >> {manifest}")
    for name, variable in entries:
        setup.append(f"printf '%s' \"${variable}\" | aai-cli --config {config_path} secrets set {name}")
    policy = ""
    if policy_lines:
        policy = (
            "\n\n## Custom API connections (aai-cli)\n\n"
            + "\n".join(policy_lines)
            + """

Use your terminal tool: `aai-cli --profile custom-api-CONNECTION_ID custom-api request
--url https://api.example.com/v1/items --method GET`. For a complete request, use
`--request-json -` with JSON on stdin: {"method":"GET","url":"https://api.example.com/v1/items",
"query":{"limit":10},"body":null,"headers":[]}.
URLs MUST be absolute and inside the connection's configured origin/base path.
The command returns {"status":200,"body":...} with JSON or text. Redirects are refused.
Use aai-cli for these connections. Never read or print credential environment variables
or the encrypted store. API-specific usage comes from assigned Skills or your template;
do not infer endpoint contracts from connection names.
"""
        )
    return RuntimeArtifacts(
        files={"custom-api-profiles.toml": "\n\n".join(blocks), "custom-api-setup.sh": "\n".join(setup) + "\n"},
        env=env,
        policy_md=policy,
    )
