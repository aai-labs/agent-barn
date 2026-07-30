# syntax=docker/dockerfile:1

# Debian archive host — see openclaw-base/Dockerfile for the rationale. Must
# carry both /debian and /debian-security. Override with:
#   docker build --build-arg APT_MIRROR=mirror.csclub.uwaterloo.ca ...
ARG APT_MIRROR=deb.debian.org

FROM rust:1-slim-bookworm AS rust-build
ARG APT_MIRROR
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
      "https://x-access-token:$(cat /run/secrets/gh_token)@github.com/aai-labs/agent-cli-tools.git" repo && \
    cargo install --path repo --root /out --locked

FROM nousresearch/hermes-agent:v2026.5.29.2
ARG APT_MIRROR

COPY --from=rust-build /out/bin/ /usr/local/bin/

ENV PLAYWRIGHT_BROWSERS_PATH=/opt/playwright

RUN set -eu; \
    if [ "$APT_MIRROR" != "deb.debian.org" ]; then \
      sed -i "s|deb\.debian\.org|${APT_MIRROR}|g" /etc/apt/sources.list 2>/dev/null || true; \
      sed -i "s|deb\.debian\.org|${APT_MIRROR}|g" /etc/apt/sources.list.d/*.sources 2>/dev/null || true; \
    fi

RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    apt-get update && \
    apt-get install -y --no-install-recommends \
        tini \
        jq \
        ripgrep \
        fd-find \
        poppler-utils \
        ffmpeg \
        imagemagick \
        sqlite3 \
        unzip \
        zip \
        ca-certificates \
    && ln -sf /usr/bin/fdfind /usr/local/bin/fd \
    && rm -rf /var/lib/apt/lists/*

RUN uv pip install --python /opt/hermes/.venv playwright && \
    /opt/hermes/.venv/bin/python -m playwright install chromium --with-deps && \
    chmod -R o+rX /opt/playwright

ARG CLOUD_CLIS=false
ENV CLOUD_CLIS=${CLOUD_CLIS}

RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    if [ "$CLOUD_CLIS" = "true" ]; then \
        apt-get update && \
        apt-get install -y --no-install-recommends gnupg unzip && \
        curl -fsSL "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o /tmp/awscliv2.zip && \
        unzip -q /tmp/awscliv2.zip -d /tmp && \
        /tmp/aws/install && \
        rm -rf /tmp/awscliv2.zip /tmp/aws && \
        curl -fsSL https://packages.cloud.google.com/apt/doc/apt-key.gpg \
            | gpg --dearmor -o /usr/share/keyrings/cloud.google.gpg && \
        echo "deb [signed-by=/usr/share/keyrings/cloud.google.gpg] https://packages.cloud.google.com/apt cloud-sdk main" \
            > /etc/apt/sources.list.d/google-cloud-sdk.list && \
        apt-get update && \
        apt-get install -y --no-install-recommends google-cloud-cli && \
        curl -fsSL https://packages.microsoft.com/keys/microsoft.asc \
            | gpg --dearmor -o /usr/share/keyrings/microsoft.gpg && \
        echo "deb [arch=amd64 signed-by=/usr/share/keyrings/microsoft.gpg] https://packages.microsoft.com/repos/azure-cli/ bookworm main" \
            > /etc/apt/sources.list.d/azure-cli.list && \
        apt-get update && \
        apt-get install -y --no-install-recommends azure-cli && \
        rm -rf /var/lib/apt/lists/*; \
    fi

USER hermes

ENTRYPOINT ["/usr/bin/tini", "--"]
