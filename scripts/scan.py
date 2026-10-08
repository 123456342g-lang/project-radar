from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.app.config import get_settings  # noqa: E402
from backend.app.db.database import init_db  # noqa: E402
from backend.app.pipeline import run_scan  # noqa: E402


def print_top(result) -> None:
    repo = result.repo
    print()
    print(f"=== {repo.get('full_name')} ===")
    if repo.get("description"):
        print(repo["description"])
    print(f"judge mode: {result.judge_mode}")
    if result.warnings:
        for warning in result.warnings:
            print(f"warning: {warning}")
    print(f"\nArtifacts scanned: {len(result.artifacts)}  Candidates: {len(result.candidates)}")
    print("\nTop problems worth doing:\n")
    for candidate in result.top:
        evidence = candidate["evidence"]
        judgment = candidate["judgment"]
        print(f"#{candidate['rank']}  {candidate['title']}")
        print(f"    type        : {candidate['problem_type']}")
        print(f"    why exists  : {candidate['why_exists']}")
        print(f"    unresolved  : {candidate['why_unresolved']}")
        print(f"    worth       : {candidate['why_worth']}")
        print(f"    minimal fix : {candidate['minimal_fix']}")
        print(
            f"    evidence    : {evidence['issues']} issues, {evidence['discussions']} discussions, "
            f"{evidence['pull_requests']} PRs, {evidence['independent_authors']} authors, "
            f"span {round(evidence['span_days'] / 30)}mo"
        )
        print(
            f"    jev         : same={judgment['same_problem']:.2f} "
            f"unresolved={judgment['unresolved']:.2f} "
            f"worth={judgment['worth_building']:.2f}/3 "
            f"mode={judgment['judge_mode']}"
        )
        print(f"    priority    : {candidate['priority']:.3f}")
        chain = candidate.get("evidence_chain") or []
        if chain:
            print("    chain       :")
            for link in chain[:8]:
                url = link.get("url") or ""
                print(f"      {link['date']}  {link['label']:<16} {link['title']}  {url}")
        print()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Scan a public GitHub repo and print the top problems worth solving."
    )
    parser.add_argument("repo", help="owner/name or a GitHub URL")
    parser.add_argument("--json", dest="json_path", help="also write the full result as JSON")
    parser.add_argument("--quiet", action="store_true", help="suppress progress output")
    args = parser.parse_args()

    repo = args.repo.strip().rstrip("/")
    for prefix in ("https://github.com/", "http://github.com/", "github.com/"):
        if repo.startswith(prefix):
            repo = repo[len(prefix):]
    repo = repo.split("?")[0].split("#")[0].strip("/").removesuffix(".git")

    settings = get_settings()
    init_db()

    def progress(stage: str, fraction: float) -> None:
        if not args.quiet:
            print(f"\r[{int(fraction * 100):3d}%] {stage}", end="", flush=True)

    result = run_scan(repo, progress_callback=progress, settings=settings)
    if not args.quiet:
        print()
    print_top(result)

    if args.json_path:
        payload = {
            "repo": result.repo,
            "judge_mode": result.judge_mode,
            "warnings": result.warnings,
            "top": result.top,
            "candidates": [
                {k: c[k] for k in ("id", "title", "problem_type", "priority", "judgment")}
                for c in result.candidates
            ],
        }
        Path(args.json_path).write_text(
            json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        print(f"wrote {args.json_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
