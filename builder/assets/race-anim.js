/* レース展開アニメーション — 各競馬場のコース形状を模した俯瞰ビュー (依存なし)
   window.__RACE_ANIM__ = { ticks, distance, direction, venue, pace, horses:[{num,name,style,rank_track,finish}] }
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
  var DUR = 10000, HOLD = 1600;

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

  var M = 54;
  var cx = W / 2, cy = H / 2 + 6;
  var ry = g.h * (H / 2 - M);
  var rx = g.w * (W / 2 - M);
  var L = Math.max(60, g.straight * 2 * rx);   // 直線の長さ
  var curve = Math.PI * ry;
  var perim = 2 * L + 2 * curve;
  var finishS = L;                               // ホーム直線の右端

  // s (周回距離) -> {x,y}  スタジアム形 (ホーム直線 下・ゴール右端)
  function pathPoint(s) {
    s = ((s % perim) + perim) % perim;
    if (s <= L) {                                       // ホーム直線: 左→右
      return { x: cx - L / 2 + s, y: cy + ry };
    }
    s -= L;
    if (s <= curve) {                                   // 右カーブ (下→上, 右へ膨らむ)
      var a = (s / curve) * Math.PI;
      return { x: cx + L / 2 + ry * Math.sin(a), y: cy + ry * Math.cos(a) };
    }
    s -= curve;
    if (s <= L) {                                       // 向正面: 右→左
      return { x: cx + L / 2 - s, y: cy - ry };
    }
    s -= L;                                             // 左カーブ (上→下, 左へ膨らむ)
    var b = (s / curve) * Math.PI;
    return { x: cx - L / 2 - ry * Math.sin(b), y: cy - ry * Math.cos(b) };
  }
  function tangent(s) {
    var p1 = pathPoint(s - 2), p2 = pathPoint(s + 2);
    var dx = p2.x - p1.x, dy = p2.y - p1.y, m = Math.hypot(dx, dy) || 1;
    return { x: dx / m, y: dy / m };
  }

  var raceLenS = Math.min(0.97, (data.distance || 1600) / g.lap) * perim;

  // レース進行 prog(0..1) -> 周回位置 s
  function sAt(prog) {
    return rightHanded
      ? finishS + (1 - prog) * raceLenS
      : finishS - (1 - prog) * raceLenS;
  }

  function drawTrack() {
    // 芝/ダートの地色
    ctx.fillStyle = (data.surface === "ダ") ? "#c9a06a" : "#7ba86a";
    ctx.strokeStyle = "#e9eef2";
    ctx.lineWidth = 30;
    ctx.beginPath();
    for (var s = 0; s <= perim; s += 6) {
      var p = pathPoint(s);
      if (s === 0) ctx.moveTo(p.x, p.y); else ctx.lineTo(p.x, p.y);
    }
    ctx.closePath();
    ctx.lineWidth = 34; ctx.strokeStyle = (data.surface === "ダ") ? "#c9a06a" : "#7ba86a";
    ctx.stroke();
    ctx.lineWidth = 2; ctx.strokeStyle = "rgba(255,255,255,.7)"; ctx.stroke();

    // ゴール線
    var f = pathPoint(finishS), ft = tangent(finishS);
    ctx.strokeStyle = "#fff"; ctx.lineWidth = 4;
    ctx.beginPath();
    ctx.moveTo(f.x - ft.y * 18, f.y + ft.x * 18);
    ctx.lineTo(f.x + ft.y * 18, f.y - ft.x * 18);
    ctx.stroke();
    ctx.fillStyle = "#333"; ctx.font = "bold 12px system-ui"; ctx.textAlign = "center";
    ctx.fillText("ゴール", f.x, f.y + 34);

    // コーナー表示 (ゴール直前のカーブ = 3〜4角)
    var cS = rightHanded ? finishS + L + curve / 2 : finishS - L - curve / 2;
    var cp = pathPoint(cS);
    ctx.fillStyle = "#444"; ctx.font = "11px system-ui";
    ctx.fillText("3〜4コーナー", cp.x, cp.y);

    ctx.fillStyle = "#555"; ctx.textAlign = "left"; ctx.font = "12px system-ui";
    ctx.fillText((data.venue || "") + "（" + (rightHanded ? "右回り" : "左回り") + " / " +
      (data.surface === "ダ" ? "ダート" : "芝") + (data.distance ? data.distance + "m" : "") + "）", 12, 20);
  }

  function rankAt(h, tf) {
    var i = Math.floor(tf), fr = tf - i;
    var a = h.rank_track[Math.min(i, ticks)], b = h.rank_track[Math.min(i + 1, ticks)];
    return a + (b - a) * fr;
  }

  var top3 = horses.filter(function (h) { return h.finish <= 3; }).map(function (h) { return h.num; });
  var playBtn = document.getElementById("animPlay");
  var replayBtn = document.getElementById("animReplay");
  var scrub = document.getElementById("animScrub");
  var label = document.getElementById("animLabel");
  var start = null, playing = false, pausedAt = 0;

  function draw(prog) {
    ctx.clearRect(0, 0, W, H);
    ctx.fillStyle = "#eef2f6"; ctx.fillRect(0, 0, W, H);
    drawTrack();

    var s0 = sAt(prog);
    var tf = prog * ticks;
    var laneGap = Math.min(9, (ry * 0.5) / Math.max(n, 6));
    var horsesSorted = horses.map(function (h, idx) { return { h: h, idx: idx, r: rankAt(h, tf) }; });

    horsesSorted.forEach(function (o) {
      var pt = pathPoint(s0);
      var tg = tangent(s0);
      // 法線方向 (トラック外側へ) にランクぶんオフセット
      var nx = -tg.y, ny = tg.x;
      var off = (o.r - 1) * laneGap - (n - 1) * laneGap / 2;
      var x = pt.x + nx * off, y = pt.y + ny * off;
      var col = PALETTE[o.idx % PALETTE.length];
      var dim = prog >= 0.999 && top3.indexOf(o.h.num) === -1;
      ctx.globalAlpha = dim ? 0.35 : 1;
      ctx.fillStyle = col;
      ctx.beginPath();
      ctx.arc(x, y, 8, 0, 2 * Math.PI);
      ctx.fill();
      ctx.fillStyle = "#fff"; ctx.font = "bold 10px system-ui"; ctx.textAlign = "center";
      ctx.fillText(o.h.num, x, y + 3.5);
      ctx.globalAlpha = 1;
    });

    // 着順リスト (右上)
    ctx.textAlign = "left"; ctx.font = "12px system-ui";
    var listed = horsesSorted.slice().sort(function (a, b) { return a.r - b.r; }).slice(0, 5);
    listed.forEach(function (o, i) {
      ctx.fillStyle = i < 3 ? "#333" : "#888";
      ctx.fillText((i + 1) + "  " + o.h.num + "." + o.h.name + " (" + o.h.style + ")", W - 232, 40 + i * 17);
    });

    var remain = Math.max(0, Math.round((data.distance || 1600) * (1 - prog) / 50) * 50);
    label.textContent = prog >= 0.999 ? "ゴール" : ("残り " + remain + "m");
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
