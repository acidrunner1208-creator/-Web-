/* レース展開アニメーション — 各競馬場のコース形状を模した俯瞰ビュー (依存なし)
   window.__RACE_ANIM__ = {
     ticks, distance, direction, venue, surface, pace, pace_note, horse_length_m,
     horses: [{ num, name, style, draw, rank_track:[...], pos_track:[0..1...], finish }]
   }
   各馬を「レース距離のどこまで進んだか(pos_track)」で個別に配置し、隊列(前後の位置関係)が
   見えるようにする。横は枠順ベース＋重なり回避で少しずつずらす。
*/
(function () {
  "use strict";
  var data = window.__RACE_ANIM__;
  var canvas = document.getElementById("raceCanvas");
  if (!data || !canvas || !data.horses || !data.horses.length) return;

  var ctx = canvas.getContext("2d");
  var W = canvas.width, H = canvas.height;
  var horses = data.horses;
  var n = horses.length;
  var ticks = data.ticks;
  var DUR = 11000, HOLD = 2000;
  var R = n > 14 ? 7 : 8;                      // 馬マーカー半径
  var D = data.distance || 1600;

  var PALETTE = ["#d64545","#3f6fb0","#4a9d63","#c98a2b","#8a5cb4","#2aa4a4","#c0577f",
    "#6b8e23","#b5651d","#5b7db1","#7a9e3a","#a34a8f","#3d8f8f","#9c6b3f","#5f6caf",
    "#c05b5b","#4f9a4f","#b98a3a"];

  // --- コース形状パラメータ (相対) ---
  var GEO = {
    "東京":{w:0.94,h:0.60,straight:0.62,lap:2000}, "中山":{w:0.72,h:0.72,straight:0.32,lap:1800},
    "阪神":{w:0.84,h:0.64,straight:0.44,lap:1800}, "京都":{w:0.88,h:0.60,straight:0.42,lap:1900},
    "中京":{w:0.80,h:0.66,straight:0.48,lap:1700}, "新潟":{w:0.96,h:0.50,straight:0.66,lap:2000},
    "福島":{w:0.68,h:0.74,straight:0.34,lap:1700}, "小倉":{w:0.66,h:0.74,straight:0.30,lap:1650},
    "札幌":{w:0.78,h:0.68,straight:0.40,lap:1650}, "函館":{w:0.62,h:0.76,straight:0.28,lap:1600}
  };
  var g = GEO[data.venue] || {w:0.82,h:0.64,straight:0.46,lap:1800};
  var rightHanded = (data.direction || "").indexOf("右") >= 0;

  var M = 56;
  var cx = W / 2, cy = H / 2 + 6;
  var ry = g.h * (H / 2 - M);
  var rx = g.w * (W / 2 - M);
  var L = Math.max(60, g.straight * 2 * rx);
  var curve = Math.PI * ry;
  var perim = 2 * L + 2 * curve;
  var finishS = L;
  var laneGap = Math.min(11, (ry * 0.72) / Math.max(n, 6));

  // s (周回距離) -> {x,y}  スタジアム形 (ホーム直線 下・ゴール右端)
  function pathPoint(s) {
    s = ((s % perim) + perim) % perim;
    if (s <= L) return { x: cx - L / 2 + s, y: cy + ry };
    s -= L;
    if (s <= curve) {
      var a = (s / curve) * Math.PI;
      return { x: cx + L / 2 + ry * Math.sin(a), y: cy + ry * Math.cos(a) };
    }
    s -= curve;
    if (s <= L) return { x: cx + L / 2 - s, y: cy - ry };
    s -= L;
    var b = (s / curve) * Math.PI;
    return { x: cx - L / 2 - ry * Math.sin(b), y: cy - ry * Math.cos(b) };
  }
  function tangent(s) {
    var p1 = pathPoint(s - 2), p2 = pathPoint(s + 2);
    var dx = p2.x - p1.x, dy = p2.y - p1.y, m = Math.hypot(dx, dy) || 1;
    return { x: dx / m, y: dy / m };
  }

  var raceLenS = Math.min(0.97, D / g.lap) * perim;

  // レース進捗 frac(0..1) -> 周回位置 s  (frac=1 でゴール)
  function sAt(frac) {
    return rightHanded
      ? finishS + (1 - frac) * raceLenS
      : finishS - (1 - frac) * raceLenS;
  }

  function interp(arr, tf) {
    var i = Math.floor(tf), fr = tf - i;
    var a = arr[Math.min(i, ticks)], b = arr[Math.min(i + 1, ticks)];
    return a + (b - a) * fr;
  }

  function drawTrack() {
    ctx.fillStyle = "#eef2f6"; ctx.fillRect(0, 0, W, H);

    // トラック帯
    ctx.beginPath();
    for (var s = 0; s <= perim; s += 6) {
      var p = pathPoint(s);
      if (s === 0) ctx.moveTo(p.x, p.y); else ctx.lineTo(p.x, p.y);
    }
    ctx.closePath();
    ctx.lineWidth = 40; ctx.lineJoin = "round";
    ctx.strokeStyle = (data.surface === "ダ") ? "#c69c6a" : "#7fae6c";
    ctx.stroke();
    ctx.lineWidth = 2; ctx.strokeStyle = "rgba(255,255,255,.65)"; ctx.stroke();

    // ゴール線
    var f = pathPoint(finishS), ft = tangent(finishS);
    ctx.strokeStyle = "#fff"; ctx.lineWidth = 5;
    ctx.beginPath();
    ctx.moveTo(f.x - ft.y * 22, f.y + ft.x * 22);
    ctx.lineTo(f.x + ft.y * 22, f.y - ft.x * 22);
    ctx.stroke();
    ctx.fillStyle = "#222"; ctx.font = "bold 12px system-ui"; ctx.textAlign = "center";
    ctx.fillText("ゴール", f.x, f.y + 36);

    // 3〜4コーナー
    var cS = rightHanded ? finishS + L + curve / 2 : finishS - L - curve / 2;
    var cp = pathPoint(cS);
    ctx.fillStyle = "#555"; ctx.font = "11px system-ui";
    ctx.fillText("3〜4コーナー", cp.x, cp.y);

    // スタート地点
    var st = pathPoint(sAt(0));
    ctx.fillStyle = "#888"; ctx.beginPath(); ctx.arc(st.x, st.y, 3, 0, 7); ctx.fill();
    ctx.fillText("スタート", st.x, st.y + (st.y > cy ? 16 : -10));

    ctx.fillStyle = "#555"; ctx.textAlign = "left"; ctx.font = "12px system-ui";
    ctx.fillText((data.venue || "") + "（" + (rightHanded ? "右回り" : "左回り") + " / " +
      (data.surface === "ダ" ? "ダート" : "芝") + (D ? D + "m" : "") + "）", 12, 20);
  }

  var top3 = horses.filter(function (h) { return h.finish <= 3; }).map(function (h) { return h.num; });
  var playBtn = document.getElementById("animPlay");
  var replayBtn = document.getElementById("animReplay");
  var scrub = document.getElementById("animScrub");
  var label = document.getElementById("animLabel");
  var start = null, playing = false, pausedAt = 0;

  function layout(tf) {
    // 各馬: 進捗 -> トラック上の点 + 枠順ベースの横オフセット
    var items = horses.map(function (h, idx) {
      var pr = interp(h.pos_track, tf);
      var s = sAt(pr);
      var base = pathPoint(s);
      var tg = tangent(s);
      var nrm = { x: -tg.y, y: tg.x };
      var lane = ((h.draw || idx + 1) - (n + 1) / 2) * laneGap;
      return {
        h: h, idx: idx, pr: pr, base: base, nrm: nrm,
        x: base.x + nrm.x * lane, y: base.y + nrm.y * lane
      };
    });
    // 重なり回避 (screen空間で押し広げ)
    var minD = R * 2 + 3;
    for (var pass = 0; pass < 6; pass++) {
      for (var i = 0; i < items.length; i++) {
        for (var j = i + 1; j < items.length; j++) {
          var A = items[i], B = items[j];
          var dx = B.x - A.x, dy = B.y - A.y, d = Math.hypot(dx, dy);
          if (d > 0.001 && d < minD) {
            var k = (minD - d) / 2 / d;
            A.x -= dx * k; A.y -= dy * k; B.x += dx * k; B.y += dy * k;
          }
        }
      }
    }
    // トラック帯からはみ出さないよう中心線からの距離をクランプ
    var maxOff = ry * 0.5;
    items.forEach(function (o) {
      var dx = o.x - o.base.x, dy = o.y - o.base.y, dist = Math.hypot(dx, dy);
      if (dist > maxOff) { o.x = o.base.x + dx / dist * maxOff; o.y = o.base.y + dy / dist * maxOff; }
    });
    return items;
  }

  function draw(prog) {
    ctx.clearRect(0, 0, W, H);
    drawTrack();
    var tf = prog * ticks;
    var items = layout(tf);

    var atFinish = prog >= 0.999;
    // 後方の馬から描画 (先頭を前面に)
    items.slice().sort(function (a, b) { return a.pr - b.pr; }).forEach(function (o) {
      var col = PALETTE[o.idx % PALETTE.length];
      var dim = atFinish && top3.indexOf(o.h.num) === -1;
      ctx.globalAlpha = dim ? 0.3 : 1;
      ctx.fillStyle = col;
      ctx.strokeStyle = "rgba(255,255,255,.9)"; ctx.lineWidth = 1.5;
      ctx.beginPath(); ctx.arc(o.x, o.y, R, 0, 7); ctx.fill(); ctx.stroke();
      ctx.fillStyle = "#fff"; ctx.font = "bold " + (R + 2) + "px system-ui"; ctx.textAlign = "center";
      ctx.fillText(o.h.num, o.x, o.y + R * 0.45);
      ctx.globalAlpha = 1;
    });

    // 隊列リスト (右上) — 現在の並び順
    var byPos = items.slice().sort(function (a, b) { return b.pr - a.pr; });
    ctx.textAlign = "left"; ctx.font = "12px system-ui";
    ctx.fillStyle = "rgba(255,255,255,.82)"; ctx.fillRect(W - 244, 28, 236, 20 + Math.min(byPos.length, 8) * 16);
    byPos.slice(0, 8).forEach(function (o, i) {
      ctx.fillStyle = i < 3 ? "#222" : "#777";
      ctx.fillText((i + 1) + "  " + o.h.num + ". " + o.h.name + "（" + o.h.style + "）", W - 238, 44 + i * 16);
    });

    var leadPr = byPos.length ? byPos[0].pr : prog;
    var remain = Math.max(0, Math.round(D * (1 - leadPr) / 50) * 50);
    label.textContent = atFinish ? "ゴール" : ("先頭 残り約 " + remain + "m");
    scrub.value = String(Math.round(prog * 100));
  }

  function frame(ts) {
    if (start === null) start = ts;
    var el = ts - start + pausedAt;
    var prog = Math.min(1, el / DUR);
    draw(prog);
    if (prog < 1) { if (playing) requestAnimationFrame(frame); }
    else if (el < DUR + HOLD && playing) { requestAnimationFrame(frame); }
    else { playing = false; pausedAt = 0; start = null; playBtn.textContent = "▶ 再生"; }
  }
  function play() {
    if (playing) {
      playing = false; pausedAt += (performance.now() - start); start = null;
      playBtn.textContent = "▶ 再生"; return;
    }
    playing = true; playBtn.textContent = "❚❚ 一時停止"; start = null;
    requestAnimationFrame(frame);
  }
  function replay() {
    playing = false; pausedAt = 0; start = null; playBtn.textContent = "▶ 再生";
    draw(0); setTimeout(play, 60);
  }
  playBtn.addEventListener("click", play);
  replayBtn.addEventListener("click", replay);
  scrub.addEventListener("input", function () {
    playing = false; start = null; pausedAt = (Number(scrub.value) / 100) * DUR;
    playBtn.textContent = "▶ 再生"; draw(Number(scrub.value) / 100);
  });
  draw(0);
})();
