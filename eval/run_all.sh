#!/usr/bin/env bash
# eval/run_all.sh — Run extractor on all samples for a given version, then compare.
#
# Usage:
#   bash eval/run_all.sh v3                       # uses prompts/system_v3.txt
#   bash eval/run_all.sh v2 prompts/system_v2.txt # explicit prompt file
#
# Output goes to eval/outputs/<version>/<sample>.json
# Run from the project root.

set -e  # stop on any error

VERSION="${1:-v3}"
PROMPT="${2:-prompts/system_${VERSION}.txt}"
OUT_DIR="eval/outputs/${VERSION}"
DATE="2026-10-20"

echo "======================================================"
echo "  MeetMinutes eval — version: ${VERSION}"
echo "  Prompt file : ${PROMPT}"
echo "  Output dir  : ${OUT_DIR}"
echo "======================================================"

# Create the output directory if it doesn't exist yet.
mkdir -p "${OUT_DIR}"

# List of sample names (must match filenames in data/ and eval/outputs/)
SAMPLES=("english_01" "hindi_01" "hinglish_01")
TOTAL=${#SAMPLES[@]}

# ── Step 1: Run extractor on each sample ────────────────────────────────────
COUNT=0
for SAMPLE in "${SAMPLES[@]}"; do
    INPUT="data/${SAMPLE}.txt"
    OUTPUT="${OUT_DIR}/${SAMPLE}.json"
    COUNT=$((COUNT + 1))

    echo ""
    echo ">>> Extracting: ${SAMPLE}"
    # stderr (logs) go to the terminal; only JSON is written to the file.
    python -m services.extractor "${INPUT}" \
        --date "${DATE}" \
        --prompt "${PROMPT}" \
        > "${OUTPUT}"

    echo "    Saved → ${OUTPUT}"

    # Sleep between samples to stay under Groq's per-minute rate limit.
    if [ "${COUNT}" -lt "${TOTAL}" ]; then
        echo "    Sleeping 25s to avoid rate limits..."
        sleep 25
    fi
done

echo ""
echo "======================================================"
echo "  All extractions done. Running compare.py..."
echo "======================================================"

# ── Step 2: Compare each output against expected ─────────────────────────────
for SAMPLE in "${SAMPLES[@]}"; do
    python eval/compare.py \
        "${SAMPLE}" \
        "${OUT_DIR}/${SAMPLE}.json" \
        "data/${SAMPLE}.expected.json"
done
