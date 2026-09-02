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
      "https://x-access-token:$(cat /run/secrets/gh_token)@github.com/aai-labs/aai-cli.git" repo && \
    cargo install --path repo --root /out --locked

FROM nousresearch/hermes-agent:v2026.8.19
ARG APT_MIRROR

COPY --from=rust-build /out/bin/ /usr/local/bin/

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

# Upstream ships a newer libsqlite3 in /usr/local/lib than Debian's sqlite3
# executable was compiled against. Keep the upstream library available to
# Hermes, but make the CLI load Debian's matching library explicitly.
COPY --chmod=0755 sqlite3-wrapper /usr/local/bin/sqlite3

# Chromium and the playwright package are deliberately absent. service.py sets
# browser.cloud_provider=firecrawl for every agent, and firecrawl is a registered
# provider in this runtime (tools/browser_tool.py maps "firecrawl" ->
# FirecrawlProvider; agent/browser_registry.py documents the config key), so the
# browser tool routes to the shared service instead of a local browser.
# browser_tool.py imports playwright lazily -- only on the local-mode path -- so
# the package itself is unused here. Removing both drops ~1.24GB.

# gog (gogcli) — Google Workspace CLI used by the google_workspace integration. Pinned:
# the OAuth scopes the API requests mirror this version's service map, and auth-state
# formats have changed across releases.
ARG GOG_VERSION=0.37.0
RUN curl -fsSL "https://github.com/openclaw/gogcli/releases/download/v${GOG_VERSION}/gogcli_${GOG_VERSION}_linux_amd64.tar.gz" \
      | tar -xz -C /usr/local/bin ./gog && \
    chmod 755 /usr/local/bin/gog

# GOG_HOME lives under /home/hermes so gog's state is rebuilt from the credential on
# every boot rather than persisting. This directory has to be created explicitly: the
# hermes user's home is /opt/data (the PVC), and /home is root-owned and empty upstream,
# so the agent could not otherwise create anything here.
RUN mkdir -p /home/hermes && chown hermes:hermes /home/hermes

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
