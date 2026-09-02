# syntax=docker/dockerfile:1

# Debian archive host. The default CDN resolves to a Fastly edge that is
# sometimes badly degraded (seen at ~30KB/s, stalling builds for over an hour).
# Override with a nearby full mirror to recover, e.g.:
#   docker build --build-arg APT_MIRROR=mirror.csclub.uwaterloo.ca ...
# It must carry BOTH /debian and /debian-security — many mirrors (ftp.us,
# cloudflaremirrors) serve only the former and break apt-get update.
ARG APT_MIRROR=deb.debian.org

FROM rust:1-slim-bookworm AS rust-build
ARG APT_MIRROR
# Handles both the classic sources.list and the deb822 .sources layout.
RUN set -eu; \
    if [ "$APT_MIRROR" != "deb.debian.org" ]; then \
      sed -i "s|deb\.debian\.org|${APT_MIRROR}|g" /etc/apt/sources.list 2>/dev/null || true; \
      sed -i "s|deb\.debian\.org|${APT_MIRROR}|g" /etc/apt/sources.list.d/*.sources 2>/dev/null || true; \
    fi
RUN apt-get update && apt-get install -y --no-install-recommends \
      git pkg-config libssl-dev ca-certificates && rm -rf /var/lib/apt/lists/*

WORKDIR /src
RUN --mount=type=secret,id=gh_token \
    git clone --depth 1 \
      "https://x-access-token:$(cat /run/secrets/gh_token)@github.com/aai-labs/aai-cli.git" repo && \
    cargo install --path repo --root /out --locked

FROM node:22-bookworm-slim
ARG APT_MIRROR
COPY --from=rust-build /out/bin/ /usr/local/bin/

ENV UV_PYTHON_INSTALL_DIR=/opt/python \
    PIP_BREAK_SYSTEM_PACKAGES=1

RUN set -eu; \
    if [ "$APT_MIRROR" != "deb.debian.org" ]; then \
      sed -i "s|deb\.debian\.org|${APT_MIRROR}|g" /etc/apt/sources.list 2>/dev/null || true; \
      sed -i "s|deb\.debian\.org|${APT_MIRROR}|g" /etc/apt/sources.list.d/*.sources 2>/dev/null || true; \
    fi

RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    apt-get update && \
    apt-get install -y --no-install-recommends git curl jq ripgrep ca-certificates tini

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

RUN uv python install 3.12 && \
    ln -sf "$(uv python find 3.12)" /usr/local/bin/python3 && \
    chmod -R o+rX /opt/python

# Chromium is deliberately absent. Web access goes through the shared firecrawl
# service, which every agent already resolves (service.py gates on fc_api_key and
# fc_base_url; helmfile wires FIRECRAWL_API_KEY into agentFirecrawlApiKey and
# values.yaml defaults agentFirecrawlBaseUrl to the ClusterIP), so a per-agent
# browser is redundant. It is also what makes the 1Gi memory limit viable: a
# gateway idles near 240MiB, but launching chromium and loading two real pages
# measured 573MiB in-pod, which a 1Gi cap cannot absorb alongside V8's heap.
# Removing it drops ~1.47GB from the image.

RUN npm install -g openclaw@2026.6.11

# gog (gogcli) — Google Workspace CLI used by the google_workspace integration. Pinned:
# the OAuth scopes the API requests mirror this version's service map, and auth-state
# formats have changed across releases.
#
# Downloaded to a file rather than piped into tar: /bin/sh has no pipefail, so in a
# pipeline the step's exit status is tar's, and a curl that dies mid-transfer could
# leave a truncated-but-extractable binary behind a passing build. Staging the
# tarball lets gzip's CRC reject a partial download before anything is unpacked.
# The retries cover github.com resetting the connection, which has failed CI builds
# on its own (release assets are served from a CDN that occasionally drops us).
ARG GOG_VERSION=0.37.0
RUN curl -fsSL --retry 5 --retry-all-errors --retry-delay 2 --connect-timeout 15 \
      -o /tmp/gogcli.tar.gz \
      "https://github.com/openclaw/gogcli/releases/download/v${GOG_VERSION}/gogcli_${GOG_VERSION}_linux_amd64.tar.gz" && \
    tar -xzf /tmp/gogcli.tar.gz -C /usr/local/bin ./gog && \
    rm -f /tmp/gogcli.tar.gz && \
    chmod 755 /usr/local/bin/gog

ARG CLOUD_CLIS=false
ENV CLOUD_CLIS=${CLOUD_CLIS}

RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    if [ "$CLOUD_CLIS" = "true" ]; then \
        apt-get update && \
        apt-get install -y --no-install-recommends gnupg unzip && \
        curl -fsSL --retry 5 --retry-all-errors --retry-delay 2 --connect-timeout 15 \
            "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o /tmp/awscliv2.zip && \
        unzip -q /tmp/awscliv2.zip -d /tmp && \
        /tmp/aws/install && \
        rm -rf /tmp/awscliv2.zip /tmp/aws && \
        curl -fsSL --retry 5 --retry-all-errors --retry-delay 2 --connect-timeout 15 \
            https://packages.cloud.google.com/apt/doc/apt-key.gpg \
            | gpg --dearmor -o /usr/share/keyrings/cloud.google.gpg && \
        echo "deb [signed-by=/usr/share/keyrings/cloud.google.gpg] https://packages.cloud.google.com/apt cloud-sdk main" \
            > /etc/apt/sources.list.d/google-cloud-sdk.list && \
        apt-get update && \
        apt-get install -y --no-install-recommends google-cloud-cli && \
        curl -fsSL --retry 5 --retry-all-errors --retry-delay 2 --connect-timeout 15 \
            https://packages.microsoft.com/keys/microsoft.asc \
            | gpg --dearmor -o /usr/share/keyrings/microsoft.gpg && \
        echo "deb [arch=amd64 signed-by=/usr/share/keyrings/microsoft.gpg] https://packages.microsoft.com/repos/azure-cli/ bookworm main" \
            > /etc/apt/sources.list.d/azure-cli.list && \
        apt-get update && \
        apt-get install -y --no-install-recommends azure-cli && \
        rm -rf /var/lib/apt/lists/*; \
    fi

RUN mkdir -p /opt/openclaw-preinstalled/npm && \
    npm install --prefix /opt/openclaw-preinstalled/npm @openclaw/msteams@2026.5.27 && \
    chown -R node:node /opt/openclaw-preinstalled

USER node

ENTRYPOINT ["/usr/bin/tini", "--"]
