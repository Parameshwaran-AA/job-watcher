"""Telegram push. One message per run, never one per job."""

from __future__ import annotations

import html
import os

import httpx

API = "https://api.telegram.org/bot{token}/sendMessage"


def _esc(s: str) -> str:
    return html.escape(str(s or ""), quote=False)


def _line(row) -> str:
    exp = ""
    if row["exp_min"] is not None:
        exp = f" · {row['exp_min']}–{row['exp_max']}y" if row["exp_max"] else f" · {row['exp_min']}+y"
    loc = f" · {_esc(row['location'])}" if row["location"] else ""
    return (
        f"<b>{row['score']}</b>  <a href=\"{_esc(row['url'])}\">{_esc(row['title'])}</a>\n"
        f"     {_esc(row['company'])}{loc}{exp}"
    )


def send(rows, max_items: int = 10) -> bool:
    """Returns True if a message went out. Silently no-ops if unconfigured."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat = os.environ.get("TELEGRAM_CHAT_ID")
    if not rows:
        return False
    if not token or not chat:
        print(f"  telegram not configured; {len(rows)} alert(s) held")
        return False

    shown = rows[:max_items]
    header = f"<b>{len(rows)} new role{'s' if len(rows) != 1 else ''} on your watchlist</b>"
    body = "\n\n".join(_line(r) for r in shown)
    if len(rows) > max_items:
        body += f"\n\n<i>+{len(rows) - max_items} more on the dashboard</i>"

    try:
        r = httpx.post(
            API.format(token=token),
            json={
                "chat_id": chat,
                "text": f"{header}\n\n{body}",
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
            timeout=20,
        )
        r.raise_for_status()
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"  telegram send failed: {exc}")
        return False


def heartbeat(text: str) -> None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat:
        return
    try:
        httpx.post(
            API.format(token=token),
            json={"chat_id": chat, "text": text, "disable_web_page_preview": True},
            timeout=20,
        )
    except Exception:  # noqa: BLE001, S110
        pass
