# Share SSH through server-side signing

Status: Accepted
Date: 2026-11-14
Origin: Maintainer's SSH access design and implementation request

The maintainer requires ordinary SSH/Git tools inside Docker-based Agents while keeping private keys outside those workloads. We provide an SSH-agent-compatible local relay backed by a separate authenticated signing listener and OpenSSH's agent implementation. This preserves native tool behavior without distributing private keys or building a new SSH transport or signature implementation.

The maintainer considered an operation broker and a recording SSH gateway, and chose to defer both. Signing audit records authentication attempts; it cannot provide command-level enforcement or complete remote command recording. Restricted shared keys use OpenSSH host-key/user constraints, while administrators can explicitly choose unrestricted signing. Existing remote sessions outlive revocation. Revisit the connection boundary when command approvals, operation policy, or tamper-resistant remote command history become requirements.
