#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把交付正文的引用编号按首次出现顺序重排，并同步重排参考文献。

写作与 evidence_ledger.md 始终使用 papers.json 的 ref_no；本脚本只改交付正文，
同时写 citation_map.json（display_to_ref: 交付序号 -> papers.json ref_no）供复核。

支持一份或多份正文：
- 单文件（A/B/C 单篇交付）：按该正文首次出现顺序编号。
- 多文件（C1+C2）：按命令行给出的顺序（应先 C1 后 C2）统一连续编号，
  各文件共用同一份参考文献列表与同一份 citation_map.json，不得各自从 1 重排。

用法：
  python3 renumber_citations.py 综述初稿.md
  python3 renumber_citations.py C1_引言.md C2_文献综述.md
  python3 renumber_citations.py 综述初稿.md --out 交付正文.md --map citation_map.json
  python3 renumber_citations.py C1_引言.md C2_文献综述.md --check
"""
import argparse
import datetime
import json
import os
import re
import sys

REF_HEADING = "## 参考文献"
CITATION_RE = re.compile(r"\[(\d+)\]")
PROTECTED_PATTERNS = (
    # 围栏代码块（含未闭合块）与行内代码。
    re.compile(r"(?ms)^[ \t]*(`{3,}|~{3,})[^\n]*(?:\n|$).*?(?:^[ \t]*\1[ \t]*(?:\n|$)|\Z)"),
    re.compile(r"(?s)(`+)(?!`)(.+?)(?<!`)\1(?!`)"),
    # URL / DOI 内的方括号数字是标识符的一部分，不是正文引用。
    re.compile(r"https?://[^\s<>一-鿿，。；、]+", re.I),
    re.compile(r"(?<![A-Za-z0-9])10\.\d{4,9}/[^\s<>一-鿿，。；、]+", re.I),
    re.compile(r"\bISBN(?:-1[03])?\s*:?\s*\[\d+\]", re.I),
    # 数字恰好作为 Markdown 链接文字时也不是顺序编码引用。
    re.compile(r"\[[^\]\n]+\]\([^)]+\)"),
)


def citation_matches(text):
    """只产生正文真实 [n]；DOI、URL、代码、Markdown 链接和四位年份均排除。"""
    protected = []
    for pattern in PROTECTED_PATTERNS:
        protected.extend((m.start(), m.end()) for m in pattern.finditer(text))
    for match in CITATION_RE.finditer(text):
        if any(start <= match.start() < end for start, end in protected):
            continue
        if len(match.group(1)) == 4:  # [2024] 等方括号年份
            continue
        yield match


def citation_numbers(text):
    return [int(match.group(1)) for match in citation_matches(text)]


def replace_citations(text, replacement):
    pieces, last = [], 0
    for match in citation_matches(text):
        pieces.append(text[last:match.start()])
        pieces.append(replacement(match))
        last = match.end()
    pieces.append(text[last:])
    return "".join(pieces)


def split_draft(text):
    if REF_HEADING not in text:
        raise ValueError("未找到「## 参考文献」分隔行")
    return text.split(REF_HEADING, 1)


def parse_entries(refsec):
    matches = list(re.finditer(r"(?m)^\[(\d+)\]\s+", refsec))
    entries = []
    for i, match in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(refsec)
        entries.append((int(match.group(1)), refsec[match.start():end].strip()))
    return entries


def ordered_unique(numbers):
    return list(dict.fromkeys(numbers))


def renumber_many(drafts):
    """drafts = [(path, body, refsec), ...]，按给定顺序统一分配交付编号。"""
    parsed = []
    entry_by_ref = {}
    entry_order = []
    for path, body, refsec in drafts:
        entries = parse_entries(refsec)
        if not entries:
            raise ValueError("%s 参考文献段没有形如 [n] 的条目" % os.path.basename(path))
        by_ref = {}
        for ref_no, entry in entries:
            if ref_no in by_ref:
                raise ValueError("%s 参考文献条目 ref_no 重复：%d" % (os.path.basename(path), ref_no))
            by_ref[ref_no] = entry
            if ref_no not in entry_by_ref:
                entry_by_ref[ref_no] = entry
                entry_order.append(ref_no)
        cited_order = ordered_unique(citation_numbers(body))
        missing = [n for n in cited_order if n not in by_ref]
        if missing:
            raise ValueError("%s 正文引用缺少参考文献条目：%s" % (os.path.basename(path), missing))
        parsed.append((path, body, cited_order))

    ordered_refs = []
    old_to_display = {}

    def assign(ref_no):
        if ref_no not in old_to_display:
            ordered_refs.append(ref_no)
            old_to_display[ref_no] = len(ordered_refs)

    cited_set = set()
    # 先跨全部正文分配"被引用"编号，保证多文件时后续文件接着前面的编号。
    for _, _, cited_order in parsed:
        for ref_no in cited_order:
            assign(ref_no)
            cited_set.add(ref_no)
    # 未被正文引用但允许列入的条目，按原参考文献出现顺序置后。
    for ref_no in entry_order:
        assign(ref_no)

    display_to_ref = {str(new): old for old, new in old_to_display.items()}
    new_drafts = []
    for path, body, _ in parsed:
        new_body = replace_citations(
            body, lambda match: "[%d]" % old_to_display[int(match.group(1))])
        new_drafts.append((path, new_body))
    new_entries = []
    for old in ordered_refs:
        entry = re.sub(r"^\[\d+\]", "[%d]" % old_to_display[old], entry_by_ref[old], count=1)
        new_entries.append(entry)
    shared_refsec = "\n\n" + "\n".join(new_entries) + "\n"
    return new_drafts, shared_refsec, display_to_ref, len(cited_set), len(ordered_refs) - len(cited_set)


def check_many(bodies, refsecs, display_to_ref):
    """多文件时把正文按顺序拼接后检查首次出现序列；各文件参考文献须同为 1..N。"""
    errors = []
    mapping = {int(k): int(v) for k, v in display_to_ref.items()}
    combined = "\n".join(bodies)
    cited_order = ordered_unique(citation_numbers(combined))
    expected = list(range(1, len(cited_order) + 1))
    if cited_order != expected:
        errors.append("正文首次出现顺序=%s，应为%s" % (cited_order, expected))
    for refsec in refsecs:
        entries = parse_entries(refsec)
        listed = [n for n, _ in entries]
        if listed != list(range(1, len(listed) + 1)):
            errors.append("参考文献条目未按 1..N 排列：%s" % listed)
        if set(listed) != set(mapping):
            errors.append("参考文献条目与 citation_map 编号集合不一致")
    if set(cited_order) - set(mapping):
        errors.append("正文引用有未映射编号：%s" % sorted(set(cited_order) - set(mapping)))
    if len(set(mapping.values())) != len(mapping):
        errors.append("citation_map 中多个交付序号指向同一 ref_no")
    return errors


def main():
    parser = argparse.ArgumentParser(description="按正文首次出现顺序重排引用与参考文献；多文件统一连续编号")
    parser.add_argument("drafts", nargs="+", help="交付正文；多份时按给出顺序统一编号并共用参考文献列表")
    parser.add_argument("--out", help="输出正文（仅单文件可用）；缺省覆盖输入文件")
    parser.add_argument("--map", dest="map_path", help="映射 JSON；缺省为首个输出文件同目录 citation_map.json")
    parser.add_argument("--check", action="store_true", help="只检查现有正文与映射，不改文件")
    args = parser.parse_args()

    if args.out and len(args.drafts) > 1:
        print("错误：多文件统一重排不支持 --out，请直接覆盖各输入文件", file=sys.stderr)
        return 1
    draft_paths = [os.path.abspath(p) for p in args.drafts]
    if len(draft_paths) > 1 and len({os.path.dirname(p) for p in draft_paths}) > 1:
        print("错误：多份正文须位于同一输出目录，才能共用 citation_map.json", file=sys.stderr)
        return 1
    out_paths = [os.path.abspath(args.out)] if args.out else draft_paths
    map_path = os.path.abspath(args.map_path) if args.map_path else os.path.join(os.path.dirname(out_paths[0]), "citation_map.json")

    try:
        drafts = []
        for path in draft_paths:
            text = open(path, encoding="utf-8").read()
            body, refsec = split_draft(text)
            drafts.append((path, body, refsec))
        if args.check:
            data = json.load(open(map_path, encoding="utf-8"))
            errors = check_many([d[1] for d in drafts], [d[2] for d in drafts], data["display_to_ref"])
            if errors:
                raise ValueError("；".join(errors))
            print("检查通过：正文引用按首次出现连续编号，参考文献与 citation_map.json 一致（%d 份正文）。" % len(drafts))
            return 0

        new_drafts, shared_refsec, display_to_ref, cited_count, uncited_count = renumber_many(drafts)
        errors = check_many([d[1] for d in new_drafts], [shared_refsec] * len(new_drafts), display_to_ref)
        if errors:
            raise ValueError("重排后自检失败：" + "；".join(errors))
        for (_, new_body), out_path in zip(new_drafts, out_paths):
            with open(out_path, "w", encoding="utf-8") as f:
                f.write(new_body + REF_HEADING + shared_refsec)
        data = {
            "version": 1,
            "rule": "first_appearance",
            "draft": os.path.basename(out_paths[0]),
            "drafts": [os.path.basename(p) for p in out_paths],
            "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "display_to_ref": display_to_ref,
            "cited_count": cited_count,
            "uncited_reference_count": uncited_count,
        }
        with open(map_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.write("\n")
        print("已重排 %d 份正文：正文引用 %d 篇按首次出现统一编号为 1..%d；参考文献共 %d 条（未引用 %d 条置后）。" % (
            len(new_drafts), cited_count, cited_count, len(display_to_ref), uncited_count))
        print("映射已写入 %s；evidence_ledger.md 仍使用原 ref_no。" % map_path)
        return 0
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print("错误：%s" % exc, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
