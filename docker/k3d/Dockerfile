FROM alpine:3.21
RUN apk add --no-cache bash curl openssl docker-cli
# k3d — pinned so the cluster version is reproducible.
#
# Retried as a whole: install.sh itself fetches the release binary from
# GitHub's asset CDN (release-assets.githubusercontent.com), and that second
# request fails intermittently. Retrying only the outer curl would re-fetch the
# script but never the download that actually fails, so the entire pipeline is
# re-run instead. Verify k3d landed rather than trusting the loop's exit status:
# `curl | bash` reports bash's status, which masks a failed download.
RUN for attempt in 1 2 3 4 5; do \
      curl -fsSL --retry 3 --retry-delay 2 \
        https://raw.githubusercontent.com/k3d-io/k3d/main/install.sh \
        | TAG=v5.8.3 bash && command -v k3d >/dev/null 2>&1 && break; \
      echo "k3d install attempt ${attempt} failed; retrying in $((attempt * 3))s"; \
      sleep $((attempt * 3)); \
    done; \
    command -v k3d >/dev/null 2>&1 || { echo "k3d install failed after 5 attempts"; exit 1; } \
    && k3d version
