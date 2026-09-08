"""レース前の最終予想を X (Twitter) に投稿し、全レース予想の note 記事を生成する。

X 投稿:
  注目レース3つ＋各レースの軸・買い目(単勝／3連複／3連単)・軸馬の平均着順/勝率/複勝率/適正オッズ。
  返信に「全レース予想を有料 note (¥300) で公開中」の宣伝をぶら下げる。
  認証情報 (X_API_KEY / X_API_SECRET / X_ACCESS_TOKEN / X_ACCESS_SECRET) が
  4つ揃っているときだけ実投稿。無ければ本文生成のみ。

note 記事:
  その日開催される全レース(1R〜12R)を1記事にまとめた本文 (¥300 販売想定)。
  note は投稿 API が無いため、本文は Basic 認証つきサイトの /announce.html に置き、
  手動でコピーして公開する。

    python -m builder.publish generate --out ./public          # 本文生成 (ビルドから自動実行)
    python -m builder.publish post-x  --out ./public           # X へ投稿 (レース日の朝のみ)
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import logging
import os
import secrets
import time
import urllib.parse
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

log = logging.getLogger("publish")

JST = timezone(timedelta(hours=9))
STATE_PATH = Path(__file__).parent / "model" / "state" / "announced.json"
NOTE_PRICE = 300
NOTE_URL_DEFAULT = os.environ.get("NOTE_URL", "https://note.com/")  # 記事URLが決まったら Secret で
X_POST_HOURS = (8, 12)   # JST。この時間帯の実行でだけ X へ投稿する (馬場発表後の最終更新)


# --------------------------------------------------------------- フォーマット
def _pct(x: float | None) -> str:
    return "—" if x is None else f"{x * 100:.0f}%"


def _bet_of(race: dict, key: str) -> dict | None:
    return next((b for b in race.get("recommended", []) if b.get("key") == key), None)


def _kaimoku(race: dict) -> str:
    puk, tan3 = _bet_of(race, "sanrenpuku"), _bet_of(race, "sanrentan")
    parts = ["単勝"]
    if puk:
        parts.append(f"3連複{puk.get('method', '')}")
    if tan3:
        parts.append(f"3連単{tan3.get('method', '')}")
    return "／".join(parts)


def _axis_stats(h: dict) -> str:
    return (f"勝率{_pct(h.get('win_prob'))} 複勝{_pct(h.get('place_prob'))} "
            f"平均{h.get('avg_finish')}着 適正{h.get('fair_win_odds')}倍")


def _race_block_x(idx: int, race: dict) -> str:
    h = race["horses"][0]
    mark = "①②③④⑤"[idx] if idx < 5 else f"{idx + 1}."
    return (
        f"{mark}{race['venue']}{race['race_number']}R {race.get('race_name') or ''}"
        f"（自信度:{race.get('confidence_tier', '—')}）\n"
        f"軸 {h['num']}.{h['name']}\n"
        f" {_axis_stats(h)}\n"
        f"買い目 {_kaimoku(race)}"
    )


def _pack(segments: list[str], limit: int = 273) -> list[str]:
    """連続する短いセグメントを limit 文字以内でまとめてスレッド用の本文列にする。"""
    out: list[str] = []
    cur = ""
    for s in segments:
        cand = s if not cur else cur + "\n\n" + s
        if len(cand) <= limit:
            cur = cand
        else:
            if cur:
                out.append(cur)
            cur = s
    if cur:
        out.append(cur)
    return out


def build_x_thread(attention: list[dict], date_label: str, note_url: str) -> list[str]:
    """X のスレッド本文列。最後の1件は note 宣伝 (返信としてぶら下げる)。"""
    header = f"【{date_label} JRA 注目レース】\nシミュレーション1万回の予想。買い目と全レース予想はnoteで。"
    blocks = [_race_block_x(i, r) for i, r in enumerate(attention[:3])]
    body = _pack([header, *blocks])
    ad = (
        "▲この日の全レース（1R〜12R）の予想を note にまとめました。\n"
        "各レースの自信度・軸馬・買い目（単勝／3連複／3連単）・軸馬の平均着順/勝率/複勝率/適正オッズ入り。\n"
        f"1記事 ¥{NOTE_PRICE}。→ {note_url}"
    )
    return body + [ad]


# --------------------------------------------------------------- note 本文
def build_note_markdown(races_of_day: list[dict], date_label: str) -> str:
    lines = [
        f"# {date_label} JRA 全レース予想（{len(races_of_day)}レース掲載）",
        "",
        "各レース、モンテカルロ・シミュレーションを **10,000 回** 試行した結果です。",
        "「自信度」は本命の抜けの大きさ（高／中／低）。買い目は軸のはっきり度で"
        "「流し」「フォーメーション」を都度選んでいます。数値は的中を保証しません。",
        "",
    ]
    by_venue: dict[str, list[dict]] = {}
    for r in races_of_day:
        by_venue.setdefault(r["venue"] or "—", []).append(r)

    for venue, rs in by_venue.items():
        lines.append(f"## {venue}")
        lines.append("")
        for r in sorted(rs, key=lambda x: x["race_number"] or 0):
            h = r["horses"][0]
            puk, tan3 = _bet_of(r, "sanrenpuku"), _bet_of(r, "sanrentan")
            lines += [
                f"### {r['race_number']}R {r.get('race_name') or ''}"
                f"　{r.get('surface', '')}{r.get('distance', '')}m"
                f"（発走 {r.get('start_time') or '—'}）",
                "",
                f"- **自信度：{r.get('confidence_tier', '—')}**",
                f"- 軸：**{h['num']}. {h['name']}**",
                f"- 軸の平均着順 {h.get('avg_finish')}着／勝率 {_pct(h.get('win_prob'))}"
                f"／複勝率 {_pct(h.get('place_prob'))}／適正オッズ {h.get('fair_win_odds')}倍",
                f"- 単勝：{_bet_of(r, 'tansho')['selection'] if _bet_of(r, 'tansho') else '—'}",
                f"- 3連複（{puk.get('method', '') if puk else ''}）：{puk['selection'] if puk else '—'}"
                f"　{puk['unit'] if puk else 0}点",
                f"- 3連単（{tan3.get('method', '') if tan3 else ''}）：{tan3['selection'] if tan3 else '—'}"
                f"　{tan3['unit'] if tan3 else 0}点",
                "",
            ]
    lines += ["---", "", "※ 過去データに基づく統計的シミュレーションです。馬券は自己責任で。"]
    return "\n".join(lines)


# --------------------------------------------------------------- X API (OAuth1.0a)
def _oauth1_header(method: str, url: str, ck: str, cs: str, at: str, ats: str) -> str:
    oauth = {
        "oauth_consumer_key": ck,
        "oauth_nonce": secrets.token_hex(16),
        "oauth_signature_method": "HMAC-SHA1",
        "oauth_timestamp": str(int(time.time())),
        "oauth_token": at,
        "oauth_version": "1.0",
    }
    q = "&".join(f"{urllib.parse.quote(k, safe='')}={urllib.parse.quote(v, safe='')}"
                 for k, v in sorted(oauth.items()))
    base = "&".join([method.upper(), urllib.parse.quote(url, safe=""),
                     urllib.parse.quote(q, safe="")])
    key = f"{urllib.parse.quote(cs, safe='')}&{urllib.parse.quote(ats, safe='')}"
    sig = base64.b64encode(hmac.new(key.encode(), base.encode(), hashlib.sha1).digest()).decode()
    oauth["oauth_signature"] = sig
    return "OAuth " + ", ".join(
        f'{urllib.parse.quote(k, safe="")}="{urllib.parse.quote(v, safe="")}"'
        for k, v in sorted(oauth.items())
    )


def _x_creds() -> tuple[str, str, str, str] | None:
    keys = ("X_API_KEY", "X_API_SECRET", "X_ACCESS_TOKEN", "X_ACCESS_SECRET")
    vals = [os.environ.get(k, "").strip() for k in keys]
    return tuple(vals) if all(vals) else None  # type: ignore


def verify_x() -> dict:
    """認証情報の疎通確認 (GET /2/users/me)。投稿はしない。"""
    creds = _x_creds()
    if not creds:
        return {"ok": False, "reason": "認証情報 (X_API_KEY 等4つ) が未設定"}
    ck, cs, at, ats = creds
    url = "https://api.twitter.com/2/users/me"
    hdr = _oauth1_header("GET", url, ck, cs, at, ats)
    r = httpx.get(url, headers={"Authorization": hdr}, timeout=20)
    if r.status_code != 200:
        return {"ok": False, "status": r.status_code, "body": r.text[:300]}
    data = r.json().get("data", {})
    return {"ok": True, "username": data.get("username"), "id": data.get("id")}


def post_x_thread(segments: list[str]) -> list[str]:
    """スレッドを順に投稿。tweet id のリストを返す。認証情報が無ければ空リスト。"""
    creds = _x_creds()
    if not creds:
        log.warning("X 認証情報が未設定のため投稿をスキップ (本文は生成済み)")
        return []
    ck, cs, at, ats = creds
    url = "https://api.twitter.com/2/tweets"
    ids: list[str] = []
    with httpx.Client(timeout=20) as cli:
        for i, text in enumerate(segments):
            payload: dict = {"text": text}
            if ids:
                payload["reply"] = {"in_reply_to_tweet_id": ids[-1]}
            hdr = _oauth1_header("POST", url, ck, cs, at, ats)
            r = cli.post(url, headers={"Authorization": hdr, "Content-Type": "application/json"},
                         json=payload)
            if r.status_code >= 300:
                log.error("X 投稿失敗 (%s): %s", r.status_code, r.text[:300])
                break
            tid = r.json()["data"]["id"]
            ids.append(tid)
            log.info("X 投稿 %d/%d -> %s", i + 1, len(segments), tid)
            time.sleep(2)
    return ids


# --------------------------------------------------------------- state
def _load_state() -> dict:
    if STATE_PATH.exists():
        try:
            return json.loads(STATE_PATH.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            pass
    return {"x_posted": []}


def _save_state(s: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(s, ensure_ascii=False, indent=2), encoding="utf-8")


# --------------------------------------------------------------- 実行
def _date_label(iso: str) -> str:
    d = datetime.fromisoformat(iso)
    wd = "月火水木金土日"[d.weekday()]
    return f"{d.month}/{d.day}（{wd}）"


def _races_by_date(payload: dict) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for r in payload.get("races", []):
        out.setdefault(r["kaisai_date"], []).append(r)
    return out


def _day_attention(races_of_day: list[dict], n: int = 3) -> list[dict]:
    """その日のレースから自信度(confidence)上位 n レース。"""
    return sorted(races_of_day, key=lambda r: r.get("confidence", 0.0), reverse=True)[:n]


def generate(out_dir: Path, payload: dict) -> None:
    """note 本文と X 本文を Basic 認証つきサイト(/announce.html, /data/private/) に置く。"""
    priv = out_dir / "data" / "private"
    priv.mkdir(parents=True, exist_ok=True)
    note_url = os.environ.get("NOTE_URL", NOTE_URL_DEFAULT)

    by_date = _races_by_date(payload)
    sections = []
    for iso in sorted(by_date):
        label = _date_label(iso)
        md = build_note_markdown(by_date[iso], label)
        (priv / f"note-{iso.replace('-', '')}.md").write_text(md, encoding="utf-8")

        att = _day_attention(by_date[iso])
        thread = build_x_thread(att, label, note_url) if att else []
        (priv / f"x-{iso.replace('-', '')}.json").write_text(
            json.dumps({"date": iso, "thread": thread}, ensure_ascii=False, indent=2),
            encoding="utf-8")

        sections.append((label, iso, md, thread))

    _write_announce_page(out_dir, sections)
    log.info("announcements 生成: %d 日分", len(sections))


def _write_announce_page(out_dir: Path, sections: list) -> None:
    esc = lambda s: (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))
    blocks = []
    for label, iso, md, thread in sections:
        tw = "\n\n──────────\n\n".join(thread)
        blocks.append(
            f"<h2>{esc(label)}</h2>"
            f"<h3>X 投稿（スレッド／最後の1件は返信の宣伝）</h3><pre>{esc(tw)}</pre>"
            f"<h3>note 記事本文（¥{NOTE_PRICE}で販売・全文コピーして貼り付け）</h3>"
            f"<pre>{esc(md)}</pre>"
        )
    html = (
        "<!doctype html><meta charset=utf-8><title>投稿用テキスト</title>"
        "<style>body{font:14px/1.6 system-ui;margin:24px;max-width:820px}"
        "pre{white-space:pre-wrap;background:#f5f6f8;border:1px solid #ddd;border-radius:8px;padding:12px}"
        "h2{border-bottom:2px solid #333;margin-top:32px}</style>"
        "<h1>投稿用テキスト（Basic認証内・非公開）</h1>"
        "<p>X は認証情報があれば自動投稿。note は下の本文をコピーして note.com で"
        f"¥{NOTE_PRICE}記事として公開してください。</p>" + "".join(blocks)
    )
    (out_dir / "announce.html").write_text(html, encoding="utf-8")


def post_x(out_dir: Path, payload: dict, *, force: bool = False,
           date: str | None = None) -> dict:
    now = datetime.now(JST)
    if not force and not (X_POST_HOURS[0] <= now.hour < X_POST_HOURS[1]):
        log.info("X 投稿時間帯外 (JST %d時) のためスキップ", now.hour)
        return {"posted": None}
    today = date or now.strftime("%Y-%m-%d")
    races_today = _races_by_date(payload).get(today, [])
    att = _day_attention(races_today)
    if not att:
        log.info("%s のレースが無いため投稿しない", today)
        return {"posted": None}

    state = _load_state()
    if today in state.get("x_posted", []) and not force:
        log.info("%s は投稿済み", today)
        return {"posted": None}

    note_url = os.environ.get("NOTE_URL", NOTE_URL_DEFAULT)
    thread = build_x_thread(att, _date_label(today), note_url)
    ids = post_x_thread(thread)
    if ids:
        state.setdefault("x_posted", []).append(today)
        _save_state(state)
    return {"posted": today if ids else None, "tweets": ids}


def _load_payload(out_dir: Path) -> dict:
    """直近ビルドの latest.json + 各レース json から payload 相当を復元。"""
    latest = json.loads((out_dir / "data" / "latest.json").read_text(encoding="utf-8"))
    races, attention = [], []
    for row in latest.get("races", []):
        p = out_dir / "data" / "races" / f"{row['race_id']}.json"
        if p.exists():
            races.append(json.loads(p.read_text(encoding="utf-8")))
    att_ids = set(latest.get("attention", []))
    attention = [r for r in races if r["race_id"] in att_ids]
    attention.sort(key=lambda r: att_ids and list(latest["attention"]).index(r["race_id"]))
    return {"races": races, "attention": attention}


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["generate", "post-x", "verify"])
    ap.add_argument("--out", default="./public")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--date", default=None, help="post-x で投稿する開催日 (YYYY-MM-DD)")
    args = ap.parse_args()

    if args.cmd == "verify":
        log.info("verify: %s", verify_x())
        return

    out = Path(args.out)
    payload = _load_payload(out)
    if args.cmd == "generate":
        generate(out, payload)
    else:
        r = post_x(out, payload, force=args.force, date=args.date)
        log.info("post-x: %s", r)


if __name__ == "__main__":
    main()
