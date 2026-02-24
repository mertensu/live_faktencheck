#!/usr/bin/env python3
"""
Exportiert Fact-Checks einer Episode aus der SQLite-Datenbank als Markdown-Dokument.

Verwendung:
    uv run python export_episode.py <episode_key> [--output datei.md] [--order Sprecher1,Sprecher2]

Beispiele:
    uv run python export_episode.py atalay-2026-02-09
    uv run python export_episode.py atalay-2026-02-09 --order "Philipp Amthor,Heidi Reichinnek"
    uv run python export_episode.py lanz-2026-02-06 --output lanz_export.md
"""

import argparse
import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

DB_PATH = Path(__file__).parent / "backend" / "data" / "factcheck.db"

CONSISTENCY_LABELS = {
    "hoch": "✅ Belegt",
    "mittel": "⚠️ Teilweise belegt",
    "niedrig": "❌ Nicht belegt / Irreführend",
    "unklar": "❓ Unklar / Nicht überprüfbar",
}


def load_fact_checks(episode_key: str) -> list[dict]:
    if not DB_PATH.exists():
        print(f"Fehler: Datenbank nicht gefunden unter {DB_PATH}", file=sys.stderr)
        sys.exit(1)

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.execute(
        "SELECT * FROM fact_checks WHERE episode_key = ? ORDER BY id",
        (episode_key,),
    )
    rows = cursor.fetchall()
    conn.close()

    if not rows:
        print(f"Keine Fact-Checks für Episode '{episode_key}' gefunden.", file=sys.stderr)
        sys.exit(1)

    return [
        {
            "id": row["id"],
            "sprecher": row["sprecher"],
            "behauptung": row["behauptung"],
            "consistency": row["consistency"],
            "begruendung": row["begruendung"],
            "quellen": json.loads(row["quellen"]),
            "timestamp": row["timestamp"],
            "episode_key": episode_key,
        }
        for row in rows
    ]


def export_as_json(episode_key: str, fact_checks: list[dict]) -> None:
    from config import get_speakers
    from backend.show_config import SHOW_CONFIG
    speakers = get_speakers(episode_key)

    output = {
        "speakers": speakers,
        "fact_checks": fact_checks,
    }

    data_dir = Path(__file__).parent / "frontend" / "public" / "data"
    data_dir.mkdir(parents=True, exist_ok=True)

    out_path = data_dir / f"{episode_key}.json"
    out_path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"✓ {len(fact_checks)} Fact-Checks exportiert → {out_path}")
    for speaker in speakers:
        count = sum(1 for fc in fact_checks if fc["sprecher"] == speaker)
        print(f"  {speaker}: {count} Claims")

    # Update shows.json with current published episodes
    shows = []
    for key, cfg in SHOW_CONFIG.items():
        if key == "test":
            continue
        shows.append({
            "key": key,
            "name": cfg.get("name", key),
            "description": cfg.get("description", ""),
            "info": cfg.get("info", ""),
            "type": cfg.get("type", "show"),
            "speakers": cfg.get("speakers", []),
            "episode_name": cfg.get("episode_name", ""),
            "publish": cfg.get("publish", False),
        })
    shows.sort(key=lambda x: x["key"], reverse=True)
    shows_path = data_dir / "shows.json"
    shows_path.write_text(json.dumps({"shows": shows}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"✓ shows.json aktualisiert → {shows_path}")


def group_by_speaker(fact_checks: list[dict], order: list[str] | None = None) -> dict[str, list]:
    """Gruppiert Fact-Checks nach Sprecher, optional in vorgegebener Reihenfolge."""
    grouped: dict[str, list] = {}
    for fc in fact_checks:
        speaker = fc["sprecher"]
        grouped.setdefault(speaker, []).append(fc)

    if order:
        # Nur die explizit genannten Sprecher, in der angegebenen Reihenfolge
        return {speaker: grouped[speaker] for speaker in order if speaker in grouped}

    return dict(sorted(grouped.items()))


def format_quellen(quellen: list) -> str:
    if not quellen:
        return ""
    lines = ["**Quellen:**"]
    for q in quellen:
        if isinstance(q, dict):
            title = q.get("title") or q.get("name") or ""
            url = q.get("url") or q.get("link") or ""
            if url and title:
                lines.append(f"- [{title}]({url})")
            elif url:
                lines.append(f"- {url}")
            elif title:
                lines.append(f"- {title}")
        else:
            lines.append(f"- {q}")
    return "\n".join(lines)


def render_markdown(episode_key: str, grouped: dict[str, list]) -> str:
    total = sum(len(v) for v in grouped.values())
    date_str = datetime.now().strftime("%d. %B %Y")

    lines = [
        f"# Fact-Check: {episode_key}",
        f"",
        f"Exportiert am {date_str} · {total} Fact-Checks",
        f"",
        "---",
        "",
    ]

    for speaker, checks in grouped.items():
        lines.append(f"## {speaker}")
        lines.append("")

        for i, fc in enumerate(checks, 1):
            label = CONSISTENCY_LABELS.get(fc["consistency"], fc["consistency"])
            lines.append(f"### {i}. {fc['behauptung']}")
            lines.append("")
            lines.append(f"**Bewertung:** {label}")
            lines.append("")
            lines.append(fc["begruendung"])
            lines.append("")

            quellen_text = format_quellen(fc["quellen"])
            if quellen_text:
                lines.append(quellen_text)
                lines.append("")

            lines.append("---")
            lines.append("")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Exportiere Fact-Checks einer Episode als Markdown oder JSON.")
    parser.add_argument("episode_key", help="Episode-Key, z.B. 'atalay-2026-02-09'")
    parser.add_argument("--output", "-o", help="Ausgabedatei (Standard: <episode_key>.md)")
    parser.add_argument(
        "--order",
        help="Sprecherreihenfolge, kommagetrennt: 'Philipp Amthor,Heidi Reichinnek'",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Als JSON exportieren nach frontend/public/data/<episode_key>.json (für Prod-Deployment)",
    )
    args = parser.parse_args()

    fact_checks = load_fact_checks(args.episode_key)

    if args.json:
        export_as_json(args.episode_key, fact_checks)
        return

    order = [s.strip() for s in args.order.split(",")] if args.order else None
    output_path = Path(args.output) if args.output else Path(f"{args.episode_key}.md")

    grouped = group_by_speaker(fact_checks, order)
    markdown = render_markdown(args.episode_key, grouped)

    output_path.write_text(markdown, encoding="utf-8")
    total = sum(len(v) for v in grouped.values())
    print(f"✓ {total} Fact-Checks exportiert → {output_path}")
    for speaker, checks in grouped.items():
        print(f"  {speaker}: {len(checks)} Claims")


if __name__ == "__main__":
    main()
