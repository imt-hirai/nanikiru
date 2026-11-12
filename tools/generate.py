#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
何切る問題ジェネレータ（赤ありリーグルール・門前想定）

  python3 tools/generate.py            # web/problems.js を再生成（200問）
  python3 tools/generate.py --count 50 --seed 1

牌の表現
  0-8   : 1-9萬      9-17 : 1-9筒      18-26 : 1-9索
  27-30 : 東南西北   31 : 白  32 : 發  33 : 中
  34/35/36 : 赤5萬 / 赤5筒 / 赤5索（kind は 4 / 13 / 22）

評価方法（簡易モデル）
  各打牌について
    1) シャンテン数と受け入れ枚数（2手先の受け入れ含む）から、残り巡目内の和了率を推定
    2) ドラ・赤・立直・役牌・タンヤオ・染め手・三色/一通・七対子見込みから打点を推定
    3) 点数状況（トップ目/ラス目 × 終盤）で打点の重みを補正
  評価値 = 和了率 × 打点^α  の大きい順に 1〜3 位を決定する。
  ※AI(Mortal等)の厳密な解ではなく、学習用の目安。
"""
import argparse
import json
import math
import os
import random
import sys

RED_KIND = [4, 13, 22]
YAO = [0, 8, 9, 17, 18, 26] + list(range(27, 34))


def kind_of(i):
    return RED_KIND[i - 34] if i >= 34 else i


def kind_name(k):
    if k < 9:
        return "%d萬" % (k + 1)
    if k < 18:
        return "%d筒" % (k - 8)
    if k < 27:
        return "%d索" % (k - 17)
    return ["東", "南", "西", "北", "白", "發", "中"][k - 27]


def tile_name(i):
    return ("赤" if i >= 34 else "") + kind_name(kind_of(i))


# ---------------------------------------------------------------- シャンテン
_memo = {}


_suit_cache = {}


def _suit_opts(t9, seq):
    """1スート(または字牌)の (面子数, ターツ数, 雀頭有無) の取り得る組合せ"""
    key = (t9, seq)
    r = _suit_cache.get(key)
    if r is not None:
        return r
    a = list(t9)
    n = len(a)
    res = set()

    def dfs(i, m, t, p):
        while i < n and a[i] == 0:
            i += 1
        if i >= n:
            res.add((m, t, p))
            return
        if a[i] >= 3:
            a[i] -= 3
            dfs(i, m + 1, t, p)
            a[i] += 3
        if seq and i <= 6 and a[i + 1] > 0 and a[i + 2] > 0:
            a[i] -= 1
            a[i + 1] -= 1
            a[i + 2] -= 1
            dfs(i, m + 1, t, p)
            a[i] += 1
            a[i + 1] += 1
            a[i + 2] += 1
        if not p and a[i] >= 2:
            a[i] -= 2
            dfs(i, m, t, 1)
            a[i] += 2
        if a[i] >= 2:
            a[i] -= 2
            dfs(i, m, t + 1, p)
            a[i] += 2
        if seq and i <= 7 and a[i + 1] > 0:
            a[i] -= 1
            a[i + 1] -= 1
            dfs(i, m, t + 1, p)
            a[i] += 1
            a[i + 1] += 1
        if seq and i <= 6 and a[i + 2] > 0:
            a[i] -= 1
            a[i + 2] -= 1
            dfs(i, m, t + 1, p)
            a[i] += 1
            a[i + 2] += 1
        a[i] -= 1
        dfs(i, m, t, p)
        a[i] += 1

    dfs(0, 0, 0, 0)
    lst = list(res)
    out = tuple(x for x in lst if not any(
        y != x and y[0] >= x[0] and y[1] >= x[1] and y[2] >= x[2] for y in lst))
    _suit_cache[key] = out
    return out


def _normal(c):
    states = {(0, 0, 0)}
    for g in range(4):
        if g < 3:
            opts = _suit_opts(tuple(c[9 * g:9 * g + 9]), True)
        else:
            opts = _suit_opts(tuple(c[27:34]), False)
        new = set()
        for (m, t, p) in states:
            for (m2, t2, p2) in opts:
                if p + p2 > 1:
                    continue
                new.add((m + m2, t + t2, p + p2))
        states = new
    best = 8
    for (m, t, p) in states:
        tt = t if m + t <= 4 else 4 - m
        v = 8 - 2 * m - tt - p
        if v < best:
            best = v
    return best


def chiitoi_shanten(c):
    pairs = sum(1 for x in c if x >= 2)
    kinds = sum(1 for x in c if x >= 1)
    s = 6 - pairs
    if kinds < 7:
        s += 7 - kinds
    return s


def kokushi_shanten(c):
    kinds = sum(1 for k in YAO if c[k] > 0)
    pair = 1 if any(c[k] >= 2 for k in YAO) else 0
    return 13 - kinds - pair


def shanten(c):
    key = tuple(c)
    v = _memo.get(key)
    if v is None:
        v = min(_normal(c), chiitoi_shanten(c), kokushi_shanten(c))
        _memo[key] = v
    return v


def ukeire(c, rem, s):
    """c(13枚) に加えると s より小さくなる牌と残り枚数"""
    n = 0
    tiles = []
    for k in range(34):
        if rem[k] <= 0 or c[k] >= 4:
            continue
        c[k] += 1
        s2 = shanten(c)
        c[k] -= 1
        if s2 < s:
            n += rem[k]
            tiles.append((k, rem[k]))
    return n, tiles


# ---------------------------------------------------------------- 打点推定
HAN_PTS = [0, 1000, 2000, 3900, 7700, 8000, 12000, 12000, 16000, 16000, 16000, 24000, 24000, 32000]


def pts_of(han, dealer):
    han = max(1.0, min(13.0, han))
    lo = int(math.floor(han))
    hi = int(math.ceil(han))
    v = HAN_PTS[lo] + (HAN_PTS[hi] - HAN_PTS[lo]) * (han - lo)
    return v * 1.5 if dealer else v


def estimate_value(c, reds, ctx, chii_ok):
    """門前・立直前提の期待翻数と打点。戻り値 (打点, 翻, 注記リスト)"""
    notes = []
    han = 1.8  # 立直 + (一発/裏/ツモ)の期待値
    dora = c[ctx["dora"]] + sum(1 for r in reds if r)
    han += dora
    if dora:
        notes.append("ドラ・赤ドラ%d枚" % dora)

    yk_pair = False
    seen = set()
    for y in ctx["yk"]:
        n = c[y]
        nm = kind_name(y)
        if n >= 3:
            han += 1
            if (nm, 3) not in seen:
                notes.append("役牌%sの刻子" % nm)
                seen.add((nm, 3))
        elif n == 2:
            yk_pair = True
            han += 0.45
            if (nm, 2) not in seen:
                notes.append("役牌%sのトイツ" % nm)
                seen.add((nm, 2))

    yao = sum(c[k] for k in YAO)
    yao_eff = yao + (5 if yk_pair else 0)
    tan = 1.0 if yao_eff == 0 else 0.6 if yao_eff == 1 else 0.25 if yao_eff == 2 else 0.0

    hs = sum(c[27:34])
    fl_best = 0.0
    fl_honor = False
    fl_note = None
    for s in range(3):
        cs = sum(c[9 * s:9 * s + 9])
        other = 13 - cs - hs
        if other <= 3:
            if hs == 0:
                v = 6 * [0.95, 0.5, 0.2, 0.05][other]
                honor = False
                nm = "チンイツ"
            else:
                v = 3 * [0.95, 0.8, 0.55, 0.3][other]
                honor = True
                nm = "ホンイツ"
            if v > fl_best:
                fl_best, fl_honor, fl_note = v, honor, nm
    if fl_best >= 0.6:
        if fl_honor:
            if fl_best >= tan * 2:
                han += fl_best
                notes.append("%s見込み" % fl_note)
            else:
                han += tan
                if tan >= 0.6:
                    notes.append("タンヤオ見込み")
        else:
            han += fl_best + tan
            notes.append("%s見込み" % fl_note)
            if tan >= 0.6:
                notes.append("タンヤオ見込み")
    else:
        han += tan
        if tan >= 0.6:
            notes.append("タンヤオ見込み")

    # 一通 / 三色（門前2翻）
    for s in range(3):
        g = [sum(1 for i in range(3) if c[9 * s + 3 * j + i] > 0) for j in range(3)]
        if min(g) >= 2 and sum(g) >= 7:
            han += 2 * 0.4
            notes.append("一通見込み")
            break
    for n in range(7):
        w = [sum(1 for i in range(3) if c[9 * s + n + i] > 0) for s in range(3)]
        if min(w) >= 2 and sum(w) >= 7:
            han += 2 * 0.35
            notes.append("三色見込み")
            break

    pts = pts_of(han, ctx["dealer"])
    if chii_ok:
        hc = 3.8 + dora + tan
        pc = pts_of(hc, ctx["dealer"]) * 0.88
        if pc > pts:
            pts = pc
            han = hc
            notes = [x for x in notes if x.startswith("ドラ")] + ["七対子見込み"]
    return pts, han, notes


# ---------------------------------------------------------------- 和了率推定
def win_prob(s, n1, n2, T, U, ron_mult=2.0):
    stages = s + 1
    ps = []
    for i in range(stages):
        last = i == stages - 1
        if i == 0:
            n = n1
        elif i == 1:
            n = n2
        else:
            n = 4.2 if last else n2 * 0.9
        if last and stages >= 3:
            n = 4.2
        p = n / U
        if last:
            p *= ron_mult
        ps.append(min(0.9, p))
    state = [0.0] * (stages + 1)
    state[0] = 1.0
    for _ in range(T):
        new = [0.0] * (stages + 1)
        new[stages] = state[stages]
        for i in range(stages):
            new[i + 1] += state[i] * ps[i]
            new[i] += state[i] * (1 - ps[i])
        state = new
    return state[stages]


# ---------------------------------------------------------------- 放銃率推定
NOSUJI = [0.065, 0.085, 0.10, 0.11, 0.12, 0.11, 0.10, 0.085, 0.065]


def danger(k, th, rem_unseen, is_dora):
    """牌 k を切ったとき、脅威者 th に放銃する確率（テンパイ前提の1回あたり）"""
    if k in th["river"] or rem_unseen <= 0:
        return 0.0  # 現物 / 4枚見えで安全
    if k >= 27:
        base = 0.06 if k in th["yk"] else 0.04
        return base * min(1.0, rem_unseen / 3.0)
    s, p = divmod(k, 9)
    base = NOSUJI[p]
    partners = [q for q in (p - 3, p + 3) if 0 <= q <= 8]
    hit = sum(1 for q in partners if 9 * s + q in th["river"])
    if len(partners) == 1:
        if hit:
            base *= 0.45
    else:
        base *= (1.0, 0.7, 0.35)[hit]
    wall_f = 0.45 + 0.55 * min(1.0, rem_unseen / 3.0)
    return base * wall_f * (1.25 if is_dora else 1.0)


def suji_label(k, th):
    if k in th["river"]:
        return "現物"
    if k < 27:
        s, p = divmod(k, 9)
        partners = [q for q in (p - 3, p + 3) if 0 <= q <= 8]
        hit = sum(1 for q in partners if 9 * s + q in th["river"])
        if hit and hit == len(partners):
            return "スジ"
    if k >= 27:
        return "字牌"
    return ""


# ---------------------------------------------------------------- 打牌評価
def eval_candidate(c14, reds14, tid, ctx, min_s):
    k = kind_of(tid)
    c = list(c14)
    c[k] -= 1
    reds = list(reds14)
    if tid >= 34:
        reds[tid - 34] = False
    rem = [max(0, 4 - c14[i] - ctx["ind"][i] - ctx["vis"][i]) for i in range(34)]
    s = shanten(c)
    n1, tiles = ukeire(c, rem, s)

    n2 = n1 * 0.7
    if 1 <= s <= min_s + 1 and n1 > 0:
        tot = 0
        for kk, r in tiles:
            c[kk] += 1
            rem[kk] -= 1
            best = 0
            for j in range(34):
                if not c[j]:
                    continue
                c[j] -= 1
                if shanten(c) == s - 1:
                    u, _t = ukeire(c, rem, s - 1)
                    if u > best:
                        best = u
                c[j] += 1
            c[kk] -= 1
            rem[kk] += 1
            tot += r * best
        n2 = tot / n1

    ron = ctx["ron_mult"]
    furiten = False
    if s == 0 and any(kk in ctx["myriver"] for kk, _ in tiles):
        ron = 1.0  # 自分の河に待ちがある＝フリテン（ツモのみ）
        furiten = True
    p = win_prob(s, n1, n2, ctx["T"], ctx["U"], ron) if n1 > 0 else 0.0
    chii_ok = chiitoi_shanten(c) <= s and sum(1 for x in c if x >= 2) >= 4
    pts, han, notes = estimate_value(c, reds, ctx, chii_ok)
    value = pts + 300 * ctx["honba"] + 1000 * ctx["kyou"]
    veff = 8000.0 * (value / 8000.0) ** ctx["alpha"]

    # 放銃リスク（現在の脅威者に対する、今の打牌 + 今後の押しのリスク）
    rem_unseen = max(0, 4 - c14[k] - ctx["ind"][k] - ctx["vis"][k])
    is_dora = (k == ctx["dora"]) or tid >= 34
    fs = {0: 1.0, 1: 0.9, 2: 0.6, 3: 0.35}.get(s, 0.2)  # 押し続けた場合に危険牌を切る度合い
    imm_prob = imm_loss = fut_prob = fut_loss = fold_loss = 0.0
    labels = []
    for th in ctx["threats"]:
        d = danger(k, th, rem_unseen, is_dora)
        imm_prob += th["tp"] * d
        imm_loss += th["tp"] * d * th["L"]
        f = th["tp"] * (1 - (1 - 0.027) ** (0.6 * ctx["T"])) * fs
        fut_prob += f
        fut_loss += f * th["L"]
        fold_loss += 0.025 * th["tp"] * th["L"]  # 完全に降りた場合の残存リスク
        if th["tp"] >= 0.5:
            labels.append(suji_label(k, th))
    peff = p * ctx["surv"] * (1 - min(0.9, imm_prob + fut_prob))
    push = peff * veff - fut_loss
    fold = -fold_loss
    # 押し/降りの良い方を採る。降りる場合でも手牌の可能性が高い方をわずかに評価
    value_after = max(push, fold) + 0.08 * min(push - fold, 0.0)
    ev = value_after - imm_loss
    dora_cnt = c[ctx["dora"]] + sum(1 for r in reds if r)
    return {
        "t": tid, "s": s, "n": n1, "n2": round(n2, 1), "w": tiles, "p": p, "pts": pts,
        "han": han, "notes": notes, "ev": ev, "dora": dora_cnt, "risk": imm_prob,
        "labels": labels, "furiten": furiten,
    }


def s_label(s):
    return "テンパイ" if s == 0 else "%dシャンテン" % s


def discard_desc(tid, c14, ctx):
    k = kind_of(tid)
    out = []
    if k == ctx["dora"] or tid >= 34:
        out.append("ドラ・赤ドラを手放すので打点は下がる")
    if k >= 27:
        if k in ctx["yk"]:
            out.append("役牌%sを1枚切る" % kind_name(k))
        else:
            out.append("役に絡まない字牌を処理")
    elif c14[k] == 1:
        s, pos = k // 9, k % 9
        iso = all(not (0 <= pos + d < 9 and c14[9 * s + pos + d]) for d in (-2, -1, 1, 2))
        if iso:
            out.append("孤立した%sを切る" % kind_name(k) if pos not in (0, 8) else "端牌の孤立牌を処理")
        else:
            out.append("%sの周辺（ターツ/浮き牌）を払う" % kind_name(k))
    elif c14[k] == 2:
        out.append("%sのトイツから1枚切る" % kind_name(k))
    else:
        out.append("%sの刻子/暗刻から1枚切る" % kind_name(k))
    return out


def explain(rank, cand, best, min_s, same_s_max_n, c14, ctx):
    why = []
    if rank == 0:
        if ctx["threats"] and cand["s"] > min_s and cand["risk"] < ctx["min_s_risk"] - 1e-9:
            why.append("シャンテン数を戻してでも放銃を避ける、守備を優先した選択")
        elif cand["s"] == min_s:
            why.append("%sを維持しつつ、受け入れ・打点・放銃リスクを含めた総合評価が最上位" % s_label(cand["s"]))
        else:
            why.append("シャンテン数は戻るが、打点・形の良さで総合評価が最上位")
    else:
        dn = cand["n"] - best["n"]
        dp = cand["pts"] - best["pts"]
        dwin = (cand["p"] - best["p"]) * 100
        line = "1位との差: %s / 受け入れ%+d枚 / 打点%+d点 / 和了率%+.1f%%" % (
            s_label(cand["s"]), dn, int(round(dp, -1)), dwin)
        if ctx["threats"]:
            line += " / 放銃率%+.1f%%" % ((cand["risk"] - best["risk"]) * 100)
        why.append(line)
    if cand["s"] == min_s and cand["n"] == same_s_max_n and cand["n"] > 0:
        why.append("同シャンテンの中で受け入れ最大（%d枚）" % cand["n"])
    why.extend(discard_desc(cand["t"], c14, ctx))
    if ctx["threats"]:
        lab = [x for x in cand["labels"] if x]
        if cand["risk"] == 0:
            why.append("脅威者の現物（または4枚見え）で、この牌での放銃はない")
        elif lab and len(set(lab)) == 1 and lab[0] in ("スジ", "現物"):
            why.append("スジ・現物中心で比較的安全（放銃率目安 %.1f%%）" % (cand["risk"] * 100))
        else:
            why.append("放銃率目安 %.1f%%（河・スジ・残り枚数から推定）" % (cand["risk"] * 100))
    if cand["furiten"]:
        why.append("待ちが自分の河にあるフリテン（ツモ和了のみ）")
    for nt in cand["notes"][:3]:
        why.append("残る手の価値: %s" % nt)
    return why


# ---------------------------------------------------------------- 牌山・局面
def make_wall():
    wall = []
    for k in range(34):
        for n in range(4):
            if k in RED_KIND and n == 0:
                wall.append(34 + RED_KIND.index(k))
            else:
                wall.append(k)
    return wall


def dora_of(ind_kind):
    if ind_kind < 27:
        return ind_kind - 8 if ind_kind % 9 == 8 else ind_kind + 1
    if ind_kind < 31:
        return 27 + (ind_kind - 27 + 1) % 4
    return 31 + (ind_kind - 31 + 1) % 3


def gauss(rng):
    return math.sqrt(-2 * math.log(1 - rng.random())) * math.cos(2 * math.pi * rng.random())


def weighted(rng, weights):
    return rng.choices(range(len(weights)), weights=weights)[0]


def gen_scene(rng, riichi_rels):
    idx = rng.randrange(8)
    round_wind = 0 if idx < 4 else 1
    kyoku = idx % 4 + 1
    honba = weighted(rng, [50, 25, 13, 7, 3, 2])
    kyou = len(riichi_rels) + weighted(rng, [75, 20, 5])
    my_wind = rng.randrange(4)
    dealer = my_wind == 0
    if idx == 0 and honba == 0 and kyou == len(riichi_rels):
        scores = [24000 if i in riichi_rels else 25000 for i in range(4)]
    else:
        sd = 1500 if idx == 0 else 3000 + 1500 * idx
        while True:
            a = [25000 + int(round(gauss(rng) * sd / 100.0)) * 100 for _ in range(4)]
            a[3] += (100000 - 1000 * kyou) - sum(a)
            if all(1000 <= x <= 90000 for x in a) and abs(a[3] - 25000) <= sd * 2.2:
                scores = a
                break
    return {
        "roundWind": round_wind, "kyoku": kyoku, "honba": honba, "kyou": kyou,
        "myWind": my_wind, "dealer": dealer, "scores": scores,
    }


def alpha_for(scene):
    sc = scene["scores"]
    me = sc[0]
    rank = 1 + sum(1 for x in sc if x > me)
    late = scene["roundWind"] == 1 and scene["kyoku"] >= 3
    lead = me - max(x for i, x in enumerate(sc) if i != 0)
    if late:
        if rank == 1 and lead >= 8000:
            return 0.7, "終盤でトップ目に点差があるため、打点より和了率・速度（と放銃回避）を重視"
        if rank == 4:
            return 1.3, "終盤でラス目のため、高打点（逆転できる手）を重視"
        if rank == 3:
            return 1.15, "終盤で3着目のため、やや打点を重視"
    return 1.0, ""


def pick_theme_weight(theme, tid, ctx):
    k = kind_of(tid)
    suit = k // 9 if k < 27 else 3
    if theme == "flush":
        if suit == ctx["theme_suit"]:
            return 4.0
        return 2.0 if suit == 3 else 1.0
    if theme == "tanyao":
        if k >= 27:
            return 0.3
        return 0.5 if k % 9 in (0, 8) else 2.5
    if theme == "yakuhai":
        return 3.0 if k in ctx["yk"] else 1.0
    return 1.0


def choose_discard(c14, reds, ctx, rng):
    best = None
    cand = []
    for k in range(34):
        if c14[k] == 0:
            continue
        c = list(c14)
        c[k] -= 1
        cand.append((shanten(c), k))
    min_s = min(x[0] for x in cand)
    rem = [max(0, 4 - c14[i] - ctx["ind"][i]) for i in range(34)]
    for s, k in cand:
        if s != min_s:
            continue
        c = list(c14)
        c[k] -= 1
        n, _t = ukeire(c, rem, s)
        score = n + rng.random() * 0.6
        if k == ctx["dora"]:
            score -= 1.5
        if k in RED_KIND and reds[RED_KIND.index(k)] and c14[k] == 1:
            score -= 1.5
        if k >= 27 and k not in ctx["yk"] and c14[k] == 1:
            score += 0.4
        if best is None or score > best[0]:
            best = (score, k)
    return best[1]


def sort_key(t):
    return (kind_of(t), 1 if t >= 34 else 0)


# ---- 他家の河・副露・リーチ ----
SEAT_NAMES = ["自分", "下家", "対面", "上家"]


def river_weight(tid, i):
    k = kind_of(tid)
    if k >= 27:
        return 3.0 if i < 6 else 1.0
    pos = k % 9
    if pos in (0, 8):
        return 2.2 if i < 6 else 1.2
    if pos in (1, 7):
        return 1.3
    return 1.0 if i < 6 else 1.6


def take_from_wall(rng, wall, n, weight_fn=None):
    out = []
    for i in range(n):
        if weight_fn:
            idx = weighted(rng, [weight_fn(t, i) for t in wall])
        else:
            idx = rng.randrange(len(wall))
        out.append(wall.pop(idx))
    return out


def make_meld(rng, wall, roundwind, pwind):
    yk = [31, 32, 33, 27 + roundwind, 27 + pwind]
    for _ in range(50):
        if rng.random() < 0.42:
            k = rng.choice(yk) if rng.random() < 0.55 else rng.randrange(34)
            idxs = [i for i, t in enumerate(wall) if kind_of(t) == k]
            if len(idxs) < 3:
                continue
            pick = sorted(rng.sample(idxs, 3), reverse=True)
            tiles = [wall.pop(i) for i in pick]
            return {"type": "pon", "tiles": sorted(tiles, key=sort_key), "called": rng.randrange(3)}
        s = rng.randrange(3)
        n = rng.choice([1, 2, 2, 3, 3, 4, 4, 5, 0, 6])
        ks = [9 * s + n + d for d in range(3)]
        idxs = []
        ok = True
        for kk in ks:
            cand = [i for i, t in enumerate(wall) if kind_of(t) == kk and i not in idxs]
            if not cand:
                ok = False
                break
            idxs.append(rng.choice(cand))
        if not ok:
            continue
        tiles = [wall[i] for i in sorted(idxs, reverse=True)]
        for i in sorted(idxs, reverse=True):
            wall.pop(i)
        return {"type": "chi", "tiles": sorted(tiles, key=sort_key), "called": rng.randrange(3)}
    return None


def meld_text(m):
    ks = [kind_of(t) for t in m["tiles"]]
    if m["type"] == "pon":
        return "ポン%s" % kind_name(ks[0])
    return "チー%s%s%s" % (kind_name(ks[0])[:-1], kind_name(ks[1])[:-1], kind_name(ks[2]))


def open_threat(melds, turn, pwind, scene, dora_kind):
    m = len(melds)
    base = {1: 0.14, 2: 0.32, 3: 0.55}[m] + 0.02 * max(0, turn - 7)
    base = min(base, 0.85)
    yk = {31, 32, 33, 27 + scene["roundWind"], 27 + pwind}
    kinds = [kind_of(t) for mm in melds for t in mm["tiles"]]
    if any(mm["type"] == "pon" and kind_of(mm["tiles"][0]) in yk for mm in melds):
        yaku = 1.0
    elif all(k < 27 and k % 9 not in (0, 8) for k in kinds):
        yaku = 0.85
    elif len({k // 9 for k in kinds if k < 27}) <= 1 and any(k >= 27 for k in kinds):
        yaku = 0.8
    else:
        yaku = 0.45
    dv = sum(1 for t in [t for mm in melds for t in mm["tiles"]] if kind_of(t) == dora_kind or t >= 34)
    return base * yaku, 3900 + 1900 * dv


def build_others(rng, wall, scene, turn, riichi_rels, open_rels, dora_kind):
    """3家の河・副露・リーチを作り、牌山から消費する"""
    seats = []
    threats = []
    vis = [0] * 34
    for rel in range(1, 4):
        pw = (scene["myWind"] + rel) % 4
        n = turn if pw < scene["myWind"] else turn - 1
        n = max(n, 1)
        seat = {"river": [], "riichi": -1, "melds": []}
        pdealer = pw == 0
        if rel in open_rels:
            nm = rng.choice([1, 1, 2, 2, 3]) if turn >= 8 else rng.choice([1, 1, 2])
            for _ in range(nm):
                m = make_meld(rng, wall, scene["roundWind"], pw)
                if m:
                    seat["melds"].append(m)
        if rel in riichi_rels:
            seat["riichi"] = rng.randint(4, n - 1)
        river = take_from_wall(rng, wall, n, river_weight)
        seat["river"] = river
        seats.append(seat)

        rset = {kind_of(t) for t in river}
        for t in river:
            vis[kind_of(t)] += 1
        for m in seat["melds"]:
            for t in m["tiles"]:
                vis[kind_of(t)] += 1
        yk = {31, 32, 33, 27 + scene["roundWind"], 27 + pw}
        if seat["riichi"] >= 0:
            L = (9750 if pdealer else 6500) + 300 * scene["honba"]
            threats.append({"rel": rel, "tp": 1.0, "L": L, "river": rset, "yk": yk, "riichi": True})
        elif seat["melds"]:
            tp, L = open_threat(seat["melds"], turn, pw, scene, dora_kind)
            L = (L * 1.5 if pdealer else L) + 300 * scene["honba"]
            threats.append({"rel": rel, "tp": tp, "L": L, "river": rset, "yk": yk, "riichi": False})
    return seats, threats, vis


def build_problem(rng, quota, seen_keys):
    sh_q, sc_q = quota["sh"], quota["sc"]
    avail = [s for s in ("quiet", "riichi", "open") if sc_q.get(s, 0) > 0]
    if not avail:
        return None
    scenario = rng.choice(avail)

    riichi_rels, open_rels = [], []
    rels = [1, 2, 3]
    rng.shuffle(rels)
    if scenario == "riichi":
        nr = 2 if rng.random() < 0.15 else 1
        riichi_rels = rels[:nr]
        if rng.random() < 0.25 and len(rels) > nr:
            open_rels = [rels[nr]]
    elif scenario == "open":
        open_rels = rels[:1] if rng.random() < 0.5 else rels[:2]
    else:
        if rng.random() < 0.3:
            open_rels = rels[:1]

    scene = gen_scene(rng, riichi_rels)
    wall = make_wall()
    rng.shuffle(wall)
    ind = wall.pop()
    ind_kind = kind_of(ind)
    dora = dora_of(ind_kind)
    yk = [31, 32, 33, 27 + scene["roundWind"], 27 + scene["myWind"]]
    ind_cnt = [0] * 34
    ind_cnt[ind_kind] += 1
    theme = rng.choice(["normal", "normal", "flush", "tanyao", "yakuhai"])
    tctx = {"theme_suit": rng.randrange(3), "yk": yk}

    w = [pick_theme_weight(theme, t, tctx) for t in wall]
    hand = []
    for _ in range(13):
        i = weighted(rng, w)
        hand.append(wall.pop(i))
        w.pop(i)

    min_turn = 6 if scenario == "riichi" else 5 if scenario == "open" else 3
    turns = list(range(min_turn, 15))
    tw_all = {3: 1, 4: 2, 5: 2, 6: 3, 7: 3, 8: 3, 9: 3, 10: 2, 11: 2, 12: 1, 13: 1, 14: 1}
    turn = turns[weighted(rng, [tw_all[t] for t in turns])]

    alpha, alpha_note = alpha_for(scene)
    ctx = {
        "dora": dora, "yk": yk, "ind": ind_cnt, "dealer": scene["dealer"],
        "honba": scene["honba"], "kyou": scene["kyou"], "alpha": alpha,
        "turn": turn, "T": max(1, 18 - turn),
    }

    def counts(h):
        c = [0] * 34
        reds = [False] * 3
        for t in h:
            c[kind_of(t)] += 1
            if t >= 34:
                reds[t - 34] = True
        return c, reds

    my_river = []
    for _ in range(turn - 1):
        hand.append(wall.pop())
        c, reds = counts(hand)
        if shanten(c) < 0:
            return None
        k = choose_discard(c, reds, ctx, rng)
        cands = [t for t in hand if kind_of(t) == k]
        cands.sort(key=lambda t: t >= 34)
        hand.remove(cands[0])
        my_river.append(cands[0])
    tsumo = wall.pop()
    hand14 = hand + [tsumo]
    c14, reds14 = counts(hand14)
    if shanten(c14) < 0:
        return None

    ids = sorted(set(hand14), key=sort_key)
    shs = {}
    for t in ids:
        c = list(c14)
        c[kind_of(t)] -= 1
        shs[t] = shanten(c)
    min_s = min(shs.values())
    if min_s > 2 or sh_q.get(min_s, 0) <= 0:
        return None
    key = (tuple(sorted(hand14)), ind)
    if key in seen_keys:
        return None

    seats_o, threats, vis = build_others(rng, wall, scene, turn, riichi_rels, open_rels, dora)
    myset = {kind_of(t) for t in my_river}
    for t in my_river:
        vis[kind_of(t)] += 1
    nri = len(riichi_rels)
    surv = 1.0
    for th in threats:
        surv *= 1 - 0.5 * th["tp"] * min(1.0, ctx["T"] / 12.0)
    ctx.update({
        "vis": vis, "threats": threats, "myriver": myset,
        "U": max(30, 121 - sum(vis)), "ron_mult": max(1.2, 2.0 - 0.4 * nri), "surv": surv,
    })

    cands = [eval_candidate(c14, reds14, t, ctx, min_s) for t in ids]
    cands.sort(key=lambda x: -x["ev"])
    if len(cands) < 4:
        return None
    e0, e1, e2 = cands[0]["ev"], cands[1]["ev"], cands[2]["ev"]
    scale = max(abs(e0), 400.0)
    if e0 - e1 < 0.05 * scale or e1 - e2 < 0.05 * scale:
        return None
    if sum(1 for x in cands if x["ev"] >= e0 - 0.6 * scale) < 3:
        return None
    # 守備の問題でも、1位が全員同じ現物ばかりで自明にならないよう調整
    if cands[0]["ev"] - cands[3]["ev"] > 2.5 * scale and rng.random() < 0.7:
        return None

    same_s = [x for x in cands if x["s"] == min_s]
    same_s_max_n = max(x["n"] for x in same_s)
    ctx["min_s_risk"] = min(x["risk"] for x in same_s)
    best = cands[0]
    out = []
    for rank, x in enumerate(cands):
        item = {
            "t": x["t"], "s": x["s"], "n": x["n"],
            "w": [[k, r] for k, r in x["w"]],
            "pts": int(round(x["pts"], -2)), "han": round(x["han"], 1),
            "p": round(x["p"] * 100, 1), "ev": int(round(x["ev"], -1)),
            "risk": round(x["risk"] * 100, 1),
        }
        if rank < 3:
            item["why"] = explain(rank, x, best, min_s, same_s_max_n, c14, ctx)
        out.append(item)

    notes = []
    for rel in riichi_rels:
        notes.append("%sがリーチ中（%d枚目の捨て牌で宣言）。現物・スジ・字牌の枯れ具合を見て押し引きを判断" % (
            SEAT_NAMES[rel], seats_o[rel - 1]["riichi"] + 1))
    for rel in open_rels:
        ms = "・".join(meld_text(m) for m in seats_o[rel - 1]["melds"])
        th = [t for t in threats if t["rel"] == rel]
        tp = th[0]["tp"] if th else 0
        notes.append("%sが副露（%s）。テンパイ確率の目安 %d%%" % (SEAT_NAMES[rel], ms, int(round(tp * 100))))
    if alpha_note:
        notes.append(alpha_note)
    if scene["dealer"]:
        notes.append("親番のため和了時の打点は1.5倍。連荘も狙える")
    if turn >= 12:
        notes.append("終盤（%d巡目）のため、残りツモ回数が少なく和了率の比重が大きい" % turn)
    if scene["honba"] or scene["kyou"]:
        notes.append("本場・供託で和了時の収入が増える（%d本場 / 供託%d本）" % (scene["honba"], scene["kyou"]))

    seen_keys.add(key)
    sh_q[min_s] -= 1
    sc_q[scenario] -= 1
    seats = [{"river": my_river, "riichi": -1, "melds": []}] + seats_o
    return {
        "roundWind": scene["roundWind"], "kyoku": scene["kyoku"], "honba": scene["honba"],
        "kyou": scene["kyou"], "dealer": scene["dealer"], "myWind": scene["myWind"],
        "turn": turn, "scores": scene["scores"], "indicator": ind,
        "hand": sorted(hand, key=sort_key), "tsumo": tsumo, "seats": seats,
        "scenario": scenario, "minShanten": min_s, "answers": out, "notes": notes,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--count", type=int, default=200)
    ap.add_argument("--seed", type=int, default=20261111)
    ap.add_argument("--out", default=os.path.join(os.path.dirname(__file__), "..", "web", "problems.js"))
    args = ap.parse_args()

    rng = random.Random(args.seed)
    n = args.count
    sh = {0: int(n * 0.25), 1: int(n * 0.40)}
    sh[2] = n - sh[0] - sh[1]
    sc = {"quiet": int(n * 0.40), "riichi": int(n * 0.40)}
    sc["open"] = n - sc["quiet"] - sc["riichi"]
    quota = {"sh": sh, "sc": sc}
    seen = set()
    problems = []
    attempts = 0
    while len(problems) < n:
        attempts += 1
        p = build_problem(rng, quota, seen)
        if p is None:
            if attempts > 3000000:
                sys.exit("生成に失敗しました")
            continue
        problems.append(p)
        if len(problems) % 10 == 0:
            print("  %d/%d 問生成 (試行 %d 回)" % (len(problems), n, attempts), file=sys.stderr)

    rng.shuffle(problems)
    for i, p in enumerate(problems):
        p["id"] = i + 1
    with open(args.out, "w", encoding="utf-8") as f:
        f.write("// このファイルは tools/generate.py で自動生成されます\n")
        f.write("const PROBLEMS = ")
        json.dump(problems, f, ensure_ascii=False, separators=(",", ":"))
        f.write(";\n")
    print("完了: %d問 -> %s" % (len(problems), os.path.abspath(args.out)))


if __name__ == "__main__":
    main()
