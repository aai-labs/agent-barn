RESTORE_POINT_RECONCILIATION_PENDING_GRACE_SECONDS = 60
RESTORE_POINT_RECONCILIATION_STALE_SECONDS = 900
RESTORE_POINT_RECONCILIATION_BATCH_SIZE = 100
RESTORE_POINT_RECONCILIATION_MAX_RUNTIME_SECONDS = 120
RESTORE_POINT_RECONCILIATION_MISSING_VOLUME_LIMIT = 50

RESTORE_POINT_POD_TERMINATION_TIMEOUT_SECONDS = 30
RESTORE_POINT_POD_TERMINATION_POLL_SECONDS = 1

RESTORE_POINT_ORPHAN_MIN_AGE_SECONDS = 1800
RESTORE_POINT_ORPHAN_DELETE_LIMIT = 20

# What a restore point's archive volume gets beyond the Agent's volume. A nearly full volume of
# incompressible data archives to more than its own size: tar adds a 512-byte header per entry
# and pads every file to 512 bytes, and gzip cannot shrink the data. The archive volume's own
# filesystem keeps space for inode tables (about 1.6% on ext4) and its journal (up to 128MiB
# below 128GiB). The capture runs as root, so ext4's reserved blocks stay usable.
RESTORE_POINT_ARCHIVE_MARGIN_PERCENT = 10
RESTORE_POINT_ARCHIVE_MARGIN_BYTES = 512 * 1024 * 1024
# Archive volumes are rounded up to this, so their sizes stay readable.
RESTORE_POINT_ARCHIVE_ROUNDING_BYTES = 256 * 1024 * 1024
