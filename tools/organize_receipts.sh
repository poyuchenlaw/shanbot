#!/bin/bash
# organize_receipts.sh
# Organizes receipt images into supplier subdirectories
# Filename format: YYMMDD_SupplierName_Amount_#ID.jpg
# Usage: bash organize_receipts.sh [receipt_dir]

set -euo pipefail

RECEIPT_DIR="${1:-/mnt/h/我的雲端硬碟/小魚資料/團膳公司資料/2026/03月/收據憑證}"

if [ ! -d "$RECEIPT_DIR" ]; then
    echo "ERROR: Directory not found: $RECEIPT_DIR"
    exit 1
fi

echo "========================================"
echo "收據憑證整理工具 (Receipt Organizer)"
echo "目錄: $RECEIPT_DIR"
echo "時間: $(date '+%Y-%m-%d %H:%M:%S')"
echo "========================================"
echo ""

# Counters
moved=0
skipped=0
created=0

# Step 1: Delete empty tmp files
echo "--- 刪除空白暫存檔 ---"
for tmpfile in "$RECEIPT_DIR"/unknown_tmp*.jpg; do
    [ -f "$tmpfile" ] || continue
    size=$(stat -c%s "$tmpfile" 2>/dev/null || stat -f%z "$tmpfile" 2>/dev/null)
    if [ "$size" -lt 1000 ]; then
        rm "$tmpfile"
        echo "  [刪除] $(basename "$tmpfile") (${size} bytes)"
    fi
done
echo ""

# Step 2: Process named receipt files (26*.jpg and 25*.jpg patterns)
echo "--- 整理收據檔案 ---"
for f in "$RECEIPT_DIR"/26*.jpg "$RECEIPT_DIR"/25*.jpg; do
    [ -f "$f" ] || continue
    filename=$(basename "$f")

    # Extract supplier name (second field, separated by _)
    supplier=$(echo "$filename" | cut -d'_' -f2)

    # Skip unknown files
    if [ "$supplier" = "unknown" ]; then
        echo "  [跳過] $filename (unknown supplier)"
        skipped=$((skipped + 1))
        continue
    fi

    # Target directory = supplier name
    target_dir="$RECEIPT_DIR/$supplier"

    # Create directory if it doesn't exist
    if [ ! -d "$target_dir" ]; then
        mkdir -p "$target_dir"
        echo "  [新建] 資料夾: $supplier/"
        created=$((created + 1))
    fi

    # Move the file
    mv "$f" "$target_dir/"
    echo "  [移動] $filename → $supplier/"
    moved=$((moved + 1))
done

echo ""
echo "========================================"
echo "完成！"
echo "  移動: $moved 個檔案"
echo "  跳過: $skipped 個 (unknown)"
echo "  新建: $created 個資料夾"
echo "========================================"
