#!/usr/bin/env bash
# Quick evaluation basket — runs the analyser test suite against a focused
# 3-case basket spanning the three common scan shapes:
#   - direct-answer (CT head cerebellar haemorrhage)
#   - focused with branching aetiology (CT thorax lung nodule)
#   - broad-coverage multi-finding (CT TAP acute abdomen + GDA bleed)
#
# Default: both production analysers (GLM, Haiku) fired against GLM generator.
# Runs ~2 minutes. Use between non-trivial prompt edits to catch regressions.
#
# Usage:
#   ./scripts/quick-eval.sh                              # default basket
#   ./scripts/quick-eval.sh --generators zai-glm-4.7 claude-sonnet-4-6   # with Sonnet reference
#   ./scripts/quick-eval.sh --variants claude-haiku-4-5-20251001          # Haiku only
#
# Output: backend/test_output/<timestamp>/summary.md (+ per-case JSON + metrics.csv)
# Prompt versions pinned at top of summary.md for regression traceability.

set -euo pipefail

cd "$(dirname "$0")/.."

poetry run python -m rapid_reports_ai.scripts.analyser_test_suite \
    --cases-file test_cases/quick_eval.json \
    "$@"
