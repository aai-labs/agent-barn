# Agent volume restore points use tar Jobs, not CSI VolumeSnapshots

Status: Accepted
Date: 2026-09-10
Origin: AF-292

Agent Barn captures an Agent's persistent volume by running a Kubernetes Job that archives it
onto a per-restore-point PVC, rather than using CSI `VolumeSnapshot` or PVC `dataSource`
cloning. `STORAGE_CLASS` defaults to `local-path` on k3s and k3d and supports neither, so a
snapshot-based design would not run on the primary or local development deployments; a file on
a plain PVC works on every storage class, at the cost of being slower than a native snapshot
would be on Ceph.

The archive is also not a byte-exact image, and that is deliberate rather than a limitation of
the mechanism: it excludes credential material and everything the runtime's start script
regenerates on boot. A snapshot could not make that distinction.

The seam for adding a snapshot backend later is the Job builder, which already takes its mounts
as a parameter.
