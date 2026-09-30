# Personal API keys on user-authenticated platform routes

Status: Accepted
Date: 2026-09-30

## Context

The existing identity contract allowed Platform Administrator routes only from user sessions. The requested external API requires keys created by Users to reach the same user-authenticated endpoints, including platform routes when the User is a Platform Administrator. Platform authority remains separate from Organization Membership authority.

## Decision

A Personal API Key identifies its owning User and can exercise that User's current Platform Administrator privilege. Full-access keys can make permitted writes; read-only keys cannot. Service and runtime credentials do not gain platform authority. Organization routes still require real Membership.

## Consequences

A Platform Administrator must treat a full-access Personal API Key as a powerful credential. Revocation, optional expiry, and password-change invalidation apply. Platform privilege removal takes effect on the next authenticated request.

This supersedes the session-only requirement in [the Platform Oversight ADR](2026-07-30-platform-oversight-without-organization-access.md) while preserving its separation of Platform View and Organization View.
