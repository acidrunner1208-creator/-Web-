"""シミュレーション結果 -> 静的 HTML / JSON 生成。"""
from __future__ import annotations

import hashlib
import json
import shutil
from datetime import date, datetime, timezone
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

_TPL_DIR = Path(__file__).parent / "templates"
_ASSET_SRC = Path(__file__).parent / "assets"
KEEP_DAYS = 45

env = Environment(
    loader=FileSystemLoader(str(_TPL_DIR)),
    autoescape=select_autoescape(["html"]),
    trim_blocks=True,
    lstrip_blocks=True,
)


def _pct(x) -> str:
    return "—" if x is None else f"{x * 100:.1f}%"


def _yen(x) -> str:
    return "—" if x is None else f"{int(round(x)):,}"


def bars_svg(values: list[float], width: int = 150, height: int = 30, color: str = "#3f6fb0") -> str:
    if not values:
        return ""
    n = len(values)
    mx = max(values) or 1.0
    bw = width / n
    rects = "".join(
        f'<rect x="{i * bw:.1f}" y="{height - max(1.0, (v / mx) * (height - 3)):.1f}" '
        f'width="{bw * 0.8:.1f}" height="{max(1.0, (v / mx) * (height - 3)):.1f}" fill="{color}" rx="1"/>'
        for i, v in enumerate(values)
    )
    return f'<svg viewBox="0 0 {width} {height}" class="spark" aria-label="着順分布">{rects}</svg>'


_PALETTE = [
    "#d64545", "#3f6fb0", "#4a9d63", "#c98a2b", "#8a5cb4", "#2aa4a4", "#c0577f",
    "#6b8e23", "#b5651d", "#5b7db1", "#7a9e3a", "#a34a8f", "#3d8f8f", "#9c6b3f",
    "#5f6caf", "#c05b5b", "#4f9a4f", "#b98a3a",
]


def positions_chart_svg(animation: dict | None, width: int = 760, height: int = 320) -> str:
    """スタート直後からゴールまでの位置取り(隊列)の推移予想を折れ線で示す静的図。

    横軸 = レースの進行 (左=スタート直後 / 右=ゴール)、縦軸 = そのときの隊列内の順位。
    """
    if not animation or not animation.get("horses"):
        return ""
    horses = animation["horses"]
    ticks = animation["ticks"]
    dist = animation.get("distance") or 0
    H = len(horses)
    if H < 2:
        return ""

    padL, padR, padT, padB = 44, 92, 40, 34
    plot_w = width - padL - padR
    plot_h = height - padT - padB

    def x(t: int) -> float:
        return padL + t / ticks * plot_w

    def y(rank: float) -> float:
        return padT + (rank - 1) / (H - 1) * plot_h

    top3 = {h["num"] for h in horses if h["finish"] <= 3}
    parts: list[str] = [
        f'<svg viewBox="0 0 {width} {height}" class="pos-chart" role="img" '
        f'aria-label="展開予想（位置取りの推移）">',
        f'<rect x="{padL}" y="{padT}" width="{plot_w:.0f}" height="{plot_h:.0f}" fill="#fafbfc" stroke="#e2e6ea"/>',
        # 序盤帯
        f'<rect x="{padL}" y="{padT}" width="{plot_w * 0.18:.0f}" height="{plot_h:.0f}" fill="#eef3f8"/>',
        f'<text x="{padL + 4}" y="{padT + 13}" font-size="10" fill="#7a8a99">スタート〜序盤</text>',
    ]
    # 距離グリッド
    for frac in (0.0, 0.25, 0.5, 0.75, 1.0):
        gx = padL + frac * plot_w
        parts.append(f'<line x1="{gx:.1f}" y1="{padT}" x2="{gx:.1f}" y2="{padT + plot_h}" stroke="#e2e6ea"/>')
        m = int(round(dist * frac / 50) * 50) if dist else int(frac * 100)
        parts.append(
            f'<text x="{gx:.1f}" y="{padT + plot_h + 14}" font-size="10" fill="#888" '
            f'text-anchor="middle">{m}{"m" if dist else "%"}</text>'
        )
    # 順位グリッド (1,3,5,...)
    for rank in range(1, H + 1, 2):
        gy = y(rank)
        parts.append(f'<line x1="{padL}" y1="{gy:.1f}" x2="{padL + plot_w}" y2="{gy:.1f}" stroke="#eef1f4"/>')
        parts.append(f'<text x="{padL - 6}" y="{gy + 3:.1f}" font-size="10" fill="#888" text-anchor="end">{rank}</text>')

    parts.append(
        f'<text x="{padL}" y="{padT - 22}" font-size="11" fill="#555">'
        f'← スタート直後　　隊列（縦=順位, 上=前）　　ゴール →</text>'
    )

    order = sorted(range(H), key=lambda i: horses[i]["finish"])
    for i in order:
        h = horses[i]
        rt = h["rank_track"]
        pts = " ".join(f"{x(t):.1f},{y(rt[t]):.1f}" for t in range(ticks + 1))
        col = _PALETTE[i % len(_PALETTE)]
        hot = h["num"] in top3
        parts.append(
            f'<polyline points="{pts}" fill="none" stroke="{col}" '
            f'stroke-width="{2.4 if hot else 1.2}" stroke-opacity="{1 if hot else 0.5}" '
            f'stroke-linejoin="round"/>'
        )
        ey = y(rt[-1])
        parts.append(
            f'<circle cx="{x(ticks):.1f}" cy="{ey:.1f}" r="{3.4 if hot else 2.4}" fill="{col}"/>'
        )
        parts.append(
            f'<text x="{x(ticks) + 6:.1f}" y="{ey + 3:.1f}" font-size="{10.5 if hot else 9.5}" '
            f'fill="{col if hot else "#999"}">{h["num"]}. {h["name"][:6]}</text>'
        )
    parts.append("</svg>")
    return "".join(parts)


def line_chart_svg(points: list[float], width: int = 640, height: int = 220,
                   mode: str = "yen") -> str:
    """0 基準線つきの折れ線。mode="yen" は円、"pct" は利益率(%) 表示。"""
    if len(points) < 2:
        return '<p class="muted">まだ確定した結果がありません。</p>'

    def lab(v: float) -> str:
        return f"{v:+.1f}%" if mode == "pct" else f"￥{int(v):,}"

    lo, hi = min(points + [0.0]), max(points + [0.0])
    span = (hi - lo) or 1.0
    pad = 30
    xs = [pad + i / (len(points) - 1) * (width - 2 * pad) for i in range(len(points))]
    ys = [height - pad - (p - lo) / span * (height - 2 * pad) for p in points]
    zero_y = height - pad - (0 - lo) / span * (height - 2 * pad)
    path = "M " + " L ".join(f"{x:.1f},{y:.1f}" for x, y in zip(xs, ys))
    last_col = "#1f8a4c" if points[-1] >= 0 else "#c0392b"
    area = f"M {xs[0]:.1f},{zero_y:.1f} L " + " L ".join(
        f"{x:.1f},{y:.1f}" for x, y in zip(xs, ys)
    ) + f" L {xs[-1]:.1f},{zero_y:.1f} Z"
    return (
        f'<svg viewBox="0 0 {width} {height}" class="roi-chart" role="img" '
        f'aria-label="{"累積利益率" if mode == "pct" else "累積損益"}">'
        f'<path d="{area}" fill="{last_col}" fill-opacity="0.12"/>'
        f'<line x1="{pad}" y1="{zero_y:.1f}" x2="{width - pad}" y2="{zero_y:.1f}" '
        f'stroke="#999" stroke-dasharray="3 3"/>'
        f'<text x="{width - pad}" y="{zero_y - 4:.1f}" font-size="10" fill="#999" text-anchor="end">±0</text>'
        f'<path d="{path}" fill="none" stroke="{last_col}" stroke-width="2"/>'
        f'<text x="4" y="14" font-size="11" fill="#666">{lab(hi)}</text>'
        f'<text x="4" y="{height - 6}" font-size="11" fill="#666">{lab(lo)}</text>'
        f'</svg>'
    )


LAUNCH_DATE = "2026-09-08"   # この日以降のレースを「運用開始からの成績」として集計

# 成績を集計・グラフ化する買い目 (キー, 表示名) — 表示順
TRACKED_BETS = [
    ("tansho", "単勝"),
    ("sanrenpuku", "3連複"),
    ("sanrentan", "3連単"),
]


def _tally(rows: list[tuple[int, int]]) -> dict:
    """rows: [(stake, ret), ...] を時系列で累積して指標＋累積利益率(%)系列を返す。"""
    stake = sum(s for s, _ in rows)
    ret = sum(r for _, r in rows)
    hit = sum(1 for s, r in rows if r > s)
    cs = cr = 0
    series = [0.0]
    for s, r in rows:
        cs += s
        cr += r
        series.append((cr - cs) / cs * 100 if cs else 0.0)
    return {
        "races": len(rows),
        "hit_races": hit,
        "stake": stake,
        "ret": ret,
        "profit": ret - stake,
        "profit_rate": round((ret - stake) / stake * 100, 1) if stake else 0.0,
        "recovery_rate": round(ret / stake * 100, 1) if stake else 0.0,
        "series": series,
        "chart": line_chart_svg(series, mode="pct") if len(series) >= 2 else "",
    }


def roi_headline(ledger: dict) -> dict:
    """運用開始日以降の累計成績＋買い目別内訳。空でも 0 を返す (ホームに常時表示)。"""
    entries = [e for e in ledger.get("entries", []) if e.get("date", "") >= LAUNCH_DATE]

    overall = _tally([(e["stake"], e["ret"]) for e in entries])

    by_type = []
    for key, label in TRACKED_BETS:
        rows = []
        for e in entries:
            b = next((x for x in e.get("bets", []) if x.get("key") == key), None)
            if b:
                rows.append((b["stake"], b["ret"]))
        by_type.append({"key": key, "label": label, **_tally(rows)})

    return {"since": LAUNCH_DATE, **overall, "by_type": by_type}


env.filters["pct"] = _pct
env.filters["yen"] = _yen
env.globals["bars_svg"] = bars_svg
env.globals["positions_chart_svg"] = positions_chart_svg
env.globals["now_jst"] = lambda: datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M")


def _index_row(r: dict) -> dict:
    top = r["horses"][0] if r["horses"] else {}
    return {
        "race_id": r["race_id"], "kaisai_date": r["kaisai_date"], "venue": r["venue"],
        "race_number": r["race_number"], "race_name": r["race_name"],
        "surface": r["surface"], "distance": r["distance"], "start_time": r["start_time"],
        "confidence": r["confidence"],
        "top": {"num": top.get("num"), "name": top.get("name"), "win_prob": top.get("win_prob")},
    }


def _prune(dir_: Path, keep_days: int = KEEP_DAYS) -> None:
    if not dir_.exists():
        return
    cutoff = date.today().toordinal() - keep_days
    for f in dir_.glob("*.json"):
        try:
            d = json.loads(f.read_text(encoding="utf-8")).get("kaisai_date", "")
            if d and date.fromisoformat(d).toordinal() < cutoff:
                f.unlink()
                html = f.parent.parent.parent / "races" / (f.stem + ".html")
                if html.exists():
                    html.unlink()
        except Exception:  # noqa: BLE001
            continue


def render_site(out_dir: Path, payload: dict) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "races").mkdir(exist_ok=True)
    (out_dir / "data" / "races").mkdir(parents=True, exist_ok=True)

    assets_out = out_dir / "assets"
    assets_out.mkdir(exist_ok=True)
    digest = hashlib.sha1()
    if _ASSET_SRC.exists():
        for f in sorted(_ASSET_SRC.iterdir()):
            if f.is_file():
                shutil.copy2(f, assets_out / f.name)
                digest.update(f.read_bytes())

    races = payload["races"]
    meta = {k: payload[k] for k in ("dates", "generated_at", "demo_mode", "n_sims", "note")}
    meta["model_state"] = payload.get("model_state", {"trained": False, "n_races": 0})
    meta["asset_ver"] = digest.hexdigest()[:8]   # アセット更新時のキャッシュ破棄用

    ledger = {}
    lp = out_dir / "data" / "ledger.json"
    if lp.exists():
        try:
            ledger = json.loads(lp.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            ledger = {}
    cum = [e["cum_profit"] for e in ledger.get("entries", [])]
    roi_chart = line_chart_svg([0.0] + cum) if cum else ""
    roi = roi_headline(ledger)

    (out_dir / "index.html").write_text(
        env.get_template("index.html").render(
            meta=meta, attention=payload["attention"], groups=payload["groups"],
            total_races=len(races), ledger=ledger, roi_chart=roi_chart, roi=roi,
        ),
        encoding="utf-8",
    )
    (out_dir / "about.html").write_text(
        env.get_template("about.html").render(meta=meta), encoding="utf-8"
    )

    for r in races:
        (out_dir / "races" / f"{r['race_id']}.html").write_text(
            env.get_template("race.html").render(meta=meta, r=r), encoding="utf-8"
        )
        (out_dir / "data" / "races" / f"{r['race_id']}.json").write_text(
            json.dumps(r, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
        )

    (out_dir / "data" / "latest.json").write_text(
        json.dumps({**meta, "attention": [a["race_id"] for a in payload["attention"]],
                    "races": [_index_row(r) for r in races]}, ensure_ascii=False),
        encoding="utf-8",
    )
    (out_dir / "_headers").write_text(
        "/assets/*\n  Cache-Control: public, max-age=86400\n"
        "/data/*\n  Cache-Control: public, max-age=180\n",
        encoding="utf-8",
    )
    _prune(out_dir / "data" / "races")
    _prune(out_dir / "data" / "recommended", keep_days=90)
