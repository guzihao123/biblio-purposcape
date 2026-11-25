#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
oa_pdf.py — OA PDF 全文定位与下载（purpose-landscape，仅 Python 标准库）

来源链（全部为开放获取，不绕过付费墙；2026-11-22 增来源分级与 Europe PMC 后备）:
  1. OpenAlex open_access / locations[].pdf_url
  2. Semantic Scholar openAccessPdf（同时取 arXiv ID）
  3. Unpaywall（需邮箱：--email 或环境变量 PURPOSE_LANDSCAPE_EMAIL）
  4. arXiv PDF
  5. Europe PMC 开放接口（一等后备）：全文 XML + 补充材料包；用 JATS XML 取全文、用补充包取原始图
来源分级（按可靠性排序，避免每次都撞同一堵墙）:
  tier 0 = 常规 PDF 直链（Springer/Nature/MDPI/Frontiers/arXiv 等，实测高成功率）
  tier 1 = 低成功率出版社（Elsevier/Science/BMJ/Wiley）：标记 low_success，只试 1 次即换下一家
  tier 2 = Europe PMC 全文 XML（一等后备，非 PDF；成功即保存 fulltext_ref<n>.xml + 可选补充包）
  tier 3 = PMC PDF 直链（要求浏览器 proof-of-work）：降到末位并标记"需浏览器验证"，只试 1 次
CORE 需 API Key，未纳入。

用法:
  python3 oa_pdf.py --doi 10.1371/journal.pone.0000308 [--email you@example.com]
  python3 oa_pdf.py --title "Attention is all you need" [--year 2017]
  python3 oa_pdf.py --papers papers.json [--ref-no 3 --ref-no 5] [--top 10]
      [--download oa_pdfs/] [--out oa_pdf_urls.json] [--json]

说明:
  - 只返回/下载开放获取版本；找不到时给出提示，不退化为其他渠道。
  - --download 按 tier 依次尝试候选链接；PDF 校验文件头 %PDF 后才落盘，
    Europe PMC XML 候选单独落 fulltext_ref<n>.xml 与 supplementaryFiles 包。
  - 纯定位不下载时，结果可写入 --out（--papers 模式默认写到 papers.json 同目录）。
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

UA = {"User-Agent": "purpose-landscape-skill/1.0 (research prototype)"}
MAX_BYTES = 80 * 1024 * 1024

# 分级判据：低成功率出版社（实测对本脚本返回 403）+ PMC 要求浏览器计算校验的 PDF 链接
LOW_SUCCESS_HOSTS = ("sciencedirect.com", "journal-of-hepatology.eu", "elsevier.com",
                     "science.org", "bmj.com", "onlinelibrary.wiley.com", "wiley.com")
PMC_PDF_HOSTS = ("pmc.ncbi.nlm.nih.gov", "ncbi.nlm.nih.gov/pmc")
EUROPEPMC_API = "https://www.ebi.ac.uk/europepmc/webservices/rest"


def http_json(url, headers=None, tries=3, timeout=30):
    hdrs = dict(UA)
    if headers:
        hdrs.update(headers)
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers=hdrs)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            last = e
            if e.code not in (429, 500, 502, 503, 504):
                break
            time.sleep((10 if e.code == 429 else 1.5) * (i + 1))
        except Exception as e:
            last = e
            time.sleep(1.5 * (i + 1))
    raise RuntimeError(str(last))


def http_binary(url, timeout=90, tries=2):
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers=dict(UA, Accept="application/pdf,*/*"))
            with urllib.request.urlopen(req, timeout=timeout) as r:
                ctype = r.headers.get("Content-Type", "")
                data = r.read(MAX_BYTES + 1)
            if len(data) > MAX_BYTES:
                raise RuntimeError("文件超过 %d MB 上限" % (MAX_BYTES // 1024 // 1024))
            return data, ctype
        except Exception as e:
            last = e
            if i < tries - 1:
                time.sleep(2)
    raise RuntimeError(str(last))


def validate_pdf_bytes(data, content_type=""):
    """Reject web pages and truncated responses before any PDF is persisted.

    The standard-library downloader cannot fully parse PDF objects.  It therefore
    checks the required magic header plus the final startxref/EOF chain and the
    xref (or xref-stream object) target.  The application adds a real pdfium parse.
    """
    if not isinstance(data, (bytes, bytearray)):
        raise ValueError("非 PDF 响应：正文不是字节数据")
    data = bytes(data)
    if not data.startswith(b"%PDF"):
        stripped = data.lstrip().lower()
        if "html" in str(content_type or "").casefold() or stripped.startswith(b"<!doctype html") or stripped.startswith(b"<html"):
            raise ValueError("非 PDF 响应：OA 链接返回网页/下载中转页")
        raise ValueError("非 PDF 响应：文件头不是 %PDF")
    tail = data[-1024:]
    final = re.search(rb"startxref\s+(\d+)\s+%%EOF\s*$", tail)
    if final is None:
        raise ValueError("PDF 响应不完整：末尾缺少有效的 startxref/%%EOF")
    offset = int(final.group(1))
    if offset <= 0 or offset >= len(data):
        raise ValueError("PDF 响应不完整：startxref 偏移越界")
    target = data[offset:offset + 64]
    if not (target.startswith(b"xref") or re.match(rb"\d+\s+\d+\s+obj\b", target)):
        raise ValueError("PDF 响应不完整：startxref 未指向 xref 或 xref 流对象")
    if b"/Root" not in data:
        raise ValueError("PDF 响应不完整：缺少文档 Root")
    return data


def http_text(url, timeout=40, tries=2):
    """取 XML/文本（Europe PMC 后备用），成功返回 (text, content_type)。"""
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers=dict(UA, Accept="application/xml,text/xml,*/*"))
            with urllib.request.urlopen(req, timeout=timeout) as r:
                ctype = r.headers.get("Content-Type", "")
                raw = r.read(MAX_BYTES + 1)
            if len(raw) > MAX_BYTES:
                raise RuntimeError("文件超过 %d MB 上限" % (MAX_BYTES // 1024 // 1024))
            return raw.decode("utf-8", "replace"), ctype
        except Exception as e:
            last = e
            if i < tries - 1:
                time.sleep(1.5)
    raise RuntimeError(str(last))


def europepmc_locate(doi):
    """DOI → PMCID（Europe PMC 开放检索接口），失败返回 None。"""
    if not doi:
        return None
    query = urllib.parse.quote('DOI:"%s"' % doi)
    url = "%s/search?query=%s&format=json&resultType=core" % (EUROPEPMC_API, query)
    try:
        data = http_json(url, tries=2)
    except Exception:
        return None
    results = (data.get("resultList") or {}).get("result") or []
    for r in results[:3]:
        pmcid = r.get("pmcid")
        if pmcid:
            return pmcid
    return None


def bare_doi(doi):
    d = (doi or "").strip()
    for p in ("https://doi.org/", "http://doi.org/", "doi:"):
        if d.lower().startswith(p):
            d = d[len(p):]
    return d.strip()


def norm_title(t):
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", (t or "").lower())


def _arxiv_from_text(*vals):
    for v in vals:
        if not v:
            continue
        s = str(v)
        m = re.search(r"10\.48550/arxiv\.([0-9]{4}\.[0-9]{4,5}(?:v\d+)?)", s, re.I)
        if m:
            return m.group(1)
        m = re.search(r"arxiv\.org/(?:abs|pdf)/([0-9]{4}\.[0-9]{4,5}(?:v\d+)?)", s, re.I)
        if m:
            return m.group(1)
    return None


def lookup_openalex_work(doi, email=None):
    if not doi:
        return None
    safe = urllib.parse.quote(doi, safe="/:;()<>[]")
    url = "https://api.openalex.org/works/doi:" + safe
    if email:
        url += "?mailto=" + urllib.parse.quote(email)
    try:
        return http_json(url)
    except Exception:
        return None


def lookup_doi_by_title(title, year=None, email=None):
    params = {"search": title, "per-page": "3"}
    if year:
        params["filter"] = "publication_year:%d" % year
    url = "https://api.openalex.org/works?" + urllib.parse.urlencode(params)
    if email:
        url += "&mailto=" + urllib.parse.quote(email)
    data = http_json(url)
    results = data.get("results") or []
    if not results:
        return None, None
    want = norm_title(title)
    for r in results:
        if norm_title(r.get("title") or r.get("display_name")) == want:
            return bare_doi(r.get("doi")), r.get("title")
    r = results[0]
    return bare_doi(r.get("doi")), r.get("title")


def resolve(doi=None, arxiv_id=None, title=None, year=None, email=None):
    doi = bare_doi(doi)
    resolved_title = None
    if not doi and not arxiv_id and title:
        doi, resolved_title = lookup_doi_by_title(title, year, email)
    candidates = []

    def add(url, source, priority, status="", license_=None, direct=None,
            tier=None, kind="pdf", note="", extra=None):
        if not url:
            return
        url = url.strip()
        if not url or any(c["url"] == url for c in candidates):
            return
        low = url.lower()
        if direct is None:
            direct = low.endswith(".pdf") or "/pdf/" in low or "format=pdf" in low or "type=pdf" in low
        if tier is None:
            if kind == "xml":
                tier = 2
            elif any(h in low for h in PMC_PDF_HOSTS):
                tier = 3
                note = note or "需浏览器验证（PMC proof-of-work），脚本可能只拿到中转页"
            elif any(h in low for h in LOW_SUCCESS_HOSTS):
                tier = 1
                note = note or "低成功率（出版社常拒绝脚本直连），只试一次"
            else:
                tier = 0
        item = {"url": url, "source": source, "priority": priority,
                "is_direct_pdf": bool(direct), "status": status,
                "tier": tier, "kind": kind, "note": note}
        if license_:
            item["license"] = license_
        if extra:
            item.update(extra)
        candidates.append(item)

    if doi:
        work = lookup_openalex_work(doi, email)
        if work:
            resolved_title = resolved_title or work.get("title") or work.get("display_name")
            oa = work.get("open_access") or {}
            if oa.get("is_oa") and oa.get("oa_url"):
                add(oa["oa_url"], "openalex", 1, oa.get("oa_status", "unknown"))
            best = work.get("best_oa_location") or {}
            add(best.get("pdf_url"), "openalex(best)", 1, best.get("version", ""))
            for loc in (work.get("locations") or [])[:8]:
                if loc.get("is_oa"):
                    add(loc.get("pdf_url"), "openalex(location)", 2, loc.get("version", ""))

        try:
            ss = http_json(
                "https://api.semanticscholar.org/graph/v1/paper/DOI:%s"
                "?fields=title,openAccessPdf,externalIds,isOpenAccess" % urllib.parse.quote(doi, safe="/:;()<>[]")
            )
            resolved_title = resolved_title or ss.get("title")
            pdf = ss.get("openAccessPdf") or {}
            if ss.get("isOpenAccess") and pdf.get("url"):
                add(pdf["url"], "semantic_scholar", 1, pdf.get("status", ""))
            arxiv_id = arxiv_id or (ss.get("externalIds") or {}).get("ArXiv")
        except Exception:
            pass

        if email:
            try:
                up = http_json("https://api.unpaywall.org/v2/%s?email=%s"
                               % (urllib.parse.quote(doi, safe="/:;()<>[]"),
                                  urllib.parse.quote(email)))
                best = up.get("best_oa_location") or {}
                add(best.get("url_for_pdf") or best.get("url"), "unpaywall", 1,
                    best.get("version", ""), best.get("license"))
                for loc in (up.get("oa_locations") or [])[:5]:
                    add(loc.get("url_for_pdf") or loc.get("url"),
                        "unpaywall(%s)" % (loc.get("host_type") or "repo"), 2,
                        loc.get("version", ""), loc.get("license"))
            except Exception:
                pass

        # Europe PMC 一等后备：全文 XML + 补充材料包（XML 无真实页码，由 app.fulltext 插章节锚点）
        if doi:
            pmcid = europepmc_locate(doi)
            if pmcid:
                add("%s/%s/fullTextXML" % (EUROPEPMC_API, pmcid),
                    "europepmc_xml", 1, status=pmcid, direct=False, kind="xml",
                    note="开放全文 XML（Europe PMC，一等后备）",
                    extra={"pmcid": pmcid,
                           "supplementary_url": "%s/%s/supplementaryFiles" % (EUROPEPMC_API, pmcid)})

        arxiv_id = arxiv_id or _arxiv_from_text(doi)
    if arxiv_id:
        add("https://arxiv.org/pdf/%s.pdf" % arxiv_id, "arxiv", 1, "preprint", direct=True)

    candidates.sort(key=lambda c: (c.get("tier", 0), not c["is_direct_pdf"], c["priority"]))
    return {"doi": doi, "arxiv_id": arxiv_id, "title": resolved_title, "candidates": candidates}


def safe_filename(res, out_dir):
    base = res.get("doi") or res.get("arxiv_id") or res.get("title") or "paper"
    base = re.sub(r"[^\w.-]+", "_", str(base)).strip("._-")[:120] or "paper"
    path = os.path.join(out_dir, base + ".pdf")
    n = 2
    while os.path.exists(path):
        path = os.path.join(out_dir, "%s_%d.pdf" % (base, n))
        n += 1
    return path


def download(res, out_dir, quiet=False):
    if not res.get("candidates"):
        return None
    emit = (lambda m: print(m, file=sys.stderr)) if quiet else print
    os.makedirs(out_dir, exist_ok=True)
    for c in res["candidates"]:
        tier = c.get("tier", 0)
        tries = 1 if tier in (1, 3) else 2
        if c.get("kind") == "xml":
            try:
                text, ctype = http_text(c["url"], tries=tries)
                if "html" in (ctype or "").lower() and "<article" not in text:
                    raise RuntimeError("XML 候选返回网页")
                if "<article" not in text and "<?xml" not in text:
                    raise RuntimeError("XML 内容不含 article 根节点")
            except Exception as e:
                emit("  全文 XML 未取得 [%s] %s (%s)" % (c["source"], c["url"][:90], e))
                continue
            tag = "ref%s" % res.get("ref_no") if res.get("ref_no") else "paper"
            xml_path = os.path.join(out_dir, "fulltext_%s.xml" % tag)
            with open(xml_path, "w", encoding="utf-8") as f:
                f.write(text)
            emit("  已取得开放全文 XML → %s (%d KB, PMCID=%s)" %
                 (xml_path, len(text) // 1024, c.get("status") or c.get("pmcid") or "?"))
            # 补充材料包：开放获取的原始图常在这里（本轮 [5] 的 Fig.1 即由此取得）
            sup_url = c.get("supplementary_url")
            if sup_url:
                try:
                    blob, ctype = http_binary(sup_url, tries=1)
                    if blob[:2] == b"PK":
                        sup_path = os.path.join(out_dir, "supplementary_%s.zip" % tag)
                        with open(sup_path, "wb") as f:
                            f.write(blob)
                        emit("  已取得补充材料包 → %s (%d KB)" % (sup_path, len(blob) // 1024))
                except Exception as e:
                    emit("  补充材料包未取得（不影响全文）：%s" % str(e)[:80])
            return xml_path
        try:
            data, ctype = http_binary(c["url"], tries=tries)
        except Exception as e:
            emit("  下载失败 [%s] %s (%s)" % (c["source"], c["url"][:90], e))
            continue
        try:
            data = validate_pdf_bytes(data, ctype)
        except Exception as e:
            if "html" in (ctype or "").lower():
                emit("  该链接返回网页（下载中转页/落地页），未保存 [%s] %s；"
                     "可在浏览器打开后另存 PDF" % (c["source"], c["url"][:90]))
            else:
                emit("  非 PDF 或 PDF 不完整，跳过 [%s] %s (%s)" %
                     (c["source"], c["url"][:90], e))
            continue
        path = safe_filename(res, out_dir)
        with open(path, "wb") as f:
            f.write(data)
        emit("  已下载 → %s (%d KB, 来源 %s, tier %d)" %
             (path, len(data) // 1024, c["source"], tier))
        return path
    return None


def print_result(res):
    head = res.get("title") or "(未解析标题)"
    print("\n%s" % head)
    if res.get("doi"):
        print("  DOI: %s" % res["doi"])
    if res.get("arxiv_id"):
        print("  arXiv: %s" % res["arxiv_id"])
    if not res.get("candidates"):
        print("  未找到开放获取版本。可尝试：提供 --email 启用 Unpaywall、机构图书馆、作者主页/ResearchGate、联系作者。")
        return
    print("  找到 %d 个开放获取候选（按可靠性 tier 排序）：" % len(res["candidates"]))
    for i, c in enumerate(res["candidates"], 1):
        flag = "[XML]" if c.get("kind") == "xml" else ("[PDF]" if c["is_direct_pdf"] else "[LINK]")
        note = " — %s" % c["note"] if c.get("note") else ""
        print("   %d. %s [%s] tier%d %s%s" %
              (i, flag, c["source"], c.get("tier", 0), c["url"][:100], note))


def select_papers(papers, ref_nos, top):
    if ref_nos:
        wanted = set(ref_nos)
        return [p for p in papers if p.get("ref_no") in wanted]
    indexed = sorted(enumerate(papers), key=lambda t: (t[1].get("cited_by_count") is None,
                                                       -(t[1].get("cited_by_count") or 0)))
    return [p for _, p in indexed[:max(1, top)]]


def main():
    ap = argparse.ArgumentParser(description="OA PDF 全文定位与下载（仅开放获取来源）")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--doi")
    src.add_argument("--title")
    src.add_argument("--arxiv")
    src.add_argument("--papers", help="papers.json 路径；批量解析 DOI 的 OA PDF")
    ap.add_argument("--year", type=int, default=None, help="配合 --title 的年份过滤")
    ap.add_argument("--email", default=os.environ.get("PURPOSE_LANDSCAPE_EMAIL"),
                    help="Unpaywall/OpenAlex 礼貌邮箱（推荐；未提供则跳过 Unpaywall）")
    ap.add_argument("--ref-no", type=int, action="append", default=None,
                    help="--papers 模式下按引用编号选择，可重复")
    ap.add_argument("--top", type=int, default=10,
                    help="--papers 模式下未指定 --ref-no 时按被引取前 N 篇（默认 10）")
    ap.add_argument("--download", default=None, help="下载目录；依次尝试候选直至成功")
    ap.add_argument("--out", default=None, help="结果 JSON 输出路径")
    ap.add_argument("--json", action="store_true", help="stdout 输出 JSON")
    a = ap.parse_args()

    quiet = a.json
    note = (lambda m: print(m, file=sys.stderr)) if quiet else print
    results = []
    if a.papers:
        with open(a.papers, encoding="utf-8") as f:
            data = json.load(f)
        papers = data.get("papers") if isinstance(data, dict) else data
        chosen = select_papers(papers or [], a.ref_no, a.top)
        if not chosen:
            print("未选中任何论文", file=sys.stderr)
            sys.exit(1)
        for p in chosen:
            doi = p.get("doi")
            arxiv_id = p.get("arxiv_id") or _arxiv_from_text(doi, p.get("pdf_url"), p.get("url"))
            try:
                r = resolve(doi=doi, arxiv_id=arxiv_id, title=p.get("title"), email=a.email)
            except Exception as e:
                note("解析失败 ref_no=%s: %s" % (p.get("ref_no"), e))
                results.append({"ref_no": p.get("ref_no"), "title": p.get("title"),
                                "doi": bare_doi(doi), "arxiv_id": arxiv_id,
                                "candidates": [], "error": str(e)})
                continue
            r["ref_no"] = p.get("ref_no")
            r["title"] = r.get("title") or p.get("title")
            results.append(r)
            if not quiet:
                print_result(r)
            if a.download:
                download(r, a.download, quiet)
            time.sleep(1.0)
        out = a.out or os.path.join(os.path.dirname(os.path.abspath(a.papers)) or ".", "oa_pdf_urls.json")
    else:
        arxiv_id = a.arxiv or _arxiv_from_text(a.doi)
        try:
            r = resolve(doi=a.doi, arxiv_id=arxiv_id, title=a.title, year=a.year, email=a.email)
        except Exception as e:
            print("定位失败: %s" % e, file=sys.stderr)
            sys.exit(1)
        results = [r]
        if not quiet:
            print_result(r)
        if a.download:
            download(r, a.download, quiet)
        out = a.out

    if out:
        clean = [{k: v for k, v in r.items() if not k.startswith("_")} for r in results]
        with open(out, "w", encoding="utf-8") as f:
            json.dump({"resolved_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                       "count": len(clean), "results": clean},
                      f, ensure_ascii=False, indent=2)
        note("\n结果已写入: " + out)
    if a.json:
        print(json.dumps([{k: v for k, v in r.items() if not k.startswith("_")} for r in results],
                         ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()