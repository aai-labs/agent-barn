FROM node:22-bookworm-slim

ENV PLAYWRIGHT_BROWSERS_PATH=/opt/playwright \
    UV_PYTHON_INSTALL_DIR=/opt/python \
    PIP_BREAK_SYSTEM_PACKAGES=1

RUN --mount=type=cache,target=/var/cache/apt,sharing=locked <<EOF
set -e
apt-get update
apt-get install -y --no-install-recommends git curl jq ripgrep ca-certificates tini
EOF

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

RUN <<EOF
set -e
uv python install 3.12
ln -sf "$(uv python find 3.12)" /usr/local/bin/python3
chmod -R o+rX /opt/python
EOF

RUN --mount=type=cache,target=/root/.cache/pip <<EOF
set -e
python3 -m pip install playwright
python3 -m playwright install chromium --with-deps
chmod -R o+rX /opt/playwright
EOF

RUN npm install -g openclaw@2026.5.7

ARG CLOUD_CLIS
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked <<EOF
set -e
[ "$CLOUD_CLIS" = "true" ] || exit 0

apt-get update
apt-get install -y --no-install-recommends gnupg unzip

# AWS CLI
curl -fsSL "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o /tmp/awscliv2.zip
unzip -q /tmp/awscliv2.zip -d /tmp
/tmp/aws/install
rm -rf /tmp/awscliv2.zip /tmp/aws

# gcloud
curl -fsSL https://packages.cloud.google.com/apt/doc/apt-key.gpg \
    | gpg --dearmor -o /usr/share/keyrings/cloud.google.gpg
echo "deb [signed-by=/usr/share/keyrings/cloud.google.gpg] https://packages.cloud.google.com/apt cloud-sdk main" \
    > /etc/apt/sources.list.d/google-cloud-sdk.list
apt-get update
apt-get install -y --no-install-recommends google-cloud-cli

# Azure CLI
curl -fsSL https://packages.microsoft.com/keys/microsoft.asc \
    | gpg --dearmor -o /usr/share/keyrings/microsoft.gpg
echo "deb [arch=amd64 signed-by=/usr/share/keyrings/microsoft.gpg] https://packages.microsoft.com/repos/azure-cli/ bookworm main" \
    > /etc/apt/sources.list.d/azure-cli.list
apt-get update
apt-get install -y --no-install-recommends azure-cli

rm -rf /var/lib/apt/lists/*
EOF

USER node

ENTRYPOINT ["/usr/bin/tini", "--"]
