#!/usr/bin/env bash
set -euo pipefail
umask 077

cd "$(dirname "$0")/.."
if [ "$#" -gt 1 ]; then
  echo "Usage: bash scripts/backup_local_postgres.sh [upload-directory]" >&2
  exit 2
fi
upload_dir="${1:-uploads}"
if [ "$#" -eq 1 ] && [ ! -d "$upload_dir" ]; then
  echo "Upload directory does not exist: $upload_dir" >&2
  exit 2
fi
backup_root="${BACKUP_ROOT:-backups}"
mkdir -p "$backup_root"
backup_root="$(cd "$backup_root" && pwd -P)"
if [ -d "$upload_dir" ]; then
  upload_dir="$(cd "$upload_dir" && pwd -P)"
  case "$backup_root/" in
    "$upload_dir/"*) echo "BACKUP_ROOT must be outside the upload directory." >&2; exit 2 ;;
  esac
fi
backup_dir="$(mktemp -d "$backup_root/.partial-course-agent-$(date +%Y%m%d-%H%M%S).XXXXXX")"
trap 'echo "Backup incomplete: $backup_dir" >&2' EXIT

docker compose exec -T db pg_dump -U course_agent -d course_agent --format=custom \
  > "$backup_dir/db.dump"
docker compose exec -T db pg_restore --list < "$backup_dir/db.dump" > /dev/null
if [ -d "$upload_dir" ]; then
  tar -czf "$backup_dir/uploads.tar.gz" -C "$upload_dir" .
fi

name="${backup_dir##*/}"
complete_dir="$backup_root/${name#.partial-}"
mv "$backup_dir" "$complete_dir"
trap - EXIT
printf 'Local PostgreSQL backup: %s\n' "$complete_dir"
