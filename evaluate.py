"""
evaluate.py - scores a PII tool on benchmark.jsonl.

Metrics (per marker and overall):
  Recall    = caught gold entities / total gold entities
              A gold entity is caught if a predicted span with the SAME label
              covers at least 50% of it.
  Precision = correct predictions / all predictions
              A prediction is correct if it overlaps a gold entity of the
              SAME label. Wrong-label and no-overlap predictions are errors.
  F1        = 2 * precision * recall / (precision + recall)

Overall scores are micro-averaged (all entities pooled together).

Run:
    python3 evaluate.py --tool scrubber            # regex + NER
    python3 evaluate.py --tool scrubber --no-ner   # regex only
    python3 evaluate.py --tool presidio            # baseline
    python3 evaluate.py --tool scrubber --quiet    # hide the error listing

Outputs:
    results_<tool>[_noner].json   metrics
    errors_<tool>[_noner].json    every miss and false positive, with context
"""
import argparse
import json
import time
from collections import defaultdict


def overlap(a_start, a_end, b_start, b_end):
    return max(0, min(a_end, b_end) - max(a_start, b_start))


def safe_div(a, b):
    return a / b if b else 0.0


def f1_score(p, r):
    return safe_div(2 * p * r, p + r)


def load_tool(name):
    if name == "scrubber":
        import scrubber
        return scrubber.find_spans
    if name == "presidio":
        import baseline_presidio
        return baseline_presidio.find_spans
    raise SystemExit(f"unknown tool: {name}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tool", default="scrubber", choices=["scrubber", "presidio"])
    ap.add_argument("--no-ner", action="store_true")
    ap.add_argument("--data", default="benchmark.jsonl")
    ap.add_argument("--quiet", action="store_true",
                    help="don't print the list of misses and false positives")
    args = ap.parse_args()

    find_spans = load_tool(args.tool)
    with open(args.data) as f:
        rows = [json.loads(line) for line in f]

    gold_n = defaultdict(int)       # gold entities per label
    hit_n = defaultdict(int)        # gold entities caught
    pred_n = defaultdict(int)       # predicted spans per label
    correct_n = defaultdict(int)    # predicted spans that are correct
    misses, false_pos = [], []
    times = []

    for row in rows:
        text, gold = row["text"], row["entities"]

        t0 = time.perf_counter()
        preds = find_spans(text, use_ner=not args.no_ner)
        times.append(time.perf_counter() - t0)

        # ---- recall side: was each gold entity caught?
        for g in gold:
            gold_n[g["type"]] += 1
            glen = g["end"] - g["start"]
            if any(p[2] == g["type"] and
                   overlap(p[0], p[1], g["start"], g["end"]) >= 0.5 * glen
                   for p in preds):
                hit_n[g["type"]] += 1
            else:
                near = [(text[p[0]:p[1]], p[2]) for p in preds
                        if overlap(p[0], p[1], g["start"], g["end"]) > 0]
                misses.append({"id": row["id"], "type": g["type"],
                               "gold": g["text"], "predicted_nearby": near,
                               "text": text})

        # ---- precision side: is each prediction correct?
        for p in preds:
            pred_n[p[2]] += 1
            same_label = any(g["type"] == p[2] and
                             overlap(p[0], p[1], g["start"], g["end"]) > 0
                             for g in gold)
            if same_label:
                correct_n[p[2]] += 1
            else:
                wrong_label = [g["type"] for g in gold
                               if overlap(p[0], p[1], g["start"], g["end"]) > 0]
                false_pos.append({"id": row["id"], "type": p[2],
                                  "span": text[p[0]:p[1]],
                                  "overlaps_gold_of_type": wrong_label,
                                  "text": text})

    # ---- report
    labels = sorted(set(gold_n) | set(pred_n))
    print(f"\nTool: {args.tool}{' (no NER)' if args.no_ner else ''}   "
          f"prompts: {len(rows)}")
    print(f"{'Marker':<10}{'Gold':>6}{'Caught':>8}{'Recall':>9}"
          f"{'Prec':>9}{'F1':>8}{'FalsePos':>10}")

    per_marker = {}
    for t in labels:
        rec = safe_div(hit_n[t], gold_n[t])
        prec = safe_div(correct_n[t], pred_n[t])
        f1 = f1_score(prec, rec)
        fp = pred_n[t] - correct_n[t]
        per_marker[t] = {"gold": gold_n[t], "caught": hit_n[t],
                         "recall": rec, "precision": prec, "f1": f1,
                         "false_positives": fp}
        print(f"{t:<10}{gold_n[t]:>6}{hit_n[t]:>8}{rec:>9.1%}"
              f"{prec:>9.1%}{f1:>8.3f}{fp:>10}")

    total_gold = sum(gold_n.values())
    total_hit = sum(hit_n.values())
    total_pred = sum(pred_n.values())
    total_correct = sum(correct_n.values())
    o_rec = safe_div(total_hit, total_gold)
    o_prec = safe_div(total_correct, total_pred)
    o_f1 = f1_score(o_prec, o_rec)
    avg_ms = 1000 * sum(times) / len(times)

    print(f"{'OVERALL':<10}{total_gold:>6}{total_hit:>8}{o_rec:>9.1%}"
          f"{o_prec:>9.1%}{o_f1:>8.3f}{total_pred - total_correct:>10}")
    print(f"Avg time/prompt: {avg_ms:.1f} ms")

    suffix = f"{args.tool}{'_noner' if args.no_ner else ''}"
    out = {"tool": args.tool, "no_ner": args.no_ner, "prompts": len(rows),
           "per_marker": per_marker,
           "overall": {"recall": o_rec, "precision": o_prec, "f1": o_f1,
                       "false_positives": total_pred - total_correct,
                       "misses": total_gold - total_hit},
           "avg_ms_per_prompt": avg_ms}
    with open(f"results_{suffix}.json", "w") as f:
        json.dump(out, f, indent=2)
    with open(f"errors_{suffix}.json", "w") as f:
        json.dump({"misses": misses, "false_positives": false_pos}, f, indent=2)
    print(f"Saved results_{suffix}.json and errors_{suffix}.json")

    if not args.quiet:
        print(f"\n--- FALSE POSITIVES ({len(false_pos)}) ---")
        for e in false_pos:
            note = (f"  (overlaps gold {e['overlaps_gold_of_type']})"
                    if e["overlaps_gold_of_type"] else "")
            print(f"[{e['id']}] {e['type']}: {e['span']!r}{note}\n"
                  f"      in {e['text'][:90]!r}")
        print(f"\n--- MISSES ({len(misses)}) ---")
        for e in misses:
            print(f"[{e['id']}] {e['type']}: {e['gold']!r}  "
                  f"nearby={e['predicted_nearby']}\n"
                  f"      in {e['text'][:90]!r}")


if __name__ == "__main__":
    main()