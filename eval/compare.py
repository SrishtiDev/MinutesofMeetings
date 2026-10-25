"""
eval/compare.py — Compare extractor output against expected action_items.

Usage:
    python eval/compare.py <sample_name> <output_json> [expected_json]

Matching logic:
  For each (expected, predicted) pair, compute:
    score = max(SequenceMatcher ratio, word-overlap Jaccard)
  Add +0.20 bonus if owners match (and are not null).
  Greedy one-to-one matching: best-score pair first, threshold 0.35.

Standard library only — no pip installs needed.
"""

import json
import re
import sys
from difflib import SequenceMatcher
from pathlib import Path

# ── constants ──────────────────────────────────────────────────────────────

MATCH_THRESHOLD = 0.35   # minimum score to consider two tasks the "same"
OWNER_BONUS     = 0.20   # score boost when owners match

# Common English stopwords to ignore when computing Jaccard overlap
STOPWORDS = {
    "a", "an", "the", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "by", "from", "is", "are", "was", "were", "be", "been",
    "has", "have", "had", "do", "does", "did", "will", "would", "shall",
    "should", "may", "might", "can", "could", "not", "no", "if", "then",
    "that", "this", "it", "its", "all", "each", "any", "both",
}

# ── helpers ────────────────────────────────────────────────────────────────

def _tokenize(text: str) -> set[str]:
    """Split text into lowercase words, remove stopwords."""
    words = set(re.findall(r"[a-z0-9]+", text.lower()))
    return words - STOPWORDS


def _seq_ratio(a: str, b: str) -> float:
    """SequenceMatcher similarity (0–1), case-insensitive."""
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


def _jaccard(a: str, b: str) -> float:
    """Word-overlap Jaccard index after removing stopwords."""
    wa = _tokenize(a)
    wb = _tokenize(b)
    if not wa or not wb:
        return 0.0
    return len(wa & wb) / len(wa | wb)


def _match_score(exp: dict, pred: dict) -> float:
    """
    Compute a combined match score between an expected and predicted item.
    score = max(SequenceMatcher, Jaccard) + owner bonus.
    """
    exp_task  = exp.get("task", "")
    pred_task = pred.get("task", "")

    # Text similarity: take the higher of the two methods
    text_score = max(_seq_ratio(exp_task, pred_task),
                     _jaccard(exp_task, pred_task))

    # Owner bonus: +0.20 if both owners are non-null and equal
    exp_owner  = exp.get("owner")
    pred_owner = pred.get("owner")
    if (exp_owner and pred_owner
            and exp_owner.lower() == pred_owner.lower()):
        text_score += OWNER_BONUS

    return text_score


def load_json(path: Path) -> dict:
    """Read a JSON file and return the parsed dict."""
    return json.loads(path.read_text(encoding="utf-8"))


def load_expected(path: Path) -> list[dict]:
    """
    Read expected.json and return its expected_action_items list.
    Keys starting with '_' in the top-level dict are metadata and ignored.
    """
    data = load_json(path)
    items = data.get("expected_action_items", [])
    return [i for i in items if not str(i.get("task", "")).startswith("_")]


def load_predicted(path: Path) -> list[dict]:
    """Read the extractor output and return its action_items list."""
    return load_json(path).get("action_items", [])


# ── matching ───────────────────────────────────────────────────────────────

def match_items(expected: list[dict], predicted: list[dict]):
    """
    Greedy one-to-one matching: build all (exp_i, pred_j, score) triples,
    sort by score descending, and greedily assign the best unused pair first.

    Returns (results_list, used_predicted_indices).
    """
    # Build a list of all possible pairings with their scores
    all_pairs = []
    for ei, exp in enumerate(expected):
        for pi, pred in enumerate(predicted):
            score = _match_score(exp, pred)
            all_pairs.append((score, ei, pi))

    # Sort descending by score → greedily pick best-first
    all_pairs.sort(reverse=True)

    used_exp  = set()
    used_pred = set()
    # Map: expected_index → (pred_index, score)
    assignments = {}

    for score, ei, pi in all_pairs:
        if ei in used_exp or pi in used_pred:
            continue
        if score < MATCH_THRESHOLD:
            continue
        assignments[ei] = (pi, round(score, 2))
        used_exp.add(ei)
        used_pred.add(pi)

    # Build result list in order of expected items
    results = []
    for ei, exp in enumerate(expected):
        exp_task = exp.get("task", "")

        if ei in assignments:
            pi, score = assignments[ei]
            pred = predicted[pi]

            # Owner correct?
            exp_owner  = exp.get("owner")
            pred_owner = pred.get("owner")
            owner_ok = (exp_owner is None and pred_owner is None) or (
                exp_owner is not None
                and pred_owner is not None
                and exp_owner.lower() == pred_owner.lower()
            )

            # Deadline correct?
            exp_dl  = exp.get("deadline")
            pred_dl = pred.get("deadline")
            deadline_ok = (exp_dl is None and pred_dl is None) or (exp_dl == pred_dl)

            results.append({
                "expected_task":    exp_task,
                "predicted_task":   pred.get("task", ""),
                "score":            score,
                "found":            True,
                "owner_correct":    owner_ok,
                "deadline_correct": deadline_ok,
                "exp_owner":        exp_owner,
                "pred_owner":       pred_owner,
                "exp_deadline":     exp_dl,
                "pred_deadline":    pred_dl,
            })
        else:
            # No match → missed (FN)
            # Show the best score we DID see for debugging
            best = 0.0
            for s, e, p in all_pairs:
                if e == ei and p not in used_pred:
                    best = max(best, s)
            results.append({
                "expected_task":    exp_task,
                "predicted_task":   None,
                "score":            round(best, 2),
                "found":            False,
                "owner_correct":    False,
                "deadline_correct": False,
                "exp_owner":        exp.get("owner"),
                "pred_owner":       None,
                "exp_deadline":     exp.get("deadline"),
                "pred_deadline":    None,
            })

    return results, used_pred


def find_extra_items(predicted: list[dict], used_predicted: set) -> list[str]:
    """Return predicted task texts not matched to any expected item (FP)."""
    return [
        predicted[i].get("task", "")
        for i in range(len(predicted))
        if i not in used_predicted
    ]


# ── report ──────────────────────────────────────────────────────────────────

def print_report(sample_name: str, results: list[dict], extras: list[str]) -> None:
    """Print a human-readable comparison report."""
    sep = "─" * 74

    print(f"\n{'═' * 74}")
    print(f"  EVAL REPORT: {sample_name}")
    print(f"{'═' * 74}")

    print(f"\n{'EXPECTED ITEM':<42}  SCORE  STATUS  OWNER  DEADLINE")
    print(sep)

    for r in results:
        task = r["expected_task"]
        short = (task[:40] + "…") if len(task) > 41 else task
        status = "FOUND " if r["found"] else "MISSED"
        owner_s  = "✓" if r["owner_correct"]    else "✗"
        dl_s     = "✓" if r["deadline_correct"] else "✗"
        score_s  = f"{r['score']:.2f}" if r["found"] else f"({r['score']:.2f})"
        print(f"  {short:<42}  {score_s:>5}  {status}  {owner_s}      {dl_s}")

        if r["found"] and not r["owner_correct"]:
            print(f"    owner:    expected={r['exp_owner']!r}  got={r['pred_owner']!r}")
        if r["found"] and not r["deadline_correct"]:
            print(f"    deadline: expected={r['exp_deadline']!r}  got={r['pred_deadline']!r}")
        if not r["found"]:
            print(f"    (best score {r['score']:.2f} — below threshold {MATCH_THRESHOLD})")

    # ── Extra (false-positive) items ──────────────────────────────────────
    print(f"\n{sep}")
    if extras:
        print("EXTRA items (predicted but not in expected):")
        for t in extras:
            short = (t[:68] + "…") if len(t) > 69 else t
            print(f"  + {short}")
    else:
        print("No extra items (no false positives).")

    # ── Aggregate metrics ─────────────────────────────────────────────────
    tp = sum(1 for r in results if r["found"])
    fn = len(results) - tp
    fp = len(extras)

    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall    = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1        = (2 * precision * recall / (precision + recall)
                 if (precision + recall) > 0 else 0.0)

    print(f"\n{sep}")
    print(f"  TP={tp}  FN={fn}  FP={fp}")
    print(f"  Precision : {precision:.2f}")
    print(f"  Recall    : {recall:.2f}")
    print(f"  F1        : {f1:.2f}")

    matched = [r for r in results if r["found"]]
    if matched:
        owner_acc = sum(1 for r in matched if r["owner_correct"])    / len(matched)
        dl_acc    = sum(1 for r in matched if r["deadline_correct"]) / len(matched)
        print(f"  Owner accuracy (matched) : {owner_acc:.0%}")
        print(f"  Deadline accuracy (matched): {dl_acc:.0%}")

    print(f"{'═' * 74}\n")


# ── entry point ─────────────────────────────────────────────────────────────

def main() -> None:
    args = sys.argv[1:]
    if len(args) < 2:
        print(
            "Usage: python eval/compare.py <sample_name> <output_json> [expected_json]\n"
            "Example: python eval/compare.py hinglish_01 "
            "eval/outputs/v3/hinglish_01.json",
            file=sys.stderr,
        )
        raise SystemExit(1)

    sample_name = args[0]
    output_path = Path(args[1])

    if len(args) >= 3:
        expected_path = Path(args[2])
    else:
        project_root  = Path(__file__).parent.parent
        expected_path = project_root / "data" / f"{sample_name}.expected.json"

    if not output_path.exists():
        print(f"Error: output file not found: {output_path}", file=sys.stderr)
        raise SystemExit(1)
    if not expected_path.exists():
        print(f"Error: expected file not found: {expected_path}", file=sys.stderr)
        raise SystemExit(1)

    expected  = load_expected(expected_path)
    predicted = load_predicted(output_path)

    results, used_predicted = match_items(expected, predicted)
    extras = find_extra_items(predicted, used_predicted)

    print_report(sample_name, results, extras)


if __name__ == "__main__":
    main()
