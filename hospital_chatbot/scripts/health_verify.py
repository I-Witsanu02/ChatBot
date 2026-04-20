#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any


def fetch_json(url: str, timeout: int = 10) -> dict[str, Any]:
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read().decode("utf-8")
        return json.loads(body)


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify chatbot runtime health endpoints")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--output", default="")
    args = parser.parse_args()

    base = args.base_url.rstrip("/")
    report: dict[str, Any] = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "base_url": base,
        "checks": {},
        "ok": False,
    }

    try:
        health = fetch_json(f"{base}/health")
        report["checks"]["health"] = health
        guide = fetch_json(f"{base}/guide")
        report["checks"]["guide"] = {
            "supported_topics_count": len(guide.get("supported_topics", [])),
            "has_welcome_message": bool(guide.get("welcome_message")),
        }
        admin = fetch_json(f"{base}/admin/status")
        report["checks"]["admin_status"] = {
            "record_count": admin.get("record_count", 0),
            "stale_summary": admin.get("manifest", {}).get("stale_summary", {}),
        }
        report["ok"] = bool(health.get("status") in {"ok", "index_missing"}) and report["checks"]["guide"]["has_welcome_message"]
    except urllib.error.HTTPError as exc:
        report["error"] = f"HTTP {exc.code}: {exc.reason}"
    except Exception as exc:
        report["error"] = str(exc)

    text = json.dumps(report, ensure_ascii=False, indent=2)
    print(text)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(text)
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
