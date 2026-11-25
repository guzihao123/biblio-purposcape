#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""format_references.py — purpose-landscape 技能的 GB/T 7714-2015 参考文献著录工具（标准库零依赖）。

从 papers.json 生成顺序编码制参考文献：能确定的姓名按"姓在前全拼、名缩为首字母"格式化；
拿不准的（复合姓氏无小品词、疑似多人合并、机构作者）一律按原样输出并列入"需人工核对"，不硬猜。
另附"可疑题录提醒"（机构作者、标题残留 Author 等数据库脏数据），供交付前人工扫一遍。

用法:
  python3 format_references.py <papers.json> [--out references.md] [--cite-date YYYY-MM-DD]
缺省读 ./papers.json，参考文献打印到 stdout；--out 同时写文件。缺项省、严禁编造（见 references/gbt7714.md）。
"""
import argparse
import json
import re
import sys
import time

PARTICLES = {"de", "da", "dos", "das", "do", "van", "von", "della", "di",
             "la", "le", "del", "den", "ter", "der"}
CORP_HINT = ("society", "university", "association", "institute", "department",
             "center", "centre", "college", "academy", "academies", "organization",
             "organisation", "ministry", "bureau", "foundation", "committee",
             "consortium")
CORP_CJK_HINT = ("科学院", "大学", "研究院", "研究所", "学会", "协会", "委员会",
                 "中心", "医院", "公司", "集团")
TAG = {"article": "J", "review": "J", "dissertation": "D",
       "book-chapter": "M", "preprint": "EB/OL", "report": "R"}


def has_cjk(s):
    return bool(re.search(r"[一-鿿]", s))


def is_corporate(name):
    low = name.lower()
    return any(h in low for h in CORP_HINT) or any(h in name for h in CORP_CJK_HINT)


def initials(given_toks):
    # 连字符名拆分取首字母：Jung-Woo -> J W；中间缩写 P. M. -> P M
    parts = [p for t in given_toks for p in re.split(r"-+", t.replace(".", " ").strip()) if p]
    return " ".join(p[0].upper() for p in parts)


def fmt_author(name):
    """返回 (著录形式, 是否需人工核对)。拿不准时按原样返回并标记，不硬猜。"""
    name = name.strip()
    if not name:
        return "", False
    if is_corporate(name):
        return name, True
    # 同一字段疑似多人：保留原样，不将后一人的姓名误拆成前一人的名。
    if name.count(",") > 1 or re.search(r";|；|、|&|\s+and\s+", name, re.I):
        return name, True
    if has_cjk(name):
        return name, False
    if "," in name:  # "Garcia Chinas, Paola" 已姓前名后，复合姓氏边界明确
        sur, giv = [x.strip() for x in name.split(",", 1)]
        return (sur.upper() + " " + initials(giv.split())).strip(), False
    name = re.sub(r"-\s+", "-", name)  # 修复连字符姓氏残留空格："Quizhpi- Gomez"
    toks = name.replace(".", " ").split()
    if len(toks) == 1:
        return toks[0].upper(), False
    cut = len(toks) - 1
    while cut > 1 and toks[cut - 1].lower() in PARTICLES:
        cut -= 1
    given, sur_toks = toks[:cut], toks[cut:]
    full = [t for t in toks if len(t) > 1 and t.lower() not in PARTICLES]
    has_particle = any(t.lower() in PARTICLES for t in toks)
    # 无逗号、无小品词的 3 词姓名无法区分中间名与复合姓氏；更多完整词及多人字段同样不硬猜。
    if (len(full) >= 4 or (len(full) >= 3 and not has_particle)
            or any(t.lower() in PARTICLES for t in given)):
        return name, True
    sur = " ".join(sur_toks).upper().replace("- ", "-")
    return (sur + " " + initials(given)).strip(), False


def authors_str(authors):
    if not authors:
        return "", []
    fmt, review = [], []
    for a in authors:
        f, flag = fmt_author(a)
        fmt.append(f)
        if flag:
            review.append(a)
    if len(fmt) > 3:
        tail = "等" if has_cjk(fmt[0]) else "et al."
        return ", ".join(fmt[:3]) + ", " + tail, review
    return ", ".join(fmt), review


def entry(p, cite_date):
    au, review = authors_str(p.get("authors"))
    tag = TAG.get(p.get("type"), "J")
    title = (p.get("title") or "").rstrip(".")
    year = p.get("year")
    venue = p.get("venue")
    doi = (p.get("doi") or "").replace("https://doi.org/", "")
    url = p.get("url") or ""
    s = "[%s] " % p.get("ref_no", "?")
    if au:
        s += au
        if not au.endswith("et al.") and not au.endswith("等"):
            s += "."
        s += " "
    s += title + "[%s]. " % tag
    if tag == "EB/OL":
        s += "(%s)[%s]. %s." % (year, cite_date, url)
    else:
        if venue:
            s += venue + ", "
        s += str(year)
        volume = p.get("volume")
        issue = p.get("issue")
        page = p.get("page")
        if volume:
            s += ", " + str(volume)
            if issue:
                s += "(%s)" % issue
        elif issue:
            s += ", (%s)" % issue
        if page:
            s += ": " + str(page)
        s += "."
        if doi:
            s += " DOI:" + doi + "."
        elif tag == "D" and url:
            s += " " + url + "."
    return s, review


def suspicious(p):
    warns = []
    for a in p.get("authors") or []:
        if is_corporate(a):
            warns.append("作者栏疑似机构名「%s」——按原样著录，正式引用前核对原文" % a)
    t = (p.get("title") or "").strip()
    if re.search(r"\bAuthor\s*$", t, re.I):
        warns.append("标题末尾残留「Author」，疑似抓取杂质——核对原文标题")
    return warns


def main():
    ap = argparse.ArgumentParser(add_help=True)
    ap.add_argument("papers", nargs="?", default="papers.json")
    ap.add_argument("--out", default=None)
    ap.add_argument("--cite-date", default=time.strftime("%Y-%m-%d"))
    a = ap.parse_args()
    data = json.load(open(a.papers, encoding="utf-8"))
    papers = data["papers"] if isinstance(data, dict) else data
    refs, reviews, susp, excluded = [], [], [], []
    for p in papers:
        if p.get("is_retracted"):
            excluded.append("ref %s《%s》：已标注撤稿，不得进入参考文献"
                            % (p.get("ref_no", "?"), p.get("title") or "(无标题)"))
            continue
        s, review = entry(p, a.cite_date)
        refs.append(s)
        for r in review:
            reviews.append("ref %s 作者「%s」：复合姓氏/疑似多人/机构，脚本不硬猜，请按 GB/T 人工著录"
                           % (p.get("ref_no", "?"), r))
        for w in suspicious(p):
            susp.append("ref %s：%s" % (p.get("ref_no", "?"), w))
    out = ["## 参考文献", ""] + refs
    if excluded:
        out += ["", "## 已排除（撤稿）", ""] + ["- " + x for x in excluded]
    if reviews:
        out += ["", "## 需人工核对（姓名）", ""] + ["- " + x for x in reviews]
    if susp:
        out += ["", "## 可疑题录提醒（交付前人工扫一遍）", ""] + ["- " + x for x in susp]
    out += ["", "> 已知局限：无逗号、无小品词的 3 词及以上姓名已进入人工核对；两词复合姓氏及韩语姓名顺序仍可能无法识别，"
            "交付前请按原文核对（见 SKILL.md 第 9 步清单）。"]
    text = "\n".join(out) + "\n"
    if a.out:
        open(a.out, "w", encoding="utf-8").write(text)
    print(text)


if __name__ == "__main__":
    main()