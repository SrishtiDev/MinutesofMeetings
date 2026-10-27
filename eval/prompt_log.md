# Evaluation log: MeetMinutes AI

Model: qwen/qwen3.8-27b (Groq free tier) | Test set: 3 samples (English, Hindi, Hinglish), 17 expected action items, 3 decisions

## Prompt v1 (baseline, first run, scored manually)
- Precision 100% (15/15), Recall 88% (15/17), FP = 0
- Owner accuracy: 15/15. Deadline accuracy: 14/15
- Missed: 2 unassigned tasks (Hindi: API documentation, Hinglish: README update)
- Date error: "end of next week" resolved to 10-27 instead of 10-30 (English)
- key_points repeated the decisions and action items
- Found while testing: 2 expected-file errors (Wednesday mapped to 10-22 instead of 10-21), fixed after checking the transcript

## Prompt v2 (+ unassigned-task rule, date reference block, key_points rule)
Raw compare.py output:
- English: TP 6, FN 0, FP 0, deadline 6/6
- Hindi: TP 6, FN 0, FP 0, deadline 5/6 (the 1 mismatch is Vikram's date, an expected-file error: transcript says Wednesday = 10-21)
- Hinglish: TP 4, FN 1, FP 1, deadline 3/4

Real picture after checking each case:
- Unassigned tasks: 0/2 found in v1, 2/2 found in v2 (main goal achieved)
- English "end of next week" error: fixed
- Hinglish MISS + EXTRA is one item matched wrongly by compare.py: "Fix the edge case in session handling and complete the user profile API" vs "Finalize user profile API and fix session handling edge case" (score 0.40, below threshold 0.5). Real TP=5, FN=0, FP=0. Tool issue, not a model issue.
- Combined (corrected): Precision 100%, Recall 100% (17/17)

## Known issues (to fix in v3)
- REGRESSION: Kabir's deadline "agle Friday tak" went from 10-23 (v1, correct) to 10-30 (v2, wrong). Cause: my date reference block labeled 10-30 as "next Friday", which contradicted the rule "next Friday = nearest upcoming Friday". Fix: relabel the block.
- compare.py matching is too strict for re-ordered wording. Use word-overlap + owner match.
- hindi_01.expected.json: Vikram's deadline must be 2026-10-21.

## Infra notes
- Groq free tier for this model: 1000 output tokens/minute. Running 3 samples back to back hit a 429 (per-minute limit). The error message said "daily limit", which was wrong. Fix: wait and retry, add a fallback model, add sleep in run_all.sh.
- The v1 prompt re-run after the code change also includes the date reference block, so it is no longer a pure v1. Pure v1 numbers = the first run above.