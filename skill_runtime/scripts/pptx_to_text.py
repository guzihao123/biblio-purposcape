#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把交付 PPT（<主题>组会汇报.pptx）抽成 汇报文本.md（供 verify_delivery.py 证据七项复核）。

为什么必须用脚本而不是手抄：
  verify_delivery.py 用 `## 参考文献` 这一行切分「正文 / 文献」两段。
  手抄、或直接拿 slidep inspect 的原始转储（里面没有这一行），后果经实测为：
    · ⑥ 参考文献完整性 → FAIL，但报的是「条目 0 条均挂 ref_no」——
      指向"台账/著录有问题"，实际是切分失败，排查会跑偏；
    · ⑤ 字数 → body 取到全文，把参考文献条目也算进正文字数（实测 3344→3401），
      文献多的 PPT 会误触 4000 上限；
    · ⑦ 无摘要不得被引 → 实际不受影响（它只扫正文 [n] 形式）。
  也就是说：它不会静默通过，但会以错误归因失败、并污染字数。本脚本负责插入该分隔行，
  并对"找不到参考文献页"当场 exit 2 明确点名原因，省掉一轮误判。

用法：
  python3 pptx_to_text.py "<输出目录>/<主题>组会汇报.pptx" --out <输出目录>/汇报文本.md
  python3 pptx_to_text.py "<输出目录>/<主题>组会汇报.pptx" --out ... --refs-regex '^参考文献|^References'
  python3 pptx_to_text.py "<输出目录>/<主题>组会汇报.pptx" --out ... --no-require-refs   # 确实无文献页时才关

退出码：0=正常；2=未找到参考文献标题（默认视为失败，避免静默失效）；3=slidep 调用失败。
"""
import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile

DEFAULT_REFS = r'^(?:参考文献|References|REFERENCES)\s*(?:[（(][^)）]*[)）])?\s*$'
# 页内小标题形式（如「参考文献（一）」「References (1)」），也接受带冒号/顿号
LOOSE_REFS = r'^(?:参考文献|References|REFERENCES)\s*(?:[（(][^)）]*[)）]|[：:、].*)?\s*$'


def find_slidep(user_path):
    if user_path:
        return user_path
    for cand in ('slidep',):
        p = shutil.which(cand)
        if p:
            return p
    return None


def clean(lines, refs_re):
    out = []
    in_refs = False
    hit_refs_at = None
    for raw in lines:
        line = raw.rstrip('\n').strip()
        if not line:
            continue
        # 丢弃结构标题（#/##/###）与位置标记（**c3**（x, y）/ **t1**（...））
        if line.startswith('#'):
            continue
        if re.match(r'^\*\*c\d+\*\*[（(]', line):
            continue
        if line.startswith('**t') and ('（' in line or '(' in line):
            continue
        # 去 Markdown 转义（inspect 会转义 [ ] _ * #）
        for a, b in (('\\[', '['), ('\\]', ']'), ('\\_', '_'), ('\\*', '*'), ('\\#', '#')):
            line = line.replace(a, b)
        if not in_refs and refs_re.match(line):
            out.append('## 参考文献')
            in_refs = True
            hit_refs_at = len(out)
        out.append(line)
    return out, hit_refs_at


def python_pptx_lines(pptx_path):
    from pptx import Presentation
    lines = []
    for slide in Presentation(pptx_path).slides:
        for shape in slide.shapes:
            if getattr(shape, 'has_text_frame', False):
                lines.extend(shape.text.splitlines())
            if getattr(shape, 'has_table', False):
                for row in shape.table.rows:
                    for cell in row.cells:
                        lines.extend(cell.text.splitlines())
    return lines


def main():
    ap = argparse.ArgumentParser(description='PPT 抽取纯文本，并插入 verify 依赖的 ## 参考文献 分隔')
    ap.add_argument('pptx', help='待抽取的 .pptx 路径')
    ap.add_argument('--out', required=True, help='输出 md 路径（通常 <输出目录>/汇报文本.md）')
    ap.add_argument('--refs-regex', default=LOOSE_REFS, help='参考文献页标题的正则（行首匹配）')
    ap.add_argument('--no-require-refs', action='store_true',
                    help='找不到参考文献标题时不报错（仅在 PPT 确实无文献页时使用）')
    ap.add_argument('--slidep', default=None, help='slidep 可执行文件路径（默认从 PATH 找）')
    args = ap.parse_args()

    if not os.path.exists(args.pptx):
        print(f'[pptx_to_text] 找不到 PPT：{args.pptx}', file=sys.stderr)
        return 3
    exe = find_slidep(args.slidep)
    raw = None
    extractor = 'slidep' if exe else 'python-pptx-no-slidep'
    if not exe:
        try:
            raw = python_pptx_lines(args.pptx)
        except ImportError:
            print('[pptx_to_text] PATH 里没有 slidep，且 python-pptx 不可用；请用 --slidep 指定', file=sys.stderr)
            return 3
        except Exception as e:
            print(f'[pptx_to_text] python-pptx 读取失败：{e}', file=sys.stderr)
            return 3

    if exe:
        # slidep inspect 拒绝写入已存在的文件，这里给一个尚不存在的路径
        tmpdir = tempfile.mkdtemp(prefix='pptx2text_')
        tmp = os.path.join(tmpdir, 'inspect.md')
        try:
            r = subprocess.run([exe, 'inspect', args.pptx, '--out', tmp],
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            if r.returncode != 0:
                print('[pptx_to_text] slidep inspect 失败，改用 python-pptx 离线解析：\n'
                      + (r.stdout or '') + (r.stderr or ''), file=sys.stderr)
                try:
                    raw = python_pptx_lines(args.pptx)
                    extractor = 'python-pptx-fallback'
                except ImportError:
                    print('[pptx_to_text] python-pptx 不可用，无法离线兜底', file=sys.stderr)
                    return 3
                except Exception as e:
                    print(f'[pptx_to_text] python-pptx 读取失败：{e}', file=sys.stderr)
                    return 3
            else:
                raw = open(tmp, encoding='utf-8').read().splitlines()
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    try:
        refs_re = re.compile(args.refs_regex)
    except re.error as e:
        print(f'[pptx_to_text] --refs-regex 非法：{e}', file=sys.stderr)
        return 3

    out, hit = clean(raw, refs_re)
    if hit is None and not args.no_require_refs:
        print('[pptx_to_text] 未在 PPT 中找到参考文献页标题（匹配 %r）。\n'
              '  这会让 verify_delivery.py 的 ⑥⑦ 两项静默失效，故按失败处理。\n'
              '  若本交付确实没有文献页，加 --no-require-refs；\n'
              '  若有文献页但标题不标准，用 --refs-regex 指定。' % args.refs_regex,
              file=sys.stderr)
        # 仍然写出文件，便于人工检查，但退出码非 0
        os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
        open(args.out, 'w', encoding='utf-8').write('\n'.join(out) + '\n')
        return 2

    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    text = '\n'.join(out) + '\n'
    open(args.out, 'w', encoding='utf-8').write(text)
    cjk = len(re.findall(r'[\u4e00-\u9fff]', text))
    body = text.split('## 参考文献')[0]
    body_cjk = len(re.findall(r'[\u4e00-\u9fff]', body))
    print(f'[pptx_to_text] wrote {args.out}  lines={len(out)}  '
          f'正文 CJK={body_cjk}  全篇 CJK={cjk}  extractor={extractor}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
