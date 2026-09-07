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
  var TYPES = {
    tansho:   { pick: [1, 1],  axis: false, label: "1着になる馬を1頭" },
    fukusho:  { pick: [1, 1],  axis: false, label: "3着以内に入る馬を1頭" },
    umaren:   { pick: [2, 2],  axis: false, label: "1・2着の2頭 (順不同)" },
    wide:     { pick: [2, 8],  axis: false, label: "3着以内に入る馬を2頭以上 (ボックス)" },
    umatan:   { pick: [2, 2],  axis: false, label: "1・2着の2頭 (両方向)" },
    sanrenpuku: { pick: [3, 10], axis: false, label: "3着以内の3頭を含む組合せ (ボックス)" },
    sanrenpuku_nagashi: { pick: [3, 9], axis: true, label: "軸1頭 + 相手2頭以上" },
    sanrentan: { pick: [3, 8], axis: false, label: "1〜3着に入る馬 (ボックス)" },
  };

  function hitRate(type, picks, axis) {
    var set = new Set(picks);
    var c = 0;
    for (var k = 0; k < samples.length; k++) {
      var sm = samples[k], a = sm.a, s = sm.s, ok = false;
      if (type === "tansho") ok = a[0] === picks[0];
      else if (type === "fukusho") ok = s.has(picks[0]);
      else if (type === "umaren") ok = (a[0] === picks[0] || a[0] === picks[1]) && (a[1] === picks[0] || a[1] === picks[1]);
      else if (type === "umatan") ok = (a[0] === picks[0] && a[1] === picks[1]) || (a[0] === picks[1] && a[1] === picks[0]);
      else if (type === "wide") { var n = 0; picks.forEach(function (p) { if (s.has(p)) n++; }); ok = n >= 2; }
      else if (type === "sanrenpuku") ok = s.has(a[0]) && s.has(a[1]) && s.has(a[2]) && set.has(a[0]) && set.has(a[1]) && set.has(a[2]);
      else if (type === "sanrentan") ok = set.has(a[0]) && set.has(a[1]) && set.has(a[2]);
      else if (type === "sanrenpuku_nagashi") {
        if (!s.has(axis)) ok = false;
        else { var m = 0; picks.forEach(function (p) { if (p !== axis && s.has(p)) m++; }); ok = m >= 2; }
      }
      if (ok) c++;
    }
    return c / NS;
  }

  function points(type, k, axisSet) {
    if (type === "tansho" || type === "fukusho") return k >= 1 ? 1 : 0;
    if (type === "umaren") return k === 2 ? 1 : 0;
    if (type === "umatan") return k === 2 ? 2 : 0;
    if (type === "wide") return comb(k, 2);
    if (type === "sanrenpuku") return comb(k, 3);
    if (type === "sanrentan") return k * (k - 1) * (k - 2);
    if (type === "sanrenpuku_nagashi") return comb(Math.max(k - 1, 0), 2);
    return 0;
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
    var axisWrap = document.createElement("label");
    axisWrap.className = "bc-axis";
    axisWrap.style.display = "none";
    axisWrap.innerHTML = "軸馬 <select id='bcAxis'></select>";
    typeSel.parentNode.parentNode.insertBefore(axisWrap, horsesBox);

    sortedNums.forEach(function (n) {
      var l = document.createElement("label");
      l.className = "bc-chk";
      l.innerHTML = "<input type='checkbox' value='" + n + "'> " + n + "." + (nameByNum[n] || "");
      horsesBox.appendChild(l);
    });
    var axisSel = axisWrap.querySelector("#bcAxis");
    sortedNums.forEach(function (n) {
      var o = document.createElement("option");
      o.value = n; o.textContent = n + "." + (nameByNum[n] || "");
      axisSel.appendChild(o);
    });

    function recompute() {
      var type = typeSel.value;
      var spec = TYPES[type];
      hint.textContent = spec.label;
      axisWrap.style.display = spec.axis ? "" : "none";
      var picks = Array.prototype.slice.call(horsesBox.querySelectorAll("input:checked"))
        .map(function (c) { return Number(c.value); });
      var axis = spec.axis ? Number(axisSel.value) : null;
      if (spec.axis && axis != null && picks.indexOf(axis) === -1) picks.push(axis);

      if (picks.length < spec.pick[0] || picks.length > spec.pick[1]) {
        probOut.textContent = "—"; ptsOut.textContent = "—";
        evOut.textContent = "—"; evOut.className = "muted";
        return;
      }
      var pr = hitRate(type, picks, axis);
      var pts = points(type, picks.length, axis);
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
    axisSel.addEventListener("change", recompute);
    horsesBox.addEventListener("change", recompute);
    recompute();
  }

  wireRecTable();
  initChecker();
})();
