FROM debian:bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends openssh-server git ca-certificates \
    && rm -rf /var/lib/apt/lists/* /etc/ssh/ssh_host_* && mkdir -p /run/sshd
CMD ["/usr/sbin/sshd", "-D", "-e", "-f", "/fixture/sshd_config"]
