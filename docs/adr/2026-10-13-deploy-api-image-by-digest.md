# Deploy the API image by digest, move its tag afterwards

Status: Accepted
Date: 2026-10-13
Origin: Maintainer decision while de-duplicating CI and Deploy; registry storage constraint stated by the maintainer.

The API runs its Alembic migration in a Helm pre-upgrade hook, after the k3s deploy workflow has already pushed the moving `latest`/`latest-staging` tag with `pullPolicy: Always`. A failed hook therefore left new code behind the tag that any pod restart, CronJob or restore-point job would pull onto the old schema. The workflow now pushes the API image by digest, deploys that digest, and re-tags the moving tag only after the sync succeeds.

- **Per-deploy immutable tags (`sha-<commit>`) were rejected:** the maintainer cannot afford the registry storage, because tagged images are never garbage-collected and every deploy would add one. Digest references add no tag, and the re-tag copies a manifest without layers.
- **Restoring the previous tag on failure was rejected:** it leaves a window while the hook runs and depends on a step that cannot run if the runner dies.
- **Scope is the API image only:** the UI has no schema coupling, and the Hermes/OpenClaw base images carry `VERSION` tags consumed by API-created pods.

Consequences: `helm rollback` renders the previous revision's digest, which a registry that garbage-collects untagged manifests may no longer hold; today's rollback does not restore the previous image either, because the tag has already moved. Revisit if the registry gains a retention policy that would make per-deploy tags affordable.
