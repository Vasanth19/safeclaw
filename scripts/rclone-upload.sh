#!/bin/sh
# SafeClaw rclone upload wrapper
# Actor calls this via docker exec to push files to Google Drive in organized folders.
# Usage: docker exec safeclaw-rclone /bin/sh -c "/usr/local/bin/rclone copy /data/attachments/pending/\$FILE gdrive:\$DRIVE_PATH ..."
#
# This file lives on the host and is mounted into the rclone container.
# The actor triggers uploads by writing a request to the pending queue.

set -e

SRC="$1"
DEST="$2"

if [ -z "$SRC" ] || [ -z "$DEST" ]; then
  echo "Usage: $0 <local-path> <gdrive:folder/path>"
  exit 1
fi

echo "[rclone] uploading $SRC → $DEST"
rclone copy "$SRC" "$DEST" \
  --drive-root-folder-id "${RCLONE_DRIVE_FOLDER_ID}" \
  --log-level INFO \
  --stats 0 \
  --transfers 2 \
  --checkers 4

echo "[rclone] upload complete"
