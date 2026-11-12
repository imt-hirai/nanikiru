(function () {
  'use strict';

  var WINDS = ['東', '南', '西', '北'];
  var REL = ['自分', '下家', '対面', '上家'];
  var RED_KIND = [4, 13, 22];
  var STORE_KEY = 'nanikiru.results.v1';

  function kindOf(id) { return id >= 34 ? RED_KIND[id - 34] : id; }

  function kindName(k) {
    if (k < 9) return (k + 1) + '萬';
    if (k < 18) return (k - 8) + '筒';
    if (k < 27) return (k - 17) + '索';
    return ['東', '南', '西', '北', '白', '發', '中'][k - 27];
  }
  function tileName(id) { return (id >= 34 ? '赤' : '') + kindName(kindOf(id)); }

  // Unicode 麻雀牌 (U+1F000〜)。末尾の U+FE0E は絵文字化を防ぐテキスト表示指定
  function glyph(k) {
    var cp;
    if (k < 9) cp = 0x1F007 + k;            // 一萬〜九萬
    else if (k < 18) cp = 0x1F019 + (k - 9);  // 一筒〜九筒
    else if (k < 27) cp = 0x1F010 + (k - 18); // 一索〜九索
    else if (k < 31) cp = 0x1F000 + (k - 27); // 東南西北
    else cp = (k === 31) ? 0x1F006 : (k === 32) ? 0x1F005 : 0x1F004; // 白發中
    return String.fromCodePoint(cp) + '︎';
  }
  function suitClass(k) { return k < 9 ? 's-m' : k < 18 ? 's-p' : k < 27 ? 's-s' : 's-z'; }

  function doraOf(ind) {
    if (ind < 27) return (ind % 9 === 8) ? ind - 8 : ind + 1;
    if (ind < 31) return 27 + (ind - 27 + 1) % 4;
    return 31 + (ind - 31 + 1) % 3;
  }

  function el(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text != null) e.textContent = text;
    return e;
  }

  function tileEl(id, opt) {
    opt = opt || {};
    var k = kindOf(id);
    var e = el(opt.button ? 'button' : 'span', 'tile ' + suitClass(k) + (id >= 34 ? ' red' : '') + (opt.size ? ' ' + opt.size : ''), glyph(k));
    if (opt.button) e.type = 'button';
    e.title = tileName(id);
    e.setAttribute('aria-label', tileName(id));
    if (id >= 34) e.appendChild(el('i', 'aka', '赤'));
    return e;
  }

  // ---------- 保存 ----------
  var results = {};
  try { results = JSON.parse(localStorage.getItem(STORE_KEY) || '{}') || {}; } catch (e) { results = {}; }
  function save() { try { localStorage.setItem(STORE_KEY, JSON.stringify(results)); } catch (e) { /* 無視 */ } }

  var total = PROBLEMS.length;
  var cur = 0;

  var $ = function (id) { return document.getElementById(id); };

  // ---------- 成績 ----------
  function renderStats() {
    var n = 0, r1 = 0, r2 = 0, r3 = 0, pts = 0;
    PROBLEMS.forEach(function (p) {
      var r = results[p.id];
      if (!r) return;
      n++;
      if (r.rank === 1) { r1++; pts += 3; } else if (r.rank === 2) { r2++; pts += 2; } else if (r.rank === 3) { r3++; pts += 1; }
    });
    var box = $('stats');
    box.textContent = '';
    function item(label, val) {
      var s = el('span');
      s.appendChild(document.createTextNode(label + ' '));
      s.appendChild(el('b', null, val));
      box.appendChild(s);
    }
    item('回答済', n + ' / ' + total);
    item('1位一致', r1 + (n ? '（' + Math.round(r1 * 100 / n) + '%）' : ''));
    item('2位', String(r2));
    item('3位', String(r3));
    item('得点', pts + '点');
  }

  // ---------- 問題表示 ----------
  function buildJump() {
    var sel = $('jump');
    sel.textContent = '';
    PROBLEMS.forEach(function (p, i) {
      var o = el('option', null, '第' + p.id + '問');
      o.value = String(i);
      sel.appendChild(o);
    });
  }
  function refreshJumpMarks() {
    var opts = $('jump').options;
    for (var i = 0; i < opts.length; i++) {
      var p = PROBLEMS[i], r = results[p.id];
      var mark = !r ? '' : (r.rank === 1 ? ' ◎' : r.rank === 2 ? ' ○' : r.rank === 3 ? ' △' : ' ×');
      opts[i].textContent = '第' + p.id + '問' + mark;
    }
  }

  function render() {
    var p = PROBLEMS[cur];
    $('q-title').textContent = '第' + p.id + '問 / ' + total + '問';
    $('jump').value = String(cur);
    $('btn-prev').disabled = cur === 0;
    $('btn-next').disabled = cur === total - 1;
    if (location.hash !== '#' + p.id) history.replaceState(null, '', '#' + p.id);

    // チップ
    var chips = $('chips');
    chips.textContent = '';
    chips.appendChild(el('span', 'chip', WINDS[p.roundWind] + p.kyoku + '局'));
    chips.appendChild(el('span', 'chip', p.honba + '本場'));
    chips.appendChild(el('span', 'chip', '供託 ' + p.kyou + '本'));
    chips.appendChild(el('span', 'chip ' + (p.dealer ? 'dealer' : 'child'), p.dealer ? '親' : '子'));
    chips.appendChild(el('span', 'chip', '自風：' + WINDS[p.myWind]));
    chips.appendChild(el('span', 'chip', '場風：' + WINDS[p.roundWind]));
    chips.appendChild(el('span', 'chip', p.turn + '巡目'));

    // 4人の点数（自分=下、下家=右、対面=上、上家=左）
    var tbl = $('table');
    tbl.textContent = '';
    var cls = ['p-me', 'p-right', 'p-top', 'p-left'];
    var rankOf = function (i) { return 1 + p.scores.filter(function (x) { return x > p.scores[i]; }).length; };
    for (var i = 0; i < 4; i++) {
      var w = (p.myWind + i) % 4;
      var seat = p.seats[i];
      var box = el('div', 'pl ' + cls[i] + (i === 0 ? ' me' : ''));
      var head = el('div', 'pl-head');
      head.appendChild(el('span', 'nm', REL[i] + '（' + rankOf(i) + '位）'));
      var wd = el('span', 'wd', WINDS[w] + '家');
      if (w === 0) wd.appendChild(el('span', 'oya', '親'));
      head.appendChild(wd);
      if (seat.riichi >= 0) head.appendChild(el('span', 'rii', 'リーチ'));
      box.appendChild(head);
      box.appendChild(el('div', 'sc', p.scores[i].toLocaleString()));

      if (seat.melds.length) {
        var ml = el('div', 'melds');
        seat.melds.forEach(function (m) {
          var g = el('span', 'meld');
          g.appendChild(el('small', null, m.type === 'pon' ? 'ポン' : 'チー'));
          m.tiles.forEach(function (t, ti) {
            var te = tileEl(t, { size: 'xs' });
            if (ti === m.called) te.classList.add('sideways');
            g.appendChild(te);
          });
          ml.appendChild(g);
        });
        box.appendChild(ml);
      }

      var rv = el('div', 'river');
      seat.river.forEach(function (t, ti) {
        var cell = el('span', 'rc');
        var te = tileEl(t, { size: 'xs' });
        if (ti === seat.riichi) { te.classList.add('sideways'); te.classList.add('riichi'); }
        cell.appendChild(te);
        rv.appendChild(cell);
      });
      box.appendChild(rv);
      tbl.appendChild(box);
    }
    var c = el('div', 'center');
    c.appendChild(el('div', 'rd', WINDS[p.roundWind] + p.kyoku + '局'));
    c.appendChild(el('div', 'sub', p.honba + '本場 / 供託' + p.kyou + '本'));
    c.appendChild(el('div', 'sub', p.turn + '巡目'));
    tbl.appendChild(c);

    // ドラ
    var ind = $('indicator'); ind.textContent = '';
    ind.appendChild(tileEl(p.indicator, { size: 'sm' }));
    var dr = $('dora'); dr.textContent = '';
    dr.appendChild(tileEl(doraOf(kindOf(p.indicator)), { size: 'sm' }));

    // 手牌
    var res = results[p.id];
    var hand = $('hand'); hand.textContent = '';
    var rankMap = {};
    p.answers.slice(0, 3).forEach(function (a, idx) { rankMap[a.t] = idx + 1; });

    function addTile(id, isTsumo) {
      var t = tileEl(id, { button: true });
      if (res) {
        t.disabled = true;
        if (rankMap[id]) {
          var b = el('span', 'badge r' + rankMap[id], rankMap[id] + '位');
          t.appendChild(b);
        } else if (res.pick !== id) {
          t.classList.add('dim');
        }
        if (res.pick === id) t.classList.add('picked');
      } else {
        t.addEventListener('click', function () { answer(id); });
      }
      hand.appendChild(t);
    }
    p.hand.forEach(function (id) { addTile(id, false); });
    hand.appendChild(el('span', 'gap'));
    addTile(p.tsumo, true);

    $('prompt').hidden = !!res;
    renderResult(p, res);
    refreshJumpMarks();
    renderStats();
  }

  function answer(id) {
    var p = PROBLEMS[cur];
    var idx = -1;
    p.answers.forEach(function (a, i) { if (a.t === id) idx = i; });
    results[p.id] = { pick: id, rank: idx >= 0 && idx < 3 ? idx + 1 : 0, pos: idx + 1 };
    save();
    render();
    $('result').scrollIntoView({ behavior: 'smooth', block: 'start' });
  }

  function fmt(n) { return n.toLocaleString(); }
  function signed(n) { return (n > 0 ? '+' : '') + n.toLocaleString(); }
  function hasThreat(p) {
    return p.seats.some(function (s) { return s.riichi >= 0 || s.melds.length > 0; });
  }
  function shLabel(s) { return s === 0 ? 'テンパイ' : s + 'シャンテン'; }

  function renderResult(p, res) {
    var box = $('result');
    box.textContent = '';
    if (!res) { box.hidden = true; return; }
    box.hidden = false;

    var v = el('div', 'verdict v' + res.rank);
    var marks = ['×', '◎', '○', '△'];
    v.appendChild(el('span', 'mark', marks[res.rank]));
    var vt = el('div');
    var title = res.rank === 1 ? '1位の打牌です！' : res.rank === 2 ? '2位の打牌です' : res.rank === 3 ? '3位の打牌です' : '3位以内に入りませんでした';
    vt.appendChild(document.createTextNode(title));
    vt.appendChild(el('small', null, 'あなたの選択：' + tileName(res.pick) + '（全' + p.answers.length + '択中 ' + res.pos + '位）'));
    v.appendChild(vt);
    box.appendChild(v);

    box.appendChild(el('h2', null, '何切る 順位（上位3つ）'));

    p.answers.slice(0, 3).forEach(function (a, i) {
      var r = el('div', 'rank r' + (i + 1) + (a.t === res.pick ? ' mine' : ''));
      var medal = el('div', 'medal');
      medal.appendChild(el('b', null, (i + 1) + '位'));
      medal.appendChild(tileEl(a.t, { size: 'sm' }));
      r.appendChild(medal);

      var body = el('div');
      var h = el('h3', null, '打 ' + tileName(a.t));
      if (a.t === res.pick) h.appendChild(el('span', 'you', 'あなたの選択'));
      body.appendChild(h);

      var m = el('div', 'metrics');
      var mets = [['', shLabel(a.s)], ['受け入れ ', a.n + '枚'], ['打点目安 ', fmt(a.pts) + '点'],
        ['和了率目安 ', a.p + '%']];
      if (hasThreat(p)) mets.push(['放銃率目安 ', a.risk + '%']);
      mets.push(['期待収支 ', signed(a.ev) + '点']);
      mets.forEach(function (x) {
        var s = el('span');
        s.appendChild(document.createTextNode(x[0]));
        s.appendChild(el('b', null, x[1]));
        m.appendChild(s);
      });
      body.appendChild(m);

      var ul = el('ul');
      (a.why || []).forEach(function (t) { ul.appendChild(el('li', null, t)); });
      body.appendChild(ul);

      if (a.w && a.w.length) {
        var w = el('div', 'waits');
        w.appendChild(document.createTextNode(a.s === 0 ? '待ち：' : '有効牌：'));
        a.w.forEach(function (x) {
          var cell = el('span', 'w');
          cell.appendChild(tileEl(x[0], { size: 'xs' }));
          cell.appendChild(document.createTextNode(x[1] + '枚'));
          w.appendChild(cell);
        });
        body.appendChild(w);
      }
      r.appendChild(body);
      box.appendChild(r);
    });

    if (p.notes && p.notes.length) {
      var nb = el('div', 'notes');
      nb.appendChild(el('strong', null, 'この局面のポイント'));
      var nu = el('ul');
      p.notes.forEach(function (t) { nu.appendChild(el('li', null, t)); });
      nb.appendChild(nu);
      box.appendChild(nb);
    }

    // 全打牌
    var det = el('details', 'others');
    det.appendChild(el('summary', null, '全ての打牌の評価を見る（' + p.answers.length + '択）'));
    var tbl = el('table', 'all');
    var head = el('tr');
    var cols = ['順位 / 打牌', 'シャンテン', '受け入れ', '打点目安', '和了率'];
    if (hasThreat(p)) cols.push('放銃率');
    cols.push('期待収支');
    cols.forEach(function (t) { head.appendChild(el('th', null, t)); });
    tbl.appendChild(head);
    p.answers.forEach(function (a, i) {
      var tr = el('tr', a.t === res.pick ? 'mine' : '');
      tr.appendChild(el('td', null, (i + 1) + '位　' + tileName(a.t)));
      tr.appendChild(el('td', null, shLabel(a.s)));
      tr.appendChild(el('td', null, a.n + '枚'));
      tr.appendChild(el('td', null, fmt(a.pts)));
      tr.appendChild(el('td', null, a.p + '%'));
      if (hasThreat(p)) tr.appendChild(el('td', null, a.risk + '%'));
      tr.appendChild(el('td', null, signed(a.ev)));
      tbl.appendChild(tr);
    });
    det.appendChild(tbl);
    box.appendChild(det);

    var act = el('div', 'result-actions');
    var nx = el('button', 'btn', cur < total - 1 ? '次の問題へ →' : '最初の問題へ');
    nx.type = 'button';
    nx.addEventListener('click', function () { go(cur < total - 1 ? cur + 1 : 0); });
    act.appendChild(nx);
    var rt = el('button', 'btn ghost', 'この問題をやり直す');
    rt.type = 'button';
    rt.style.cssText = 'background:#fff;color:#14532d';
    rt.addEventListener('click', function () { delete results[p.id]; save(); render(); window.scrollTo({ top: 0, behavior: 'smooth' }); });
    act.appendChild(rt);
    box.appendChild(act);
  }

  function go(i) {
    cur = Math.max(0, Math.min(total - 1, i));
    render();
    window.scrollTo({ top: 0 });
  }

  function randomUnanswered() {
    var left = [];
    PROBLEMS.forEach(function (p, i) { if (!results[p.id]) left.push(i); });
    if (!left.length) { alert('全問回答済みです。成績をリセットするともう一度挑戦できます。'); return; }
    go(left[Math.floor(Math.random() * left.length)]);
  }

  // ---------- 初期化 ----------
  buildJump();
  $('btn-prev').addEventListener('click', function () { go(cur - 1); });
  $('btn-next').addEventListener('click', function () { go(cur + 1); });
  $('btn-random').addEventListener('click', randomUnanswered);
  $('jump').addEventListener('change', function (e) { go(parseInt(e.target.value, 10)); });
  $('btn-reset').addEventListener('click', function () {
    if (confirm('回答履歴と成績をすべてリセットしますか？')) { results = {}; save(); render(); }
  });
  window.addEventListener('keydown', function (e) {
    if (e.target && (e.target.tagName === 'SELECT' || e.target.tagName === 'INPUT')) return;
    if (e.key === 'ArrowLeft') go(cur - 1);
    if (e.key === 'ArrowRight') go(cur + 1);
  });

  var start = 0;
  var m = /^#(\d+)$/.exec(location.hash);
  if (m) {
    var n = parseInt(m[1], 10);
    PROBLEMS.forEach(function (p, i) { if (p.id === n) start = i; });
  } else {
    // 未回答の最初の問題から
    for (var i = 0; i < PROBLEMS.length; i++) { if (!results[PROBLEMS[i].id]) { start = i; break; } }
  }
  go(start);
})();
