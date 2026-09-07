/* レース展開アニメーション (依存なし)
   window.__RACE_ANIM__ = {
     ticks, distance, direction, venue, surface, pace, pace_note,
     horses: [{ num, name, style, draw, rank_track:[...], pos_track:[0..1...], finish }]
   }

   表示は 2 段構成:
   - 上: コースのミニマップ (各競馬場の形状を再現。隊列の「現在地」を点で表示)
   - 下: レーン・ストリップ。横 = 進んだ距離 (右がゴール)、縦 = 枠順で固定したレーン。
        馬同士が絶対に重ならないので前後関係 = 隊列がそのまま読める。奥行き感のため
        進むほどマーカーを少し大きく描き、遠近のレーン線を添える。
*/
(function () {
  "use strict";
  var data = window.__RACE_ANIM__;
  var canvas = document.getElementById("raceCanvas");
  if (!data || !canvas || !data.horses || !data.horses.length) return;

  var ctx = canvas.getContext("2d");
  var W = canvas.width, H = canvas.height;
  var ticks = data.ticks;
  var D = data.distance || 1600;
  var DUR = 11000, HOLD = 2200;

  // 枠順で安定ソート (上のレーン = 内枠)
  var horses = data.horses.slice().sort(function (a, b) {
    return (a.draw || a.num) - (b.draw || b.num) || a.num - b.num;
  });
  var n = horses.length;

  var PALETTE = ["#d64545","#3f6fb0","#4a9d63","#c98a2b","#8a5cb4","#2aa4a4","#c0577f",
    "#6b8e23","#b5651d","#5b7db1","#7a9e3a","#a34a8f","#3d8f8f","#9c6b3f","#5f6caf",
    "#c05b5b","#4f9a4f","#b98a3a"];
  var colorOf = {};
  horses.forEach(function (h, i) { colorOf[h.num] = PALETTE[i % PALETTE.length]; });

  var GEO = {
    "東京":{w:0.95,h:0.58,straight:0.62,lap:2000}, "中山":{w:0.72,h:0.74,straight:0.30,lap:1800},
    "阪神":{w:0.85,h:0.62,straight:0.44,lap:1800}, "京都":{w:0.90,h:0.58,straight:0.44,lap:1900},
    "中京":{w:0.80,h:0.64,straight:0.48,lap:1700}, "新潟":{w:0.97,h:0.48,straight:0.68,lap:2000},
    "福島":{w:0.68,h:0.76,straight:0.32,lap:1700}, "小倉":{w:0.66,h:0.76,straight:0.28,lap:1650},
    "札幌":{w:0.78,h:0.68,straight:0.38,lap:1650}, "函館":{w:0.62,h:0.78,straight:0.26,lap:1600}
  };
  var g = GEO[data.venue] || {w:0.82,h:0.64,straight:0.46,lap:1800};
  var rightHanded = (data.direction || "").indexOf("右") >= 0;

  function interp(arr, tf) {
    var i = Math.floor(tf), fr = tf - i;
    var a = arr[Math.min(i, ticks)], b = arr[Math.min(i + 1, ticks)];
    return a + (b - a) * fr;
  }

  // ---------- ミニマップ用スタジアム形 ----------
  function makeCourse(cx, cy, rx, ry, straight) {
    var L = Math.max(16, straight * 2 * rx), curve = Math.PI * ry;
    var perim = 2 * L + 2 * curve, finishS = L;
    function pp(s) {
      s = ((s % perim) + perim) % perim;
      if (s <= L) return { x: cx - L / 2 + s, y: cy + ry };
      s -= L;
      if (s <= curve) { var a = (s / curve) * Math.PI; return { x: cx + L / 2 + ry * Math.sin(a), y: cy + ry * Math.cos(a) }; }
      s -= curve;
      if (s <= L) return { x: cx + L / 2 - s, y: cy - ry };
      s -= L; var b = (s / curve) * Math.PI;
      return { x: cx - L / 2 - ry * Math.sin(b), y: cy - ry * Math.cos(b) };
    }
    return { pp: pp, perim: perim, finishS: finishS };
  }

  var MM = { x: 20, y: 14, w: 210, h: 104 };
  var mmc = makeCourse(MM.x + MM.w / 2, MM.y + MM.h / 2, g.w * (MM.w / 2 - 10),
                       g.h * (MM.h / 2 - 10), g.straight);
  var mmRaceLen = Math.min(0.97, D / g.lap) * mmc.perim;
  function mmSAt(frac) {
    return rightHanded ? mmc.finishS + (1 - frac) * mmRaceLen
                       : mmc.finishS - (1 - frac) * mmRaceLen;
  }

  function drawMinimap(items, leadNum) {
    ctx.save();
    ctx.strokeStyle = "#c7d0d8"; ctx.lineWidth = 9; ctx.lineJoin = "round";
    ctx.beginPath();
    for (var s = 0; s <= mmc.perim; s += 5) {
      var p = mmc.pp(s); if (s === 0) ctx.moveTo(p.x, p.y); else ctx.lineTo(p.x, p.y);
    }
    ctx.closePath(); ctx.stroke();
    ctx.strokeStyle = (data.surface === "ダ") ? "#c69c6a" : "#8fb87a"; ctx.lineWidth = 5; ctx.stroke();

    var f = mmc.pp(mmc.finishS);
    ctx.fillStyle = "#e23"; ctx.beginPath(); ctx.arc(f.x, f.y, 2.6, 0, 7); ctx.fill();

    items.forEach(function (o) {
      var p = mmc.pp(mmSAt(o.pr));
      var lead = o.h.num === leadNum;
      ctx.beginPath(); ctx.arc(p.x, p.y, lead ? 4 : 2.7, 0, 7);
      ctx.fillStyle = colorOf[o.h.num]; ctx.fill();
      if (lead) { ctx.strokeStyle = "#fff"; ctx.lineWidth = 1.5; ctx.stroke(); }
    });

    ctx.fillStyle = "#5b6b7a"; ctx.font = "10px system-ui"; ctx.textAlign = "left";
    ctx.fillText((data.venue || "") + "　" + (rightHanded ? "右回り" : "左回り") + "　" +
      (data.surface === "ダ" ? "ダート" : "芝") + D + "m", MM.x, MM.y + MM.h + 12);
    ctx.restore();
  }

  // ---------- レーン・ストリップ ----------
  var GUT = 150;                       // 左の馬名ラベル幅
  var SX0 = GUT + 6, SX1 = W - 74;     // 走路の左右
  var SY0 = 150, SY1 = H - 18;         // 走路の上下
  var laneH = (SY1 - SY0) / n;
  var vanish = { x: SX0 - 520, y: (SY0 + SY1) / 2 };   // 遠近の消失点 (左奥)

  function laneY(i) { return SY0 + laneH * (i + 0.5); }
  function progX(pr) { return SX0 + Math.max(-0.03, Math.min(1.03, pr)) * (SX1 - SX0); }

  function drawStrip(items, prog, leadPr, leadNum) {
    // 走路の地色 (上=奥 を少し暗く)
    var grad = ctx.createLinearGradient(0, SY0, 0, SY1);
    var base = (data.surface === "ダ") ? ["#b98f5e", "#d8b483"] : ["#6f9e5e", "#93bd7c"];
    grad.addColorStop(0, base[0]); grad.addColorStop(1, base[1]);
    ctx.fillStyle = grad;
    ctx.fillRect(SX0 - 4, SY0, SX1 - SX0 + 8, SY1 - SY0);

    // 遠近のレーン線 (消失点へ収束)
    ctx.strokeStyle = "rgba(255,255,255,.18)"; ctx.lineWidth = 1;
    for (var i = 0; i <= n; i++) {
      var y = SY0 + laneH * i;
      ctx.beginPath(); ctx.moveTo(SX1, y);
      ctx.lineTo(vanish.x, vanish.y + (y - vanish.y) * 0.12);
      ctx.stroke();
    }
    // 距離目盛り (200m 毎)
    ctx.fillStyle = "#7a8790"; ctx.font = "10px system-ui"; ctx.textAlign = "center";
    var step = D > 2000 ? 400 : 200;
    for (var m = 0; m <= D; m += step) {
      var gx = progX(m / D);
      ctx.strokeStyle = "rgba(255,255,255,.28)";
      ctx.beginPath(); ctx.moveTo(gx, SY0); ctx.lineTo(gx, SY1); ctx.stroke();
      ctx.fillText((D - m) + "m", gx, SY0 - 6);
    }
    ctx.textAlign = "left"; ctx.fillText("スタート", SX0, SY0 - 20);
    ctx.textAlign = "right"; ctx.fillText("ゴール", SX1, SY0 - 20);

    // ゴール標識
    ctx.fillStyle = "#fff"; ctx.fillRect(SX1 - 2, SY0, 4, SY1 - SY0);
    for (var k = 0; k < (SY1 - SY0) / 8; k++) {
      ctx.fillStyle = k % 2 ? "#111" : "#fff";
      ctx.fillRect(SX1 + 2, SY0 + k * 8, 8, 8);
    }

    // 先頭ライン
    var lx = progX(leadPr);
    ctx.strokeStyle = "rgba(20,20,20,.35)"; ctx.setLineDash([4, 4]); ctx.lineWidth = 1.5;
    ctx.beginPath(); ctx.moveTo(lx, SY0); ctx.lineTo(lx, SY1); ctx.stroke();
    ctx.setLineDash([]);

    var atFinish = prog >= 0.999;
    items.forEach(function (o, idx) {
      var y = laneY(idx);
      var x = progX(o.pr);
      var col = colorOf[o.h.num];
      var r = 6.5 + 3.2 * Math.max(0, Math.min(1, o.pr));    // 進むほど大きく (奥行き感)
      var dim = atFinish && o.h.finish > 3;

      // ラベル (左ガター)
      ctx.globalAlpha = dim ? 0.4 : 1;
      ctx.fillStyle = col; ctx.fillRect(6, y - 7, 5, 14);
      ctx.fillStyle = dim ? "#999" : "#2a2f34";
      ctx.font = (o.h.finish <= 3 && atFinish ? "bold " : "") + "11px system-ui";
      ctx.textAlign = "left";
      ctx.fillText(o.h.num + " " + clip(o.h.name, 7), 16, y + 3.5);

      // 影 + 馬マーカー (右向きのしずく形)
      ctx.fillStyle = "rgba(0,0,0,.16)";
      ctx.beginPath(); ctx.ellipse(x + 1, y + r * 0.55, r * 1.05, r * 0.5, 0, 0, 7); ctx.fill();
      ctx.fillStyle = col;
      ctx.strokeStyle = "rgba(255,255,255,.95)"; ctx.lineWidth = 1.6;
      ctx.beginPath();
      ctx.moveTo(x + r * 1.5, y);
      ctx.quadraticCurveTo(x + r * 0.4, y - r, x - r * 0.7, y - r * 0.6);
      ctx.quadraticCurveTo(x - r * 1.1, y, x - r * 0.7, y + r * 0.6);
      ctx.quadraticCurveTo(x + r * 0.4, y + r, x + r * 1.5, y);
      ctx.fill(); ctx.stroke();
      ctx.fillStyle = "#fff"; ctx.font = "bold " + (r + 1) + "px system-ui"; ctx.textAlign = "center";
      ctx.fillText(o.h.num, x + r * 0.15, y + r * 0.4);
      ctx.globalAlpha = 1;
    });
  }

  function clip(s, k) { return (s && s.length > k) ? s.slice(0, k) : (s || ""); }

  // ---------- 状態 & ループ ----------
  var playBtn = document.getElementById("animPlay");
  var replayBtn = document.getElementById("animReplay");
  var scrub = document.getElementById("animScrub");
  var label = document.getElementById("animLabel");
  var start = null, playing = false, pausedAt = 0;

  function compute(tf) {
    var arr = horses.map(function (h) {
      return { h: h, pr: interp(h.pos_track, tf) };
    });
    var lead = arr.slice().sort(function (a, b) { return b.pr - a.pr; })[0];
    return { items: arr, leadPr: lead.pr, leadNum: lead.h.num,
             order: arr.slice().sort(function (a, b) { return b.pr - a.pr; }) };
  }

  function draw(prog) {
    ctx.clearRect(0, 0, W, H);
    ctx.fillStyle = "#eef2f6"; ctx.fillRect(0, 0, W, H);
    var st = compute(prog * ticks);

    drawStrip(st.items, prog, st.leadPr, st.leadNum);
    drawMinimap(st.items, st.leadNum);

    // 現在の隊列順 (ミニマップ右)
    ctx.textAlign = "left"; ctx.font = "11px system-ui";
    var bx = MM.x + MM.w + 18;
    ctx.fillStyle = "#333"; ctx.font = "bold 11px system-ui";
    ctx.fillText(prog >= 0.999 ? "着順" : "現在の隊列", bx, MM.y + 12);
    ctx.font = "11px system-ui";
    st.order.slice(0, 6).forEach(function (o, i) {
      ctx.fillStyle = i < 3 ? colorOf[o.h.num] : "#888";
      ctx.fillText((i + 1) + "  " + o.h.num + ". " + clip(o.h.name, 8) + "（" + o.h.style + "）",
        bx, MM.y + 30 + i * 14);
    });

    var remain = Math.max(0, Math.round(D * (1 - st.leadPr) / 50) * 50);
    label.textContent = prog >= 0.999 ? "ゴール" : ("先頭 残り約 " + remain + "m");
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
