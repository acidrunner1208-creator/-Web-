/* 推奨買い目の期待値計算 + 買い目チェッカー (依存なし)
   window.__RACE__ = { horses:[馬番(予想順)], names:[馬名], podium:[p1,p2,p3, ...], podium_n }
*/
(function () {
  "use strict";
  var R = window.__RACE__;
  if (!R) return;

  var nums = R.horses.slice().map(Number);
  var nameByNum = {};
  R.horses.forEach(function (n, i) { nameByNum[n] = R.names[i]; });
  var sortedNums = nums.slice().sort(function (a, b) { return a - b; });

  // podium サンプル -> [{s:Set(top3), a:[p1,p2,p3]}]
  var P = R.podium || [];
  var samples = [];
  for (var i = 0; i + 2 < P.length; i += 3) {
    samples.push({ a: [P[i], P[i + 1], P[i + 2]], s: new Set([P[i], P[i + 1], P[i + 2]]) });
  }
  var NS = samples.length || 1;

  function comb(n, k) {
    if (k < 0 || k > n) return 0;
    var r = 1;
    for (var j = 0; j < k; j++) r = r * (n - j) / (j + 1);
    return Math.round(r);
  }

  // ---- 推奨買い目テーブルの期待値 ----
  function wireRecTable() {
    var rows = document.querySelectorAll("#recTable tbody tr");
    rows.forEach(function (tr) {
      var prob = parseFloat(tr.dataset.prob);
      var unit = parseFloat(tr.dataset.unit) || 1;
      var input = tr.querySelector(".odds-in");
      var evCell = tr.querySelector(".ev");
      if (!input) return;
      input.addEventListener("input", function () {
        var odds = parseFloat(input.value);
        if (!odds || odds <= 0) { evCell.textContent = "—"; evCell.className = "ev muted"; return; }
        var ev = prob * odds / unit - 1;
        evCell.textContent = (ev >= 0 ? "+" : "") + (ev * 100).toFixed(1) + "%";
        evCell.className = "ev " + (ev >= 0 ? "pos" : "neg");
      });
    });
  }

  // ---- 買い目チェッカー ----
  // 単勝〜ワイドは1つの馬番リストから選ぶ「フラット」型。
  // 3連複・3連単は 1〜3着それぞれの候補馬グループを選ぶ「フォーメーション」型のみに統一
  // (ボックス・軸1頭流しは廃止)。
  var TYPES = {
    tansho:   { kind: "flat", pick: [1, 1], label: "1着になる馬を1頭" },
    fukusho:  { kind: "flat", pick: [1, 1], label: "3着以内に入る馬を1頭" },
    umaren:   { kind: "flat", pick: [2, 2], label: "1・2着の2頭 (順不同)" },
    wide:     { kind: "flat", pick: [2, 8], label: "3着以内に入る馬を2頭以上 (ボックス)" },
    umatan:   { kind: "flat", pick: [2, 2], label: "1・2着の2頭 (着順どおり)" },
    sanrenpuku: { kind: "formation", ordered: false,
      label: "1〜3着それぞれの候補馬を選択（同じ馬を複数列に入れても可・順不同で的中判定）" },
    sanrentan: { kind: "formation", ordered: true,
      label: "1〜3着それぞれの候補馬を選択（同じ馬を複数列に入れても可・着順どおりで的中判定）" },
  };

  function hitRateFlat(type, picks) {
    var set = new Set(picks);
    var c = 0;
    for (var k = 0; k < samples.length; k++) {
      var sm = samples[k], a = sm.a, s = sm.s, ok = false;
      if (type === "tansho") ok = a[0] === picks[0];
      else if (type === "fukusho") ok = s.has(picks[0]);
      else if (type === "umaren") ok = (a[0] === picks[0] || a[0] === picks[1]) && (a[1] === picks[0] || a[1] === picks[1]);
      else if (type === "umatan") ok = (a[0] === picks[0] && a[1] === picks[1]) || (a[0] === picks[1] && a[1] === picks[0]);
      else if (type === "wide") { var n = 0; picks.forEach(function (p) { if (s.has(p)) n++; }); ok = n >= 2; }
      if (ok) c++;
    }
    return c / NS;
  }

  function pointsFlat(type, k) {
    if (type === "tansho" || type === "fukusho") return k >= 1 ? 1 : 0;
    if (type === "umaren") return k === 2 ? 1 : 0;
    if (type === "umatan") return k === 2 ? 2 : 0;
    if (type === "wide") return comb(k, 2);
    return 0;
  }

  // フォーメーション買い目の組合せ生成: g1/g2/g3 は各列で選んだ馬番の配列。
  // 3頭とも異なる馬になる組だけを採用。ordered=false (3連複) は重複組を除去。
  function formationCombos(g1, g2, g3, ordered) {
    var out = [], seen = ordered ? null : {};
    g1.forEach(function (a) {
      g2.forEach(function (b) {
        if (b === a) return;
        g3.forEach(function (c) {
          if (c === a || c === b) return;
          if (ordered) { out.push([a, b, c]); return; }
          var key = [a, b, c].slice().sort(function (x, y) { return x - y; }).join(",");
          if (!seen[key]) { seen[key] = true; out.push(key.split(",").map(Number)); }
        });
      });
    });
    return out;
  }

  function hitRateFormation(combos, ordered) {
    if (!combos.length) return 0;
    var keys = {};
    combos.forEach(function (c) {
      var k = ordered ? c.join(",") : c.slice().sort(function (x, y) { return x - y; }).join(",");
      keys[k] = true;
    });
    var hit = 0;
    for (var i = 0; i < samples.length; i++) {
      var a = samples[i].a;
      var key = ordered ? a.join(",") : a.slice().sort(function (x, y) { return x - y; }).join(",");
      if (keys[key]) hit++;
    }
    return hit / NS;
  }

  function initChecker() {
    var host = document.getElementById("betChecker");
    if (!host) return;
    var typeSel = document.getElementById("bcType");
    var horsesBox = document.getElementById("bcHorses");
    var hint = document.getElementById("bcHint");
    var probOut = document.getElementById("bcProb");
    var ptsOut = document.getElementById("bcPoints");
    var oddsIn = document.getElementById("bcOdds");
    var evOut = document.getElementById("bcEV");

    var formationBox = document.createElement("div");
    formationBox.className = "bc-formation";
    formationBox.style.display = "none";
    horsesBox.parentNode.insertBefore(formationBox, horsesBox.nextSibling);
    var groupLabels = ["1着候補", "2着候補", "3着候補"];
    var groups = groupLabels.map(function (label, gi) {
      var wrap = document.createElement("div");
      wrap.className = "bc-fgroup";
      var h = document.createElement("h4");
      h.textContent = label;
      wrap.appendChild(h);
      var list = document.createElement("div");
      list.className = "bc-horses";
      sortedNums.forEach(function (n) {
        var l = document.createElement("label");
        l.className = "bc-chk";
        l.innerHTML = "<input type='checkbox' data-g='" + gi + "' value='" + n + "'> " + n + "." + (nameByNum[n] || "");
        list.appendChild(l);
      });
      wrap.appendChild(list);
      formationBox.appendChild(wrap);
      return list;
    });

    sortedNums.forEach(function (n) {
      var l = document.createElement("label");
      l.className = "bc-chk";
      l.innerHTML = "<input type='checkbox' value='" + n + "'> " + n + "." + (nameByNum[n] || "");
      horsesBox.appendChild(l);
    });

    function groupPicks(gi) {
      return Array.prototype.slice.call(groups[gi].querySelectorAll("input:checked"))
        .map(function (c) { return Number(c.value); });
    }

    function recompute() {
      var type = typeSel.value;
      var spec = TYPES[type];
      hint.textContent = spec.label;
      var pr, pts;

      if (spec.kind === "formation") {
        horsesBox.style.display = "none";
        formationBox.style.display = "";
        var g1 = groupPicks(0), g2 = groupPicks(1), g3 = groupPicks(2);
        var combos = formationCombos(g1, g2, g3, spec.ordered);
        if (!combos.length) {
          probOut.textContent = "—"; ptsOut.textContent = "—";
          evOut.textContent = "—"; evOut.className = "muted";
          return;
        }
        pr = hitRateFormation(combos, spec.ordered);
        pts = combos.length;
      } else {
        horsesBox.style.display = "";
        formationBox.style.display = "none";
        var picks = Array.prototype.slice.call(horsesBox.querySelectorAll("input:checked"))
          .map(function (c) { return Number(c.value); });
        if (picks.length < spec.pick[0] || picks.length > spec.pick[1]) {
          probOut.textContent = "—"; ptsOut.textContent = "—";
          evOut.textContent = "—"; evOut.className = "muted";
          return;
        }
        pr = hitRateFlat(type, picks);
        pts = pointsFlat(type, picks.length);
      }

      probOut.textContent = (pr * 100).toFixed(1) + "%";
      ptsOut.textContent = pts + "点";
      var odds = parseFloat(oddsIn.value);
      if (odds && odds > 0 && pts > 0) {
        var ev = pr * odds / pts - 1;
        evOut.textContent = (ev >= 0 ? "+" : "") + (ev * 100).toFixed(1) + "%";
        evOut.className = ev >= 0 ? "pos" : "neg";
      } else { evOut.textContent = "—"; evOut.className = "muted"; }
    }

    typeSel.addEventListener("change", recompute);
    oddsIn.addEventListener("input", recompute);
    horsesBox.addEventListener("change", recompute);
    formationBox.addEventListener("change", recompute);
    recompute();
  }

  wireRecTable();
  initChecker();
})();
