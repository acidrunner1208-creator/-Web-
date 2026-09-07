"""シミュレーション結果 -> 静的 HTML / JSON 生成。"""
from __future__ import annotations

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


def line_chart_svg(points: list[float], width: int = 640, height: int = 220) -> str:
    """累積損益の折れ線 (0 基準線つき)。"""
    if len(points) < 2:
        return '<p class="muted">まだ確定した結果がありません。</p>'
    lo, hi = min(points + [0.0]), max(points + [0.0])
    span = (hi - lo) or 1.0
    pad = 24
    xs = [pad + i / (len(points) - 1) * (width - 2 * pad) for i in range(len(points))]
    ys = [height - pad - (p - lo) / span * (height - 2 * pad) for p in points]
    zero_y = height - pad - (0 - lo) / span * (height - 2 * pad)
    path = "M " + " L ".join(f"{x:.1f},{y:.1f}" for x, y in zip(xs, ys))
    last_col = "#1f8a4c" if points[-1] >= 0 else "#c0392b"
    area = f"M {xs[0]:.1f},{zero_y:.1f} L " + " L ".join(
        f"{x:.1f},{y:.1f}" for x, y in zip(xs, ys)
    ) + f" L {xs[-1]:.1f},{zero_y:.1f} Z"
    return (
        f'<svg viewBox="0 0 {width} {height}" class="roi-chart" role="img" aria-label="累積損益">'
        f'<path d="{area}" fill="{last_col}" fill-opacity="0.12"/>'
        f'<line x1="{pad}" y1="{zero_y:.1f}" x2="{width - pad}" y2="{zero_y:.1f}" '
        f'stroke="#999" stroke-dasharray="3 3"/>'
        f'<path d="{path}" fill="none" stroke="{last_col}" stroke-width="2"/>'
        f'<text x="{pad}" y="14" font-size="11" fill="#666">￥{int(hi):,}</text>'
        f'<text x="{pad}" y="{height - 6}" font-size="11" fill="#666">￥{int(lo):,}</text>'
        f'</svg>'
    )


env.filters["pct"] = _pct
env.filters["yen"] = _yen
env.globals["bars_svg"] = bars_svg
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
    if _ASSET_SRC.exists():
        for f in _ASSET_SRC.iterdir():
            if f.is_file():
                shutil.copy2(f, assets_out / f.name)

    races = payload["races"]
    meta = {k: payload[k] for k in ("dates", "generated_at", "demo_mode", "n_sims", "note")}
    meta["model_state"] = payload.get("model_state", {"trained": False, "n_races": 0})

    ledger = {}
    lp = out_dir / "data" / "ledger.json"
    if lp.exists():
        try:
            ledger = json.loads(lp.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            ledger = {}
    cum = [e["cum_profit"] for e in ledger.get("entries", [])]
    roi_chart = line_chart_svg([0.0] + cum) if cum else ""

    (out_dir / "index.html").write_text(
        env.get_template("index.html").render(
            meta=meta, attention=payload["attention"], groups=payload["groups"],
            total_races=len(races), ledger=ledger, roi_chart=roi_chart,
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
