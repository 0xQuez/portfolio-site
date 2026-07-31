#!/usr/bin/env python3
"""Build portfolio stats.json from Hermes pipeline handoffs and kanban.

stdlib-only; intended to run from cron on the portfolio owner's Mac.
"""
from __future__ import annotations

import datetime as dt
import json
import re
import subprocess
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

OUTPUT_DIR = Path.home() / ".hermes" / "claude-outputs"
REPO_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_FILE = REPO_ROOT / "stats.json"

PIPELINE_PREFIXES = {
    "content_engine": ("content-engine-",),
    "outreach": ("weekly-outreach-",),
    "rewards": ("beta-rewards-", "product-rewards-"),
    "analytics": ("discord-analysis-",),
}
DATE_RE = re.compile(r"(20\d{2}-\d{2}-\d{2})")
NUMBER_RE = re.compile(r"(?<![\w.])([0-9][0-9,]*(?:\.\d+)?)(?![\w.])")


def files_for(prefixes: Iterable[str]) -> List[Path]:
    prefix_tuple = tuple(prefixes)
    return sorted(
        (p for p in OUTPUT_DIR.glob("*.md") if p.name.startswith(prefix_tuple)),
        key=lambda p: (date_from_name(p) or "", p.name),
    )


def date_from_name(path: Path) -> Optional[str]:
    match = DATE_RE.search(path.name)
    return match.group(1) if match else None


def field(text: str, name: str) -> str:
    match = re.search(r"^\s*-\s*\*\*" + re.escape(name) + r"\s*:\s*\*\*\s*(.*?)\s*$", text, re.M | re.I)
    return match.group(1).strip() if match else ""


def is_complete(text: str) -> bool:
    status = field(text, "Status").lower()
    return "complete" in status and "partial" not in status


def numbers(text: str) -> List[float]:
    return [float(n.replace(",", "")) for n in NUMBER_RE.findall(text)]


def integer(value: float) -> int:
    return int(value) if value.is_integer() else int(round(value))


def first_number(text: str, pattern: str) -> Optional[int]:
    match = re.search(pattern, text, re.I)
    if not match:
        return None
    return integer(float(match.group(1).replace(",", "")))


def parse_csv_rows(text: str) -> Optional[int]:
    # Handoffs report transitions such as "521 to 531 rows".
    match = re.search(r"(?:to|after:)\s*([0-9][0-9,]*)\s+rows?", text, re.I)
    return integer(float(match.group(1).replace(",", ""))) if match else None


def build_stats() -> Tuple[dict, dict]:
    content_files = files_for(PIPELINE_PREFIXES["content_engine"])
    outreach_files = files_for(PIPELINE_PREFIXES["outreach"])
    reward_files = files_for(PIPELINE_PREFIXES["rewards"])
    analytics_files = files_for(PIPELINE_PREFIXES["analytics"])

    content_text = [(p, p.read_text(encoding="utf-8", errors="replace")) for p in content_files]
    outreach_text = [(p, p.read_text(encoding="utf-8", errors="replace")) for p in outreach_files]
    reward_text = [(p, p.read_text(encoding="utf-8", errors="replace")) for p in reward_files]
    analytics_text = [(p, p.read_text(encoding="utf-8", errors="replace")) for p in analytics_files]

    content_success = sum(is_complete(t) for _, t in content_text)
    content_topics = sum(bool(re.search(r"Topic chosen:", t, re.I)) for _, t in content_text)
    content_sources = 0
    for _, text in content_text:
        source_match = re.search(r"(?:Three|3)\s+(?:verified\s+)?primary sources?", text, re.I)
        content_sources += 3 if source_match else len(re.findall(r"\bverified primary sources?\b", text, re.I))
    # Content handoffs contain no engagement figures; zero is a measured total.

    targets = 0
    drafts = 0
    replies = 0
    csv_rows = None
    for _, text in outreach_text:
        # "N new targets" is the authoritative per-run delta.
        n = first_number(text, r"([0-9][0-9,]*)\s+new targets?")
        if n is not None:
            targets += n
        n = first_number(text, r"([0-9][0-9,]*)\s+Gmail drafts?")
        if n is not None:
            drafts += n
        # Count explicit reply events, not every occurrence of the word reply.
        replies += len(re.findall(r"\b(?:replied|replies|reply)\b", field(text, "Engagement / Results"), re.I))
        row = parse_csv_rows(text)
        if row is not None:
            csv_rows = row
    if csv_rows is None:
        csv_rows = 0

    reward_success_dates = [date for p, t in reward_text if is_complete(t) for date in [date_from_name(p)] if date]
    reward_last_success = max(reward_success_dates) if reward_success_dates else ""
    reward_status = "ok" if reward_text and all(is_complete(t) for _, t in reward_text) else "degraded"

    latest_analytics = analytics_text[-1][1] if analytics_text else ""
    members = re.findall(r"(?:Main:|Gate:)\s*([0-9][0-9,]*)\s*[→>-]\s*([0-9][0-9,]*)", latest_analytics)
    members_total = sum(integer(float(end.replace(",", ""))) for _, end in members)

    kanban = parse_kanban()
    generated = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    stats = {
        "generated_at": generated,
        "pipelines": {
            "content_engine": {
                "runs": len(content_text), "briefs_published": content_success,
                "topics_covered": content_topics, "sources_verified": content_sources,
                "engagement_total": 0,
            },
            "rewards": {"cycles_run": len(reward_text), "status": reward_status, "last_success": reward_last_success},
            "outreach": {"targets_researched": targets, "drafts_created": drafts, "replies_received": replies, "csv_rows": csv_rows},
            "analytics": {"servers_tracked": 2, "members_total": members_total, "weekly_reports": len(analytics_text), "last_run": date_from_name(analytics_files[-1]) if analytics_files else ""},
            "support": {"inquiries_resolved": 1000, "source": "manual"},
            "kanban": kanban,
        },
        "case_studies": [
            {"id": "support", "stat": "1,000+", "unit": "inquiries resolved", "context": "solo Zendesk ops, no dedicated team"},
            {"id": "pipelines", "stat": "6+", "unit": "recurring automation pipelines", "context": "replaced weekly manual ops"},
            {"id": "growth", "stat": "25,000+", "unit": "Discord members", "context": "375go app launch: 250K+ downloads"},
            {"id": "content", "stat": str(content_success), "unit": "weekly source-verified briefs", "context": "12-week Physical AI curriculum"},
            {"id": "radio", "stat": "500", "unit": "avg live listeners", "context": "2 seasons, X Spaces"},
            {"id": "nametag", "stat": "$1.1M+", "unit": "product sold", "context": "0 → 60,000+ users, 6 products shipped"},
            {"id": "ibm", "stat": "$2.5M", "unit": "deals closed", "context": "$1.4M above quota, Fortune 20"},
        ],
    }
    sources = {"content": [p.name for p, _ in content_text], "outreach": [p.name for p, _ in outreach_text], "rewards": [p.name for p, _ in reward_text], "analytics": [p.name for p, _ in analytics_text], "kanban": "hermes kanban list 2>&1", "support": "manual per build spec"}
    return stats, sources


def parse_kanban() -> Dict[str, int]:
    try:
        result = subprocess.run(["hermes", "kanban", "list"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, check=False, timeout=30)
        text = result.stdout
    except (OSError, subprocess.SubprocessError):
        text = ""
    counts = {"completed": 0, "blocked": 0, "in_progress": 0}
    line_re = re.compile(r"\bt_[0-9a-f]+\s+(done|blocked|in_progress|in-progress|running)\b", re.I)
    for line in text.splitlines():
        match = line_re.search(line)
        if not match:
            continue
        state = match.group(1).lower().replace("-", "_")
        if state == "done":
            counts["completed"] += 1
        elif state == "blocked":
            counts["blocked"] += 1
        elif state in ("in_progress", "running"):
            counts["in_progress"] += 1
    return counts


def main() -> None:
    stats, sources = build_stats()
    OUTPUT_FILE.write_text(json.dumps(stats, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(stats, indent=2))
    print("\nSources:\n" + json.dumps(sources, indent=2))


if __name__ == "__main__":
    main()
