#!/bin/bash
# OMNIMIND LOCAL — Backup data and configs
set -e
BACKUP_DIR="./data/backups/$(date +%Y%m%d_%H%M%S)"
mkdir -p "$BACKUP_DIR"

echo "[BACKUP] Backing up configs..."
cp -r ./configs "$BACKUP_DIR/configs"

echo "[BACKUP] Backing up memory..."
cp -r ./data/memory "$BACKUP_DIR/memory" 2>/dev/null || true

echo "[BACKUP] Backing up learning data..."
cp -r ./data/learning "$BACKUP_DIR/learning" 2>/dev/null || true

echo "[BACKUP] Compressing..."
tar czf "$BACKUP_DIR.tar.gz" -C "$(dirname $BACKUP_DIR)" "$(basename $BACKUP_DIR)"
rm -rf "$BACKUP_DIR"

echo "[BACKUP] ✅ Saved to $BACKUP_DIR.tar.gz"
echo "[BACKUP] Size: $(du -sh "$BACKUP_DIR.tar.gz" | cut -f1)"
