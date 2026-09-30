FROM alpine:3.21
RUN apk add --no-cache bash curl openssl docker-cli
# k3d — pinned so the cluster version is reproducible
RUN curl -fsSL https://raw.githubusercontent.com/k3d-io/k3d/main/install.sh \
    | TAG=v5.8.3 bash
