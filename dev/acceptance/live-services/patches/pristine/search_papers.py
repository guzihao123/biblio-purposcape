#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
search_papers.py — purpose-landscape 技能的论文检索脚本（仅用 Python 标准库）

用法:
  python3 search_papers.py openalex --query "lung nodule detection" [--from-year 2023] [--limit 30]
      [--sort recency|citations|relevance] [--out papers.json] [--count-only]
  python3 search_papers.py arxiv --query "lung nodule detection" [--limit 15]
      [--sort recency|relevance] [--out papers.json] [--count-only]
  python3 search_papers.py semantic_scholar --query "lung nodule detection" [--from-year 2023]
      [--limit 15] [--sort recency|citations|relevance] [--out s2.json] [--count-only]
  python3 search_papers.py crossref --query "课后服务 学业" [--from-year 2023] [--limit 15]
      [--sort recency|citations|relevance] [--out crossref.json] [--count-only]

输出: stdout 打印紧凑清单(每篇一行)+统计; 完整数据(含摘要)写入 --out 指定的 JSON 文件。
证据等级: A=有开放全文链接, B=仅有摘要, C=仅有题录。
Semantic Scholar 为可选补充源(无需密钥, 未设 S2_API_KEY 时约 1 请求/3 秒)；其记录不含
referenced_works，不参与引用网络建边；多 --query 时逐条请求后本地合并去重。
Crossref 为补充检索源(2026-11-20 接入，免费无 key)：中文词与题录/DOI 补全场景；词袋
匹配(非严格 AND，计数只作副信号、噪声靠相关性剔除兜底)；撤稿按 update-to 含 retraction
判定；reference 内含 DOI 的条目以 DOI URL 形式写入 referenced_works(与 OpenAlex id 不互
通，仅池内 Crossref 篇可互引建边)；429 限流由 fetch() 退避重试。
OpenAlex 篇另含 institutions/countries（机构与国家码，来自 authorships，供国内外对比
的池内统计用，2026-11-22 接入）；arXiv/Crossref/S2 篇该字段为空数组，统计须注明覆盖。
"""
import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

UA = {"User-Agent": "purpose-landscape-skill/1.0 (research prototype)"}


def fetch(url, tries=3, headers=None):
    hdrs = dict(UA)
    if headers:
        hdrs.update(headers)
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers=hdrs)
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.read().decode("utf-8")
        except Exception as e:
            last = e
            code = getattr(e, "code", None)
            if code is not None and code not in (429, 500, 502, 503, 504):
                break
            time.sleep((10 if code == 429 else 1.5) * (i + 1))
    raise RuntimeError(str(last))


def evidence_level(p):
    if p.get("oa_url") or p.get("pdf_url"):
        return "A"
    if p.get("abstract"):
        return "B"
    return "C"


def abstract_from_inverted(inv):
    if not isinstance(inv, dict) or not inv:
        return None
    pos = {}
    for w, ps in inv.items():
        for i in ps:
            pos[i] = w
    text = " ".join(pos[i] for i in sorted(pos)).strip()
    return text or None


def search_openalex(a):
    limit = min(a.limit, 50)
    # 标题+摘要匹配，比全文 search= 精准：计数信号真实、取回噪声低（流程问题1）
    # 多 --query 用 | 在 OpenAlex filter 内做 OR
    filters = ["title_and_abstract.search:" + "|".join(a.query)]
    if a.from_year:
        filters.append("from_publication_date:%d-01-01" % a.from_year)
    params = {"per-page": "1" if a.count_only else str(limit), "filter": ",".join(filters)}
    if a.sort == "recency":
        params["sort"] = "publication_date:desc"
    elif a.sort == "citations":
        params["sort"] = "cited_by_count:desc"
    url = "https://api.openalex.org/works?" + urllib.parse.urlencode(params)
    data = json.loads(fetch(url))
    total = data.get("meta", {}).get("count", 0)
    if a.count_only:
        yr = (", %d年起" % a.from_year) if a.from_year else ""
        print("OpenAlex 命中总数(标题+摘要): %d  (query=\"%s\"%s)" % (total, " OR ".join(a.query), yr))
        if a.phrase_count:
            pf = ['title_and_abstract.search:"%s"' % a.query[0]]
            if a.from_year:
                pf.append("from_publication_date:%d-01-01" % a.from_year)
            purl = "https://api.openalex.org/works?" + urllib.parse.urlencode({"per-page": "1", "filter": ",".join(pf)})
            pt = json.loads(fetch(purl)).get("meta", {}).get("count", 0)
            print("  其中整串短语精确匹配: %d（太少说明词组偏窄，可放宽）" % pt)
        return
    papers = []
    for w in data.get("results", []):
        authors = [x.get("author", {}).get("display_name") for x in (w.get("authorships") or [])[:5]]
        authors = [x for x in authors if x]
        institutions, countries = [], []
        for x in (w.get("authorships") or []):
            for inst in (x.get("institutions") or []):
                nm = inst.get("display_name")
                cc = inst.get("country_code")
                if nm and nm not in institutions:
                    institutions.append(nm)
                if cc and cc not in countries:
                    countries.append(cc)
            for cc in (x.get("countries") or []):
                if cc and cc not in countries:
                    countries.append(cc)
        src = (w.get("primary_location") or {}).get("source") or {}
        p = {
            "source": "openalex",
            "id": w.get("id"),
            "title": w.get("title") or w.get("display_name") or "(无标题)",
            "year": w.get("publication_year"),
            "authors": authors,
            "venue": src.get("display_name"),
            "cited_by_count": w.get("cited_by_count", 0),
            "doi": w.get("doi"),
            "url": w.get("doi") or w.get("id"),
            "oa_url": (w.get("open_access") or {}).get("oa_url"),
            "pdf_url": None,
            "abstract": abstract_from_inverted(w.get("abstract_inverted_index")),
            "type": w.get("type"),
            "language": w.get("language"),
            "institutions": institutions,
            "countries": countries,
            "is_retracted": bool(w.get("is_retracted")),
            "referenced_works": w.get("referenced_works") or [],
        }
        p["evidence_level"] = evidence_level(p)
        t = (p["title"] or "").lower()
        if t.startswith("retraction") or t.startswith("retracted") or "撤稿" in t or t.startswith("corrigendum"):
            p["is_retracted"] = True
        papers.append(p)
    finish(papers, total, a, "openalex")


NS = {"atom": "http://www.w3.org/2005/Atom",
      "opensearch": "http://a9.com/-/spec/opensearch/1.1/",
      "arxiv": "http://arxiv.org/schemas/atom"}


def search_arxiv(a):
    limit = min(a.limit, 50)
    multi = len(a.query) > 1
    raw = " OR ".join(a.query) if multi else a.query[0].strip()
    user_quoted = raw.startswith('"')
    words = raw.strip('"').split()

    def run(sq):
        params = {"search_query": sq, "start": "0",
                  "max_results": "1" if a.count_only else str(limit)}
        if a.sort != "relevance":
            params["sortBy"] = "submittedDate"
            params["sortOrder"] = "descending"
        url = "https://export.arxiv.org/api/query?" + urllib.parse.urlencode(params)
        r = ET.fromstring(fetch(url))
        te = r.find("opensearch:totalResults", NS)
        t = int(te.text) if te is not None and te.text else 0
        return r, t

    # 多词查询先强制短语匹配，避免松匹配捞回不相关论文
    phrase = raw if (user_quoted or multi) else ('"%s"' % raw if " " in raw else raw)
    root, total = run("all:" + phrase)
    # 短语 0 命中（3-4 词长短语几乎必然不逐字出现）→ 降级为逐词 AND：每个词都须出现，
    # 比整串短语宽松、比单词松匹配严格。第二次压力测试发现并修复。多 query OR 不做此降级。
    if total == 0 and not user_quoted and not multi and len(words) >= 2:
        root, total = run(" AND ".join("all:" + w for w in words))
        print("arXiv 短语 0 命中，降级为逐词 AND 重试 (query=\"%s\")" % raw)
    if a.count_only:
        print("arXiv 命中总数: %d  (query=\"%s\")" % (total, a.query))
        return
    papers = []
    for e in root.findall("atom:entry", NS):
        def txt(tag):
            el = e.find(tag, NS)
            return " ".join(el.text.split()) if el is not None and el.text else None
        id_url = txt("atom:id") or ""
        arxiv_id = id_url.replace("http://arxiv.org/abs/", "").replace("https://arxiv.org/abs/", "")
        authors = [" ".join(n.text.split()) for n in e.findall("atom:author/atom:name", NS)[:5] if n.text]
        published = txt("atom:published") or ""
        p = {
            "source": "arxiv",
            "id": arxiv_id,
            "title": txt("atom:title") or "(无标题)",
            "year": int(published[:4]) if published[:4].isdigit() else None,
            "authors": authors,
            "venue": "arXiv preprint",
            "cited_by_count": None,
            "doi": txt("arxiv:doi"),
            "url": id_url,
            "oa_url": id_url,
            "pdf_url": id_url.replace("/abs/", "/pdf/"),
            "abstract": txt("atom:summary"),
            "type": "preprint",
            "language": "en",
            "institutions": [],
            "countries": [],
        }
        p["evidence_level"] = evidence_level(p)
        papers.append(p)
    finish(papers, total, a, "arxiv")


S2_FIELDS = ("title,authors,year,citationCount,externalIds,openAccessPdf,"
             "abstract,venue,journal,publicationTypes,isOpenAccess")
S2_BULK = "https://api.semanticscholar.org/graph/v1/paper/search/bulk"


def _title_key(title):
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", (title or "").lower())


def _fetch_s2(url, headers=None, tries=4):
    """S2 专用请求：429 时按 30/60/90 秒退避（未设密钥时全局限流很常见）。"""
    hdrs = dict(UA)
    if headers:
        hdrs.update(headers)
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers=hdrs)
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            last = e
            if e.code == 429:
                wait = 30 * (i + 1)
                ra = e.headers.get("Retry-After") if e.headers else None
                if ra and str(ra).isdigit():
                    wait = max(wait, int(ra))
                print("Semantic Scholar 限流(429)，等待 %d 秒后重试 (%d/%d)..." % (wait, i + 1, tries))
                time.sleep(wait)
                continue
            if e.code in (500, 502, 503, 504):
                time.sleep(3 * (i + 1))
                continue
            body = e.read().decode("utf-8", "replace")[:200]
            raise RuntimeError("HTTP %s: %s" % (e.code, body))
        except Exception as e:
            last = e
            time.sleep(2 * (i + 1))
    raise RuntimeError("Semantic Scholar 仍不可用（多为限流，可稍后重试或设置 S2_API_KEY）: %s" % last)


def _s2_sort(papers, mode):
    if mode == "recency":
        papers.sort(key=lambda p: (p.get("year") is None, -(p.get("year") or 0)))
    elif mode == "citations":
        papers.sort(key=lambda p: (p.get("cited_by_count") is None,
                                   -(p.get("cited_by_count") or 0)))
    return papers


def search_semantic_scholar(a):
    """Semantic Scholar 补充源（bulk 端点）：无需密钥（S2_API_KEY 可提额）。
    bulk 单次最多返回 1000 条、不支持 relevance 排序，因此默认按被引降序取回后本地截断；
    recency 用 publicationDate:desc。记录不含 referenced_works，撤稿仅按标题启发式判断。"""
    limit = min(a.limit, 100)
    headers = {}
    if os.environ.get("S2_API_KEY"):
        headers["x-api-key"] = os.environ["S2_API_KEY"]
    terms = ['"%s"' % q.strip().strip('"') for q in a.query if q.strip()]
    query = " | ".join(terms)
    sort = "publicationDate:desc" if a.sort == "recency" else "citationCount:desc"
    params = {"query": query, "fields": S2_FIELDS, "sort": sort}
    if a.from_year:
        params["year"] = "%d-" % a.from_year
    url = S2_BULK + "?" + urllib.parse.urlencode(params)
    data = _fetch_s2(url, headers)
    total = data.get("total", 0)
    if a.count_only:
        yr = (", %d年起" % a.from_year) if a.from_year else ""
        print("Semantic Scholar 命中总数(约): %d  (query=\"%s\"%s)" % (total, query, yr))
        print("  注：S2 total 为近似值、检索语义与 OpenAlex 不同，仅作副信号；"
              "术语计数与分图统计以 OpenAlex 为准。")
        return
    rows = data.get("data") or []
    if a.sort == "relevance":
        print("  注：S2 bulk 不提供 relevance 排序，已按被引降序取回；引用编号仍以 OpenAlex/arXiv 为主。")
    papers = []
    for it in rows:
        ext = it.get("externalIds") or {}
        authors = [x.get("name") for x in (it.get("authors") or [])[:5]]
        authors = [x for x in authors if x]
        pdf = (it.get("openAccessPdf") or {}).get("url")
        doi = ext.get("DOI")
        pid = it.get("paperId")
        types = it.get("publicationTypes") or []
        p = {
            "source": "semantic_scholar",
            "id": pid,
            "title": it.get("title") or "(无标题)",
            "year": it.get("year"),
            "authors": authors,
            "venue": it.get("venue") or ((it.get("journal") or {}).get("name")),
            "cited_by_count": it.get("citationCount"),
            "doi": ("https://doi.org/" + doi) if doi else None,
            "url": (("https://www.semanticscholar.org/paper/" + pid) if pid
                    else (("https://doi.org/" + doi) if doi else None)),
            "oa_url": pdf,
            "pdf_url": pdf,
            "abstract": it.get("abstract"),
            "type": (types[0] if types else None),
            "language": None,
            "institutions": [],
            "countries": [],
            "is_retracted": False,
            "referenced_works": [],
            "arxiv_id": ext.get("ArXiv"),
        }
        p["evidence_level"] = evidence_level(p)
        t = (p["title"] or "").lower()
        if t.startswith("retraction") or t.startswith("retracted") or "撤稿" in t:
            p["is_retracted"] = True
        papers.append(p)
    seen, uniq = set(), []
    for p in papers:
        k = (p.get("doi") or "").lower() or _title_key(p["title"])
        if k in seen:
            continue
        seen.add(k)
        uniq.append(p)
    finish(_s2_sort(uniq, a.sort)[:limit], total, a, "semantic_scholar")


CR_SELECT = ("DOI,title,author,container-title,volume,issue,page,issued,published,"
             "is-referenced-by-count,type,publisher,language,abstract,reference,update-to")


def _cr_clean_abstract(ab):
    if not ab:
        return None
    text = re.sub(r"<[^>]+>", " ", ab or "")
    text = re.sub(r"\s+", " ", text).strip()
    return text or None


def _cr_authors(msg):
    out = []
    for x in msg.get("author") or []:
        if x.get("given") and x.get("family"):
            out.append("%s %s" % (x["given"], x["family"]))
        elif x.get("name"):
            out.append(x["name"])
        elif x.get("family"):
            out.append(x["family"])
    return out


def search_crossref(a):
    """Crossref 补充检索源（免费无 key，2026-11-20 接入）。题录/DOI/卷期页最权威；
    词袋匹配（非严格 AND），中文检索有效（Crossref 注册中文期刊）。"""
    limit = min(a.limit, 100)
    params = {"query.bibliographic": " ".join(a.query),
              "rows": "1" if a.count_only else str(limit),
              "select": CR_SELECT}
    if a.from_year:
        params["filter"] = "from-pub-date:%d-01-01" % a.from_year
    if a.sort == "citations":
        params["sort"] = "is-referenced-by-count"
        params["order"] = "desc"
    elif a.sort == "recency":
        params["sort"] = "published"
        params["order"] = "desc"
    url = "https://api.crossref.org/works?" + urllib.parse.urlencode(params)
    try:
        data = json.loads(fetch(url))
    except RuntimeError as e:
        if "400" in str(e) or "Bad Request" in str(e):
            params.pop("select", None)
            url = "https://api.crossref.org/works?" + urllib.parse.urlencode(params)
            data = json.loads(fetch(url))
        else:
            raise
    msg = data.get("message", {})
    total = msg.get("total-results", 0)
    if a.count_only:
        yr = (", %d年起" % a.from_year) if a.from_year else ""
        print("Crossref 命中总数(词袋匹配): %d  (query=\"%s\"%s)" % (total, " ".join(a.query), yr))
        print("  注：Crossref 为词袋匹配（非严格 AND），计数只作副信号，噪声靠相关性剔除兜底。")
        return
    papers = []
    for w in msg.get("items", []):
        doi = w.get("DOI")
        refs = ["https://doi.org/" + r["DOI"] for r in (w.get("reference") or []) if r.get("DOI")]
        updates = w.get("update-to") or []
        is_retracted = any("retract" in (str(u.get("type", "")) + str(u.get("label", ""))).lower()
                           for u in updates)
        year = None
        for k in ("published", "issued"):
            dp = (w.get(k) or {}).get("date-parts") or []
            if dp and dp[0] and dp[0][0]:
                year = dp[0][0]
                break
        doi_url = ("https://doi.org/" + doi) if doi else None
        p = {
            "source": "crossref",
            "id": doi_url,
            "title": _cr_clean_abstract((w.get("title") or [""])[0]) or "(无标题)",
            "year": year,
            "authors": _cr_authors(w),
            "venue": (w.get("container-title") or [None])[0],
            "cited_by_count": w.get("is-referenced-by-count", 0),
            "doi": doi_url,
            "url": doi_url,
            "oa_url": None,
            "pdf_url": None,
            "abstract": _cr_clean_abstract(w.get("abstract")),
            "type": w.get("type"),
            "language": w.get("language"),
            "institutions": [],
            "countries": [],
            "is_retracted": is_retracted,
            "referenced_works": refs,
            "volume": w.get("volume"),
            "issue": w.get("issue"),
            "page": w.get("page"),
            "publisher": w.get("publisher"),
        }
        p["evidence_level"] = evidence_level(p)
        t = (p["title"] or "").lower()
        if t.startswith("retraction") or t.startswith("retracted") or "撤稿" in t or t.startswith("corrigendum"):
            p["is_retracted"] = True
        papers.append(p)
    finish(papers, total, a, "crossref")


def finish(papers, total, a, source):
    out = a.out or (source + "_papers.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump({"query": a.query, "source": source, "total_hits": total,
                   "retrieved_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "papers": papers},
                  f, ensure_ascii=False, indent=2)
    levels = {"A": 0, "B": 0, "C": 0}
    for p in papers:
        levels[p["evidence_level"]] += 1
    print("[%s] 命中总数 %d, 本次取回 %d 篇 (A级全文:%d B级摘要:%d C级题录:%d)"
          % (source, total, len(papers), levels["A"], levels["B"], levels["C"]))
    for i, p in enumerate(papers, 1):
        t = p["title"]
        if len(t) > 90:
            t = t[:90] + "…"
        cited = "-" if p["cited_by_count"] is None else p["cited_by_count"]
        flag = " ⚠已撤稿" if p.get("is_retracted") else ""
        print("[%d] %s | 被引%s | %s | %s%s" % (i, p["year"] or "?", cited, p["evidence_level"], t, flag))
    print("完整数据(含摘要)已写入: " + out)


def stats_openalex(a):
    """聚合统计（group_by）：只取分组计数，不下载论文。--stats year=年度趋势 /
    topics=主题分布；--topic-series <topic_id>=该主题的年度序列（比较分析用）。"""
    if not a.out:
        print("统计模式必须用 --out 指定输出 JSON 文件")
        sys.exit(1)
    filters = ["title_and_abstract.search:" + "|".join(a.query)]
    if a.from_year:
        filters.append("from_publication_date:%d-01-01" % a.from_year)
    if a.topic_series:
        filters.append("topics.id:" + a.topic_series)
        gb = "publication_year"
    elif a.stats == "year":
        gb = "publication_year"
    else:
        gb = "topics.id"
    # group_by 模式下 per-page 控制返回的分组数（不是论文数），取上限 200
    params = {"per-page": "200", "filter": ",".join(filters), "group_by": gb}
    data = json.loads(fetch("https://api.openalex.org/works?" + urllib.parse.urlencode(params)))
    groups = [{"key": g.get("key"), "name": g.get("key_display_name") or str(g.get("key")),
               "count": g.get("count", 0)} for g in data.get("group_by", [])]
    if gb == "publication_year":
        groups = [g for g in groups if str(g["key"]).isdigit()]
        groups.sort(key=lambda g: int(g["key"]))
    else:
        groups.sort(key=lambda g: -g["count"])
    total = data.get("meta", {}).get("count", 0)
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump({"queries": a.query, "from_year": a.from_year, "group_by": gb,
                   "topic_series": a.topic_series, "total_hits": total, "groups": groups},
                  f, ensure_ascii=False, indent=2)
    print("OpenAlex 聚合(group_by=%s): 命中总数 %d, 分组数 %d" % (gb, total, len(groups)))
    for g in groups[:12]:
        print("  %s: %d" % (g["name"], g["count"]))
    print("完整分组已写入: " + a.out)


def main():
    ap = argparse.ArgumentParser(add_help=True)
    ap.add_argument("source", choices=["openalex", "arxiv", "semantic_scholar", "crossref"])
    ap.add_argument("--query", required=True, action="append",
                    help="可重复传多个术语；检索/统计时按 OR 合并")
    ap.add_argument("--from-year", type=int, default=None)
    ap.add_argument("--limit", type=int, default=30)
    ap.add_argument("--sort", choices=["recency", "citations", "relevance"], default="relevance")
    ap.add_argument("--out", default=None)
    ap.add_argument("--count-only", action="store_true")
    ap.add_argument("--phrase-count", action="store_true",
                    help="计数时额外给出整串短语精确匹配数（精确度副信号，仅 OpenAlex）")
    ap.add_argument("--stats", choices=["year", "topics"], default=None,
                    help="聚合统计模式（仅 OpenAlex）：year=年度趋势分组，topics=主题分布分组；需 --out")
    ap.add_argument("--topic-series", default=None, metavar="TOPIC_ID",
                    help="取指定 OpenAlex topic 的年度发文序列（比较分析用；仅 OpenAlex）；需 --out")
    a = ap.parse_args()
    try:
        if a.stats or a.topic_series:
            if a.source != "openalex":
                print("聚合统计仅支持 openalex")
                sys.exit(1)
            stats_openalex(a)
        elif a.source == "openalex":
            search_openalex(a)
        elif a.source == "semantic_scholar":
            search_semantic_scholar(a)
        elif a.source == "crossref":
            search_crossref(a)
        else:
            search_arxiv(a)
    except Exception as e:
        print("检索失败(%s): %s。可稍后重试或换用另一数据源。" % (a.source, e))
        sys.exit(1)


if __name__ == "__main__":
    main()