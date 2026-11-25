#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""版式轮转门禁：把「同类版式不连续超过 2 页」从口号变成 exit code。

输入是 pptx_layouts.Deck.write() 产出的 layout_manifest.json。
之所以能做这个检查，是因为版式族在生成期就被 @layout 装饰器登记进 manifest——
生成之后只看 .pptx 是判断不了「这一页和上一页是不是同一个骨架」的。

用法：
  python3 check_layout_rotation.py slides/layout_manifest.json
  python3 check_layout_rotation.py ... --max-run 2 --max-share 0.35 --min-families 5
  python3 check_layout_rotation.py ... --json layout_check.json

规则：
  R1 同一版式族物理连续超过 --max-run 页                → FAIL（版式单一的直接定义）
  R2 版式族总数少于 --min-families（页数 ≥12 时才查）    → FAIL
  R3 单一版式族占比超过 --max-share                      → FAIL（当年 19/28 双卡就是这个）
  R4 同族相邻且交替变体（深色左右/说明条上下/图左右）相同 → WARN，提示该翻个面
  R5 存在 custom 页（body 是手写 Box，未声明版式族）      → WARN，属于审计盲区
退出码 0=无 FAIL；1=有 FAIL；2=输入有问题。
"""
import argparse
import collections
import json
import os
import sys


def load(path):
    if not os.path.exists(path):
        raise SystemExit('[layout] 找不到 manifest：%s（先跑 Deck.write()）' % path)
    with open(path, encoding='utf-8') as f:
        m = json.load(f)
    if 'pages' not in m or not m['pages']:
        raise SystemExit('[layout] manifest 里没有 pages')
    return m


def check(m, max_run, max_share, min_families):
    pages = sorted(m['pages'], key=lambda p: p['n'])
    total = len(pages)
    fails, warns = [], []

    # R1 连续同类（遇 custom 中断：不知道它是什么，保守处理并由 R5 提醒）
    run_fam, run_start, run_len = None, None, 0
    runs = []
    for p in pages + [{'n': None, 'layout': '__END__'}]:
        fam = p['layout']
        if fam == 'custom':
            fam = None
        if fam is not None and fam == run_fam:
            run_len += 1
        else:
            if run_fam is not None:
                runs.append((run_fam, run_start, run_len))
            run_fam, run_start, run_len = fam, p['n'], (1 if fam else 0)
    for fam, start, ln in runs:
        if ln > max_run:
            fails.append('R1 版式族 %s 连续 %d 页（第 %d–%d 页），超过上限 %d'
                         % (fam, ln, start, start + ln - 1, max_run))

    # R2/R3 族分布（custom 不参与族数统计）
    cnt = collections.Counter(p['layout'] for p in pages if p['layout'] != 'custom')
    if total >= 12 and len(cnt) < min_families:
        fails.append('R2 全篇只用了 %d 个版式族（%s），少于下限 %d'
                     % (len(cnt), '/'.join(sorted(cnt)), min_families))
    for fam, c in cnt.most_common():
        share = c / float(total)
        if share > max_share:
            fails.append('R3 版式族 %s 占 %d/%d 页（%.0f%%），超过上限 %.0f%%'
                         % (fam, c, total, share * 100, max_share * 100))

    # R4 同族相邻但变体没变（只提醒，不判失败）
    for a, b in zip(pages, pages[1:]):
        if a['layout'] == b['layout'] and a['layout'] != 'custom':
            va, vb = a.get('variant') or {}, b.get('variant') or {}
            common = set(va) & set(vb)
            if common and all(va[k] == vb[k] for k in common):
                warns.append('R4 第 %d/%d 页同为 %s 且变体相同 %s——深浅/左右/上下可以翻个面'
                             % (a['n'], b['n'], a['layout'],
                                {k: va[k] for k in sorted(common)}))

    customs = [p['n'] for p in pages if p['layout'] == 'custom']
    if customs:
        warns.append('R5 第 %s 页未声明版式族（custom），不参与 R1–R3 统计；'
                     '建议 deck.add(..., layout="...") 显式命名' % customs)
    return pages, cnt, fails, warns


def main():
    ap = argparse.ArgumentParser(description='版式轮转门禁')
    ap.add_argument('manifest')
    ap.add_argument('--max-run', type=int, default=2)
    ap.add_argument('--max-share', type=float, default=0.35)
    ap.add_argument('--min-families', type=int, default=5)
    ap.add_argument('--json', dest='json_out', default=None)
    args = ap.parse_args()

    m = load(args.manifest)
    pages, cnt, fails, warns = check(m, args.max_run, args.max_share, args.min_families)

    print('== 每页版式族 ==')
    for p in pages:
        var = p.get('variant') or {}
        vs = ' '.join('%s=%s' % (k, var[k]) for k in sorted(var))
        print('  %02d  %-11s %-8s %s' % (p['n'], p['layout'], vs, p['title'][:34]))
    print('\n== 族分布（共 %d 页）==' % len(pages))
    for fam, c in cnt.most_common():
        bar = '#' * c
        print('  %-11s %2d 页 %5.1f%%  %s' % (fam, c, c * 100.0 / len(pages), bar))
    for w in warns:
        print('[WARN] ' + w)
    for f in fails:
        print('[FAIL] ' + f)
    print('\n结论：%s（FAIL %d / WARN %d；阈值 max-run=%d max-share=%.2f min-families=%d）'
          % ('不通过' if fails else '通过', len(fails), len(warns),
             args.max_run, args.max_share, args.min_families))

    if args.json_out:
        with open(args.json_out, 'w', encoding='utf-8') as f:
            json.dump({'ok': not fails, 'fails': fails, 'warns': warns,
                       'families': dict(cnt),
                       'pages': [{k: p[k] for k in ('n', 'title', 'layout', 'variant')}
                                 for p in pages]}, f, ensure_ascii=False, indent=2)
        print('报告已写 ' + args.json_out)
    return 1 if fails else 0


if __name__ == '__main__':
    sys.exit(main())
