#!/usr/bin/env python3
"""DANP 드랍 트래커 — Slack 일일 알림"""

import os
import re
import json
import requests
from datetime import datetime, timezone, timedelta
from collections import defaultdict

FIREBASE_URL = (
    "https://danp-dashboard-default-rtdb.asia-southeast1.firebasedatabase.app/.json"
)
DASHBOARD_URL = "https://danp0acount-blip.github.io/danp-dashboard/"

_raw = os.environ.get("SLACK_WEBHOOK_URL", "")
_match = re.search(r"https://hooks\.slack\.com/services/[^\s'\"]+", _raw)
if not _match:
    raise SystemExit("SLACK_WEBHOOK_URL에 유효한 Slack webhook URL이 없습니다.")
SLACK_WEBHOOK_URL = _match.group(0)

try:
    USER_IDS = json.loads(os.environ.get("USER_IDS_JSON", "{}"))
except json.JSONDecodeError:
    USER_IDS = {}

KST = timezone(timedelta(hours=9))
TODAY = datetime.now(KST).date()
URGENT_THRESHOLD = 3


def mention(names):
    if isinstance(names, str):
        names = [names]
    names = [n for n in names if n and n.strip()]
    parts = []
    for n in names:
        uid = USER_IDS.get(n)
        parts.append(f"<@{uid}>" if uid else f"`@{n}`")
    return " ".join(parts) if parts else "`담당자 미지정`"


def parse_date(s):
    if not s or not str(s).strip():
        return None
    try:
        return datetime.strptime(str(s).strip(), "%Y-%m-%d").date()
    except ValueError:
        return None


def collect():
    r = requests.get(FIREBASE_URL, timeout=30)
    r.raise_for_status()
    data = r.json()["danp"]

    items = []
    for drop in data["drops"]:
        dname = drop["name"]
        for p in drop.get("plans", []) or []:
            if p.get("status") == "제출완료":
                continue
            due = parse_date(p.get("dl"))
            if not due:
                continue
            items.append({"name": p["nm"], "due": due, "who": p.get("who") or [], "drop": dname})
        for t in drop.get("tasks", []) or []:
            if t.get("s") == "완료":
                continue
            due = parse_date(t.get("d"))
            if not due:
                continue
            items.append({"name": t["n"], "due": due, "who": t.get("w") or [], "drop": dname})
    return items


def short_drop(name):
    parts = name.split()
    return " ".join(parts[:2]) if len(parts) >= 2 else name


def group_by_who(items):
    groups = defaultdict(list)
    for it in items:
        who = it["who"] if isinstance(it["who"], list) else [it["who"]]
        who = tuple(sorted(w for w in who if w and w.strip()))
        groups[who].append(it)
    return sorted(groups.items(), key=lambda kv: -len(kv[1]))


def format_overdue_line(it):
    diff = (TODAY - it["due"]).days
    return f"  `-{diff}d` {it['name']}  _{short_drop(it['drop'])}_"


def format_urgent_line(it):
    diff = (it["due"] - TODAY).days
    label = "D-Day" if diff == 0 else f"D-{diff}"
    return f"  `{label}` {it['name']}  _{short_drop(it['drop'])}_"


def build_message():
    items = collect()
    overdue = sorted([i for i in items if i["due"] < TODAY], key=lambda x: x["due"])
    urgent = sorted(
        [i for i in items if 0 <= (i["due"] - TODAY).days <= URGENT_THRESHOLD],
        key=lambda x: x["due"],
    )

    today_str = f"{TODAY.month}/{TODAY.day}"
    weekday = "월화수목금토일"[TODAY.weekday()]
    lines = [f"🚨 *드랍 트래커* · {today_str}({weekday})"]

    if not overdue and not urgent:
        lines += ["", "✅ 마감 지난/임박한 항목 없음"]
        lines += ["", f"📊 <{DASHBOARD_URL}|대시보드 바로가기>"]
        return "\n".join(lines)

    if overdue:
        lines += ["", f"🔴 *마감 지남 · {len(overdue)}건*"]
        for who, group in group_by_who(overdue):
            lines += ["", f"{mention(list(who))} · {len(group)}건"]
            for it in group:
                lines.append(format_overdue_line(it))

    if urgent:
        lines += ["", f"🟡 *D-{URGENT_THRESHOLD} 임박 · {len(urgent)}건*"]
        for who, group in group_by_who(urgent):
            lines += ["", f"{mention(list(who))} · {len(group)}건"]
            for it in group:
                lines.append(format_urgent_line(it))

    lines += ["", f"📊 <{DASHBOARD_URL}|대시보드 바로가기>"]
    return "\n".join(lines)


def main():
    msg = build_message()
    print(msg)
    r = requests.post(SLACK_WEBHOOK_URL, json={"text": msg}, timeout=30)
    r.raise_for_status()
    print(f"\nSent. status={r.status_code}")


if __name__ == "__main__":
    main()
