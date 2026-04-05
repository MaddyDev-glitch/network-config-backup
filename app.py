#!/usr/bin/env python3
import hashlib
import json
import os
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from flask import Flask, abort, jsonify, render_template, request


BASE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = BASE_DIR / "output"
DB_PATH = BASE_DIR / "webui.db"

SSH_HEADER_RE = re.compile(r"^(# .*\n)+\n?", re.MULTILINE)
NETCONF_COMMENT_RE = re.compile(r"^<!--.*?-->\s*", re.MULTILINE)
MESSAGE_ID_RE = re.compile(r'message-id="[^"]+"')


@dataclass
class Snapshot:
    device: str
    path: Path
    collected_at: datetime
    raw_content: str
    normalized_content: str
    size: int


def create_app() -> Flask:
    app = Flask(__name__)
    init_db()

    @app.route("/")
    def index() -> str:
        return render_template("index.html")

    @app.get("/api/devices")
    def devices() -> Any:
        device_entries = []
        changes_by_device = collect_changes()
        for device, changes in changes_by_device.items():
            snapshots = read_snapshots(OUTPUT_DIR / device)
            latest_snapshot = snapshots[-1] if snapshots else None
            latest_change = changes[-1] if changes else None
            device_entries.append(
                {
                    "name": device,
                    "change_count": len(changes),
                    "snapshot_count": len(snapshots),
                    "last_seen": latest_snapshot.collected_at.isoformat(sep=" ", timespec="seconds") if latest_snapshot else None,
                    "latest_summary": latest_change["summary"] if latest_change else "No snapshots",
                }
            )
        return jsonify({"devices": sorted(device_entries, key=lambda item: item["name"].lower())})

    @app.get("/api/devices/<device_name>/changes")
    def device_changes(device_name: str) -> Any:
        changes = collect_changes().get(device_name)
        if changes is None:
            abort(404, description="Device not found")
        return jsonify({"device": device_name, "changes": changes})

    @app.get("/api/changes/<change_id>")
    def change_detail(change_id: str) -> Any:
        change = find_change(change_id)
        if not change:
            abort(404, description="Change not found")
        return jsonify(change)

    @app.post("/api/changes/<change_id>/note")
    def save_note(change_id: str) -> Any:
        change = find_change(change_id)
        if not change:
            abort(404, description="Change not found")
        payload = request.get_json(silent=True) or {}
        note = (payload.get("note") or "").strip()
        upsert_note(
            change_id=change_id,
            device_name=change["device"],
            previous_path=change["previous"]["path"] if change["previous"] else None,
            current_path=change["current"]["path"],
            note=note,
        )
        return jsonify({"ok": True, "note": note, "updated_at": get_note(change_id).get("updated_at")})

    return app


def init_db() -> None:
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS change_notes (
                change_id TEXT PRIMARY KEY,
                device_name TEXT NOT NULL,
                previous_path TEXT,
                current_path TEXT NOT NULL,
                note TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL
            )
            """
        )


def upsert_note(change_id: str, device_name: str, previous_path: str | None, current_path: str, note: str) -> None:
    updated_at = datetime.now().isoformat(timespec="seconds")
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            INSERT INTO change_notes (change_id, device_name, previous_path, current_path, note, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(change_id) DO UPDATE SET
                note = excluded.note,
                updated_at = excluded.updated_at
            """,
            (change_id, device_name, previous_path, current_path, note, updated_at),
        )


def get_note(change_id: str) -> dict[str, str]:
    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute(
            "SELECT note, updated_at FROM change_notes WHERE change_id = ?",
            (change_id,),
        ).fetchone()
    if not row:
        return {"note": "", "updated_at": ""}
    return {"note": row[0], "updated_at": row[1]}


def read_snapshots(device_dir: Path) -> list[Snapshot]:
    snapshots = []
    for path in sorted(p for p in device_dir.iterdir() if p.is_file()):
        raw_content = path.read_text(encoding="utf-8", errors="ignore")
        normalized = normalize_snapshot(path, raw_content)
        snapshots.append(
            Snapshot(
                device=device_dir.name,
                path=path,
                collected_at=parse_snapshot_time(path, raw_content),
                raw_content=raw_content,
                normalized_content=normalized,
                size=path.stat().st_size,
            )
        )
    return sorted(snapshots, key=lambda item: item.collected_at)


def normalize_snapshot(path: Path, content: str) -> str:
    if path.suffix == ".txt":
        body = SSH_HEADER_RE.sub("", content, count=1)
        return body.strip()

    if path.suffix == ".xml":
        body = NETCONF_COMMENT_RE.sub("", content)
        body = MESSAGE_ID_RE.sub('message-id="normalized"', body)
        return body.strip()

    return content.strip()


def parse_snapshot_time(path: Path, content: str) -> datetime:
    if match := re.search(r"# Collected: ([^\n]+)", content):
        return datetime.strptime(match.group(1).strip(), "%Y-%m-%d %H:%M:%S")

    if match := re.search(r"<!-- Collected: ([^>]+) -->", content):
        return datetime.strptime(match.group(1).strip(), "%Y-%m-%d %H:%M:%S")

    if match := re.search(r"_(\d{8}_\d{6})", path.stem):
        return datetime.strptime(match.group(1), "%d%m%Y_%H%M%S")

    if match := re.search(r"_(\d{10})$", path.stem):
        return datetime.fromtimestamp(int(match.group(1)))

    return datetime.fromtimestamp(path.stat().st_mtime)


def collect_changes() -> dict[str, list[dict[str, Any]]]:
    changes_by_device: dict[str, list[dict[str, Any]]] = {}
    if not OUTPUT_DIR.exists():
        return changes_by_device

    for device_dir in sorted(p for p in OUTPUT_DIR.iterdir() if p.is_dir()):
        snapshots = read_snapshots(device_dir)
        device_changes = []
        previous_snapshot: Snapshot | None = None

        for snapshot in snapshots:
            if previous_snapshot and previous_snapshot.normalized_content == snapshot.normalized_content:
                previous_snapshot = snapshot
                continue

            change_id = make_change_id(device_dir.name, previous_snapshot, snapshot)
            note = get_note(change_id)
            line_stats = compute_line_stats(
                previous_snapshot.normalized_content if previous_snapshot else "",
                snapshot.normalized_content,
            )
            device_changes.append(
                {
                    "id": change_id,
                    "device": device_dir.name,
                    "summary": summarize_change(previous_snapshot, snapshot, line_stats),
                    "type": "initial" if previous_snapshot is None else "change",
                    "current": snapshot_payload(snapshot),
                    "previous": snapshot_payload(previous_snapshot) if previous_snapshot else None,
                    "note": note["note"],
                    "note_updated_at": note["updated_at"],
                    "stats": line_stats,
                }
            )
            previous_snapshot = snapshot

        changes_by_device[device_dir.name] = device_changes

    return changes_by_device


def find_change(change_id: str) -> dict[str, Any] | None:
    for changes in collect_changes().values():
        for change in changes:
            if change["id"] == change_id:
                previous_text = change["previous"]["normalized_content"] if change["previous"] else ""
                current_text = change["current"]["normalized_content"]
                change["diff_rows"] = build_side_by_side_diff(previous_text, current_text)
                return change
    return None


def snapshot_payload(snapshot: Snapshot | None) -> dict[str, Any] | None:
    if snapshot is None:
        return None
    return {
        "path": str(snapshot.path.relative_to(BASE_DIR)),
        "filename": snapshot.path.name,
        "collected_at": snapshot.collected_at.isoformat(sep=" ", timespec="seconds"),
        "size": snapshot.size,
        "raw_content": snapshot.raw_content,
        "normalized_content": snapshot.normalized_content,
    }


def make_change_id(device: str, previous_snapshot: Snapshot | None, current_snapshot: Snapshot) -> str:
    seed = {
        "device": device,
        "previous": previous_snapshot.path.name if previous_snapshot else None,
        "current": current_snapshot.path.name,
    }
    return hashlib.sha1(json.dumps(seed, sort_keys=True).encode("utf-8")).hexdigest()[:16]


def summarize_change(previous_snapshot: Snapshot | None, current_snapshot: Snapshot, line_stats: dict[str, int]) -> str:
    if previous_snapshot is None:
        return "Initial snapshot"

    parts = []
    if line_stats["added"]:
        parts.append(f"+{line_stats['added']}")
    if line_stats["removed"]:
        parts.append(f"-{line_stats['removed']}")
    if line_stats["changed"]:
        parts.append(f"~{line_stats['changed']}")
    if not parts:
        parts.append("metadata only")
    return " ".join(parts)


def compute_line_stats(previous_text: str, current_text: str) -> dict[str, int]:
    matcher = SequenceMatcher(None, previous_text.splitlines(), current_text.splitlines())
    added = removed = changed = 0
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "insert":
            added += j2 - j1
        elif tag == "delete":
            removed += i2 - i1
        elif tag == "replace":
            changed += max(i2 - i1, j2 - j1)
    return {"added": added, "removed": removed, "changed": changed}


def build_side_by_side_diff(previous_text: str, current_text: str) -> list[dict[str, Any]]:
    previous_lines = previous_text.splitlines()
    current_lines = current_text.splitlines()
    matcher = SequenceMatcher(None, previous_lines, current_lines)
    rows = []

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            for old_idx, new_idx in zip(range(i1, i2), range(j1, j2)):
                rows.append(diff_row("equal", old_idx + 1, previous_lines[old_idx], new_idx + 1, current_lines[new_idx]))
            continue

        left_chunk = previous_lines[i1:i2]
        right_chunk = current_lines[j1:j2]
        length = max(len(left_chunk), len(right_chunk))

        for offset in range(length):
            left_line = left_chunk[offset] if offset < len(left_chunk) else ""
            right_line = right_chunk[offset] if offset < len(right_chunk) else ""
            left_no = i1 + offset + 1 if offset < len(left_chunk) else None
            right_no = j1 + offset + 1 if offset < len(right_chunk) else None
            rows.append(diff_row(tag, left_no, left_line, right_no, right_line))

    return rows


def diff_row(kind: str, left_no: int | None, left_text: str, right_no: int | None, right_text: str) -> dict[str, Any]:
    return {
        "kind": kind,
        "left": {"line_no": left_no, "text": left_text},
        "right": {"line_no": right_no, "text": right_text},
    }


app = create_app()


if __name__ == "__main__":
    host = os.environ.get("WEBUI_HOST", "192.168.1.100")
    port = int(os.environ.get("WEBUI_PORT", "8080"))
    app.run(host=host, port=port, debug=False)
