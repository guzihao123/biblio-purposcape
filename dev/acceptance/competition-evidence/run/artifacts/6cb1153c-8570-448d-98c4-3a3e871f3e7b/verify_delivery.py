#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""交付前脚本复核（purpose-landscape SKILL.md 第 9 步 7a，强制；预置已测脚本）。
对回 papers.json 逐项机械核验交付物，输出 verify_report.txt 到脚本所在目录。不得以自报代替。

八项：
  ①证据等级：台账每条等级 = papers.json 对应 ref_no 的 evidence_level。
  ②B级标注：含 B 级引用的论断句必须带"（据摘要）"或"（部分据摘要）"。
  ③原句逐字回验（双轨，2026-11-22）：
     ③摘要通道：台账每条支撑原句，空白归一化后逐字包含于该篇 abstract（默认必过）。
     ③全文通道：台账第 5/6 列给出「全文定位|全文原句」时，额外到 fulltext_ref<n>.txt
       指定页/节逐字回验；文件缺失自动回落摘要通道、不判失败；原句不匹配判失败。
  ④数字绑定台账：正文论断数字优先绑定台账"数字→原句"（数字须出现在所引 ref 的台账原句里）；
     未绑定但在摘要出现的标"待人工确认"（防结构性/巧合匹配），摘要也找不到的判失败。
  ⑤字数：正文 CJK 字数落在用途区间（默认 A 1500-2500；D 3000-6000；C1/C2 各 800-1200，由第二参数传入）；
     C1/C2 支持英文交付，英文按词、中文按汉字，混合文本合计。
  ⑥参考文献完整性：正文每个 [n] 有同号条目、条目均挂到 ref_no、无撤稿；
     B/C 模式必须存在 citation_map.json，缺失即失败；
     若同目录有 citation_map.json，则正文/文献表编号为交付序号，按 display_to_ref 映射回 ref_no，
     并检查正文引用首次出现顺序为 1,2,3…。
  ⑦无摘要不得被正文引用：abstract 为空的 ref_no 出现在正文 [n] 即失败。
  ⑧模式形态（--mode A/A_DIALOGUE/B/C1/C2/D，2026-11-20 增）：按模式检查必含构件/首段分叉/禁词/指向密度/
     防虚构/卡片数；C1 另查 Research Gap 分析表完整数据行与池内 [n] 证据、完整引言第三段空白及第 4/5 段回应；
     C2 另查五列研究空白分析表完整数据行与池内 [n] 证据、空白点及证据纳入完整综述、六列比较表与 PRISMA 执行记录。
     C1+C2 必须分别按 --mode C1、--mode C2 复核；--mode C2 在同目录存在 C1_引言.md 时另查“衔接与重复检查”中的
     空白一致性、重复处理、交叉指向及两份文本的长段落重复。非法模式（含 --mode C 或所谓“研究空白”模式）直接退出，
     不得跳过形态检查。机器口径见 modes.md 各模式"形态硬门禁"；未传 --mode 时跳过（向后兼容）。

用法：把本脚本复制到 <输出目录> 后运行 `python3 verify_delivery.py [交付正文文件] [字数区间] [--mode A|A_DIALOGUE|B|C1|C2|D]`。
  默认正文文件 综述初稿.md（形式 B）；形式 A/C 先把 Word/PPT 抽成纯文本（含参考文献）存为 md 再传入。
  脚本读同目录的 papers.json / evidence_ledger.md / search_log.md（如有）/ 正文，报告写同目录 verify_report.txt。
退出码：0=无失败项（待人工确认项会在报告中列出，须交付说明披露）；1=有失败项，须改正重跑。
"""
import json, os, re, sys

D = os.path.dirname(os.path.abspath(__file__))
draft_name = sys.argv[1] if len(sys.argv) > 1 else "综述初稿.md"
# 用途字数区间：默认 A 基线 1500-2500；D 传 3000-6000；C1/C2 各传 800-1200
range_arg = sys.argv[2] if len(sys.argv) > 2 else "1500-2500"
LO, HI = (int(x) for x in range_arg.split("-"))
mode_arg = None
if "--mode" in sys.argv:
    _mi = sys.argv.index("--mode")
    if _mi + 1 >= len(sys.argv):
        print("缺少模式值；C 模式必须分别使用 --mode C1 或 --mode C2。")
        sys.exit(2)
    mode_arg = sys.argv[_mi + 1]
VALID_MODES = {"A", "A_DIALOGUE", "B", "C1", "C2", "D"}
if mode_arg is not None and mode_arg not in VALID_MODES:
    print("未知模式: %s；C 模式必须分别使用 --mode C1 或 --mode C2。" % mode_arg)
    sys.exit(2)

papers = {p["ref_no"]: p for p in json.load(open(os.path.join(D, "papers.json"), encoding="utf-8"))["papers"]}
citation_map_path = os.path.join(D, "citation_map.json")
display_to_ref = {}
map_drafts = []
if os.path.exists(citation_map_path):
    map_data = json.load(open(citation_map_path, encoding="utf-8"))
    display_to_ref = {int(k): int(v) for k, v in map_data.get("display_to_ref", {}).items()}
    map_drafts = map_data.get("drafts", [])

def pool_ref(n):
    return display_to_ref.get(n, n) if display_to_ref else n

draft = open(os.path.join(D, draft_name), encoding="utf-8").read()
ledger = open(os.path.join(D, "evidence_ledger.md"), encoding="utf-8").read()
search_log_path = os.path.join(D, "search_log.md")
search_log = open(search_log_path, encoding="utf-8").read() if os.path.exists(search_log_path) else ""
body = draft.split("## 参考文献")[0]
refsec = draft.split("## 参考文献")[1] if "## 参考文献" in draft else ""

def norm(s):
    return re.sub(r"\s+", " ", (s or "")).strip()

# 英文数词→数字（摘要里拼写的数字，如 Forty-two=42）
UNITS = ["zero","one","two","three","four","five","six","seven","eight","nine","ten",
         "eleven","twelve","thirteen","fourteen","fifteen","sixteen","seventeen","eighteen","nineteen"]
TENS = {"twenty":20,"thirty":30,"forty":40,"fifty":50,"sixty":60,"seventy":70,"eighty":80,"ninety":90}
# 葡/西语数字词（拉美文献常见，流程问题3）+ 法/德常用十位。
# 刻意排除 once/cent/dos/uno 等"恰好也是英文单词"的词，避免把英文 once(曾经)/cent(分) 误转成数字。
ML_WORDS = {
    "três":3,"tres":3,"quatro":4,"cinco":5,"seis":6,"sete":7,"oito":8,"nove":9,"dez":10,
    "onze":11,"doze":12,"treze":13,"catorze":14,"quatorze":14,"quinze":15,"dezesseis":16,
    "dezasseis":16,"dezessete":17,"dezassete":17,"dezoito":18,"dezenove":19,"dezanove":19,
    "vinte":20,"trinta":30,"quarenta":40,"cinquenta":50,"sessenta":60,"setenta":70,
    "oitenta":80,"noventa":90,"cem":100,"dois":2,"duas":2,
    "cero":0,"cuatro":4,"siete":7,"ocho":8,"nueve":9,"diez":10,"doce":12,"trece":13,
    "catorce":14,"quince":15,"dieciseis":16,"dieciséis":16,"diecisiete":17,"dieciocho":18,
    "diecinueve":19,"veinte":20,"treinta":30,"cuarenta":40,"cincuenta":50,"sesenta":60,
    "ochenta":80,"cien":100,"ciento":100,
    "vingt":20,"trente":30,"quarante":40,"cinquante":50,"soixante":60,
    "zwanzig":20,"dreißig":30,"dreissig":30,"vierzig":40,"fünfzig":50,"fuenfzig":50,
    "sechzig":60,"siebzig":70,"achtzig":80,"neunzig":90,"hundert":100,
}
_ML_PAT = re.compile(r"\b(" + "|".join(sorted(ML_WORDS, key=len, reverse=True)) + r")\b", re.I)
def augment_numbers(text):
    def tens_repl(m):
        v = TENS[m.group(1).lower()]
        if m.group(2):
            v += UNITS.index(m.group(2).lower())
        return str(v)
    t = re.sub(r"\b(twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety)(?:[-\s](one|two|three|four|five|six|seven|eight|nine))?\b",
               tens_repl, text, flags=re.I)
    t = re.sub(r"\b(" + "|".join(UNITS) + r")\b", lambda m: str(UNITS.index(m.group(0).lower())), t, flags=re.I)
    t = _ML_PAT.sub(lambda m: str(ML_WORDS[m.group(0).lower()]), t)
    return t

def quant_numbers(s):
    """抽取论断数字：去引用标记[n]、分离比较符、排除字母+数字标识符（AZD5069/p53/PD-L1/11q13/S1P/CXCR2/CD8 等）。"""
    s = re.sub(r"\[\d+(?:-\d+)?\]", " ", s)
    s = re.sub(r"([=><])", r" \1 ", s)
    toks = re.split(r"[\s\u4e00-\u9fff\u3000-\u303f\uff00-\uffef]+", s)
    nums = set()
    for t in toks:
        if re.search(r"[A-Za-z]", t) and re.search(r"\d", t):
            continue
        nums.update(re.findall(r"\d+(?:\.\d+)?", t))
    return nums

# 解析台账
rows = []
for line in ledger.splitlines():
    line = line.strip()
    if not line.startswith("|"):
        continue
    cells = [c.strip() for c in line.strip("|").split("|")]
    if len(cells) < 4 or not cells[1].isdigit():
        continue
    # 双轨证据链（2026-11-22）：第 5/6 列可选 = 全文来源定位 / 全文原句。
    # 定位格式：fulltext_ref7.txt @ page 5 或 fulltext_ref5.txt @ sec METHODS（分隔符用 @，不能用 |）。
    rows.append({"claim": cells[0], "ref": int(cells[1]), "quote": cells[2], "level": cells[3],
                 "full_loc": cells[4] if len(cells) > 4 else "",
                 "full_quote": cells[5] if len(cells) > 5 else ""})

report, fails, warns = [], {}, []
def log(check, ok, detail):
    report.append(("PASS" if ok else "FAIL", check, detail))
    if not ok:
        fails.setdefault(check, []).append(detail)

# ① 证据等级
bad = []
for r in rows:
    p = papers.get(r["ref"])
    if not p:
        bad.append("ref %d 不在 papers.json" % r["ref"]); continue
    if r["level"] != p["evidence_level"]:
        bad.append("ref %d 台账标 %s 但 papers.json=%s（%s）" % (r["ref"], r["level"], p["evidence_level"], r["claim"]))
log("①证据等级", not bad, "台账 %d 条逐篇核对 evidence_level；%s" % (len(rows), "全部一致" if not bad else "; ".join(bad)))

# ③ 原句逐字回验（双轨：摘要通道必过；全文通道仅对带 full_loc 的条目额外回验）
def fulltext_slice(loc):
    """loc = 文件名 @ page 7 或 文件名 @ sec METHODS；返回该页/节文本，找不到文件返回 None。"""
    if not loc or "@" not in loc:
        return None
    fn, anchor = [x.strip() for x in loc.split("@", 1)]
    path = os.path.join(D, os.path.basename(fn))
    if not os.path.exists(path):
        return None
    text = open(path, encoding="utf-8").read()
    if not anchor:
        return text
    parts = re.split(r"=== (page \d+|sec [^=]+?) ===", text)
    # parts = [前, 锚点1, 内容1, 锚点2, 内容2, ...]
    for i in range(1, len(parts) - 1, 2):
        if parts[i].strip().lower() == anchor.strip().lower():
            return parts[i + 1]
    return ""

bad, bad_full, full_hit, full_total, full_missing = [], [], 0, 0, []
for r in rows:
    ab = norm(papers.get(r["ref"], {}).get("abstract"))
    if not ab:
        bad.append("ref %d 无摘要，摘要通道无处回验（%s）" % (r["ref"], r["claim"])); continue
    if norm(r["quote"]) not in ab:
        bad.append("ref %d 摘要原句未逐字命中：%s" % (r["ref"], r["quote"][:60]))
    if r.get("full_loc") and r.get("full_quote"):
        full_total += 1
        seg = fulltext_slice(r["full_loc"])
        if seg is None:
            full_missing.append("ref %d 全文文件缺失，回落摘要通道" % r["ref"])
        elif norm(r["full_quote"]) not in norm(seg):
            bad_full.append("ref %d 全文原句未在 %s 逐字命中：%s" % (
                r["ref"], r["full_loc"], r["full_quote"][:60]))
        else:
            full_hit += 1
log("③摘要通道", not bad, "%d/%d 条摘要原句逐字命中（默认必过）" % (len(rows)-len(bad), len(rows)) + ("；" + "; ".join(bad) if bad else ""))
log("③全文通道", not bad_full, "%d/%d 条全文原句在指定页/节逐字命中%s" % (
    full_hit, full_total, "；缺失回落 %d 条" % len(full_missing) if full_missing else "") + ("；" + "; ".join(bad_full) if bad_full else ""))
warns.extend(full_missing)

sentences = [s for s in re.split(r"[。；\n]", body) if s.strip()]
def cited_refs(s):
    return [pool_ref(int(x)) for x in re.findall(r"\[(\d+)\]", s)]

# ② B级标注
bad, b_sent = [], 0
for s in sentences:
    refs = cited_refs(s)
    if refs and any(papers.get(r, {}).get("evidence_level") == "B" for r in refs):
        b_sent += 1
        if "据摘要" not in s:
            bad.append("含B级引用%s缺据摘要标注：%s" % (refs, s.strip()[:50]))
log("②B级据摘要标注", not bad, "含B级引用论断句 %d 个，%s" % (b_sent, "均带据摘要/部分据摘要" if not bad else "; ".join(bad)))

# ④ 数字绑定台账原句（数字按完整 token 匹配，避免 "3"⊂"2.73" 这类子串巧合；未绑定一律待人工确认）
bound_map, unbound = [], []
for s in sentences:
    refs = cited_refs(s)
    if not refs:
        continue
    for tk in sorted(quant_numbers(s)):
        hit = [r for r in rows if r["ref"] in refs and tk in quant_numbers(
            augment_numbers(r["quote"] + " " + (r.get("full_quote") or "")))]
        if hit:
            h = hit[0]
            bound_map.append("%s → ref%d 台账原句「%s」（论断:%s）" % (tk, h["ref"], h["quote"][:50], h["claim"]))
        else:
            unbound.append("%s（句引%s）未绑定台账原句——待人工确认是否结构性/标识符数字（如 S1P 的 1、方向计数的 3）" % (tk, refs))
log("④数字绑定台账", True, "绑定台账原句 %d 个；待人工确认 %d 个（须交付说明披露并逐条人工判定）" % (len(bound_map), len(unbound)))
warns.extend(unbound)

# ⑤ 字数（C1/C2 支持中文汉字与英文词混合计量；其他模式维持 CJK 口径）
cjk = len(re.findall(r"[\u4e00-\u9fff]", body))
english_words = len(re.findall(r"\b[A-Za-z]+(?:[-'][A-Za-z]+)*\b", body)) if mode_arg in {"C1", "C2"} else 0
word_count = cjk + english_words
metric = "CJK 汉字+英文词" if mode_arg in {"C1", "C2"} else "CJK 字数"
log("⑤字数", LO <= word_count <= HI, "正文 %s=%d（区间%d-%d，不含参考文献）" % (metric, word_count, LO, HI))

# ⑥ 参考文献完整性（有 citation_map.json 时，[n] 是交付序号，先映射回 papers.json 的 ref_no）
cited_order = [int(x) for x in re.findall(r"\[(\d+)\]", body)]
cited_display = set(cited_order)
listed_display = set(int(x) for x in re.findall(r"^\[(\d+)\]", refsec, flags=re.M))
listed = listed_display
bad = []
if cited_display - listed_display:
    bad.append("正文引用缺条目:%s" % sorted(cited_display - listed_display))
if mode_arg in {"B", "C1", "C2"} and not display_to_ref:
    bad.append("B/C 模式缺少 citation_map.json：须先运行 renumber_citations.py 按首次出现顺序重排")
if display_to_ref:
    # C1+C2 共用一份映射时，单篇正文不必从 1 开始；按 map_drafts 顺序拼接后检查全局首次出现序列。
    order_body = body
    if len(map_drafts) > 1:
        parts = []
        for name in map_drafts:
            path = os.path.join(D, name)
            if os.path.exists(path):
                parts.append(open(path, encoding="utf-8").read().split("## 参考文献")[0])
        if parts:
            order_body = "\n".join(parts)
    first_seen = list(dict.fromkeys(int(x) for x in re.findall(r"\[(\d+)\]", order_body)))
    if first_seen != list(range(1, len(first_seen) + 1)):
        bad.append("正文引用未按首次出现顺序连续编号:%s" % first_seen)
    if sorted(listed_display) != list(range(1, len(listed_display) + 1)):
        bad.append("参考文献条目编号不连续:%s" % sorted(listed_display))
    unmapped = sorted((cited_display | listed_display) - set(display_to_ref))
    if unmapped:
        bad.append("交付编号未写入citation_map:%s" % unmapped)
    if len(set(display_to_ref.values())) != len(display_to_ref):
        bad.append("citation_map存在重复ref_no")
listed_pool = {pool_ref(r) for r in listed_display}
cited_pool = {pool_ref(r) for r in cited_display}
if listed_pool - set(papers):
    bad.append("条目无法挂到papers.json:%s" % sorted(listed_pool - set(papers)))
retr = sorted(r for r in listed_pool if papers.get(r, {}).get("is_retracted"))
if retr:
    bad.append("含撤稿:%s" % retr)
log("⑥参考文献完整性", not bad, "正文引用%d编号均有同号条目；条目%d条均挂ref_no；无撤稿；%s%s" % (
    len(cited_display), len(listed_display),
    "交付序号按首次出现连续且已映射ref_no；" if display_to_ref else "",
    "通过" if not bad else "; ".join(bad)))

# ⑦ 无摘要不得被正文引用
bad = ["ref %d 无摘要却被正文引用" % r for r in sorted(cited_pool) if not norm(papers.get(r, {}).get("abstract"))]
noabs_all = sorted(r for r, p in papers.items() if not norm(p.get("abstract")))
log("⑦无摘要不得被正文引用", not bad, "正文引用%d编号均有摘要；池内无摘要%s仅可进参考文献；%s" % (len(cited_pool), noabs_all, "通过" if not bad else "; ".join(bad)))

# ⑧ 模式形态检查（--mode A/A_DIALOGUE/B/C1/C2/D；未传时跳过，向后兼容；2026-11-20 增）
def mode_shape_checks(mode):
    head = body[:800]
    paras = [l for l in body.split("\n") if l.strip()]
    state = {"ok": True, "det": []}

    def need(cond, msg):
        if not cond:
            state["ok"] = False
            state["det"].append("缺 " + msg)
        else:
            state["det"].append("有 " + msg)

    def named_section(title):
        match = re.search(r"^#{1,6}\s*" + re.escape(title) + r"\s*$", body, flags=re.M)
        if not match:
            return ""
        next_heading = re.search(r"^#{1,6}\s+", body[match.end():], flags=re.M)
        end = match.end() + next_heading.start() if next_heading else len(body)
        return body[match.end():end].strip()

    def substantive_citation_section(title):
        text = named_section(title)
        plain = re.sub(r"[#*`\s|【】\[\]]", "", text)
        return len(plain) >= 20 and re.search(r"\[\d+\]", text) is not None

    def has_filled_table(columns, evidence_column=None):
        """检查精确表头与完整数据行；指定证据列时还须含池内引用 [n]。"""
        def cells(line):
            return [c.strip() for c in line.strip().strip("|").split("|")]
        for i, line in enumerate(paras):
            if cells(line) != list(columns):
                continue
            for row in paras[i + 1:]:
                if not row.strip().startswith("|"):
                    break
                values = cells(row)
                if len(values) != len(columns):
                    continue
                if all(re.fullmatch(r":?-{3,}:?", v.replace(" ", "")) for v in values):
                    continue
                if all(v and "【" not in v and "】" not in v for v in values):
                    if evidence_column is not None:
                        evidence = values[columns.index(evidence_column)]
                        if not re.search(r"\[\d+\]", evidence):
                            continue
                    return True
        return False

    if mode in {"C1", "C2"}:
        ledger_refs = {r["ref"] for r in rows}
        need(bool(cited_pool) and bool(rows), "正文引用与证据台账均不得为空")
        need(not (cited_pool - ledger_refs), "正文引用均有台账覆盖（缺 %s）" % sorted(cited_pool - ledger_refs))
        need(bool(listed), "参考文献列表不得为空")

    if mode == "A":
        for w in ("研究价值", "可行性", "创新潜力", "实施难度"):
            need(body.count(w) >= 3, "方向卡维度「%s」出现 ≥3 次" % w)
        for w in ("核心研究问题", "数据可得性"):
            need(body.count(w) >= 3, "方向卡字段「%s」出现 ≥3 次" % w)
        ranks = re.findall(r"第\s*[0-9０-９一二三四五]\s*推荐|储备方向", body)
        need(len(ranks) >= 3, "排序标记（第 N 推荐/储备方向）≥3（实得 %d）" % len(ranks))
        need(re.search(r"第\s*[1１一]\s*推荐", body) is not None, "第 1 推荐标记存在")
        need(any(k in body for k in ("优于", "推荐理由", "排序理由")), "第 1 推荐理由（优于/推荐理由/排序理由任一）")
        need(sum(1 for l in paras if "空白" in l and re.search(r"\[\d+\]", l)) >= 3, "空白证据行（含 [n]）≥3")
        need(("全景树" in body) or ("分堆" in body), "全景树/分堆")
        need(("领域" in head) or ("格局" in head), "首段=领域格局（正文开头含 领域/格局）")
    elif mode == "A_DIALOGUE":
        need(("领域" in head) or ("格局" in head), "首段=领域格局（正文开头含 领域/格局）")
        categories = [
            "理论创新型选题", "方法创新型选题", "研究对象拓展型选题",
            "数据与实证创新型选题", "机制解释型选题", "前沿交叉型选题",
            "应用需求驱动型选题",
        ]
        headings = []
        for i, label in enumerate(categories, 1):
            pat = r"^#{2,4}\s*(?:\d+\s*[.、]?\s*)?" + re.escape(label) + r"\s*$"
            m = re.search(pat, body, flags=re.M)
            need(m is not None, "七类标题「%s」" % label)
            if m:
                headings.append((i, label, m))
        headings.sort(key=lambda x: x[2].start())
        pre_body = body[:headings[0][2].start()] if headings else body
        key_lines = [l for l in pre_body.splitlines()
                     if re.match(r"^\s*[-*]\s+", l) and re.search(r"\[\d+\]", l)]
        need(5 <= len(key_lines) <= 8, "对话要点 5–8 条（实得 %d）" % len(key_lines))
        blanks = [l for l in key_lines if "空白" in l]
        need(len(blanks) >= 3, "研究空白要点 ≥3 条（实得 %d）" % len(blanks))

        slot_pat = re.compile(r"^\s*[-*]?\s*选题\s*([12１２])\s*[｜|]", re.M)
        for pos, (idx, label, heading) in enumerate(headings):
            end = headings[pos + 1][2].start() if pos + 1 < len(headings) else len(body)
            section = body[heading.end():end]
            slots = list(slot_pat.finditer(section))
            slot_nums = [m.group(1).translate(str.maketrans("１２", "12")) for m in slots]
            need(len(slots) == 2 and sorted(slot_nums) == ["1", "2"],
                 "%s含选题 1/2 两个槽位（实得 %d）" % (label, len(slots)))
            for j, slot in enumerate(slots):
                slot_end = slots[j + 1].start() if j + 1 < len(slots) else len(section)
                segment = section[slot.end():slot_end]
                slot_name = "%s·选题 %s" % (label, slot_nums[j])
                if "未推荐" in segment[:100]:
                    reason = re.search(r"原因\s*[：:]\s*([^\n]+)", segment)
                    reason_text = reason.group(1).strip() if reason else ""
                    specific = any(k in reason_text for k in (
                        "证据", "数据", "重复", "范围", "机制", "理论", "检索", "候选", "摘要", "全文"))
                    need(len(reason_text) >= 8 and specific,
                         slot_name + "未推荐原因具体（≥8 字且说明证据/数据/重复/范围等）")
                else:
                    for field in ("核心研究问题", "文献依据", "数据可得性", "研究价值", "可行性", "创新潜力", "实施难度"):
                        need(field in segment, slot_name + "字段「%s」" % field)
                    need(re.search(r"\[\d+\]", segment) is not None, slot_name + "文献依据含 [n]")
                    need(re.search(r"类内第\s*[12１２]\s*推荐", segment[:120]) is not None,
                         slot_name + "类内排序")
        top = re.search(r"综合第\s*[1１一]\s*推荐", body)
        need(top is not None, "综合第 1 推荐")
        if top:
            tail = body[top.start():]
            need(any(k in tail for k in ("推荐理由", "优于", "排序理由")), "综合第 1 推荐理由")
            need("风险" in tail, "综合第 1 推荐主要风险")
        need(len(listed) <= 10, "代表文献 ≤10 篇（实得 %d）" % len(listed))
    elif mode == "B":
        need("若不开展本项目" in body, "刚性需求段（若不开展本项目）")
        need(any(l.strip().startswith("|") and all(k in l for k in ("不足", "科学问题", "研究内容")) for l in paras), "对解表（表头含 不足/科学问题/研究内容）")
        for k in ("研究需求", "已有进展", "现有不足", "科学问题", "切入点", "预期贡献"):
            need(k in body, "六段链链节「%s」" % k)
        need(any(re.match(r"^#{2,4}\s*(?:\d+\s+)?已有研究对本项目技术路线的支撑\s*$", l.strip()) for l in paras), "固定节名（已有研究对本项目技术路线的支撑）")
        need("可复用资产清单" not in body, "无旧节名（可复用资产清单）")
        need(sum(1 for l in paras if l.strip().startswith("-") and "研究内容（" in l) >= 3, "技术路线支撑清单行（研究内容（N））≥3")
        need("本项目" in head, "首段分叉（正文开头含 本项目）")
        bad = []
        for w in ("研究空白", "值得做", "建议方向", "亟待"):
            for l in paras:
                if w in l and not re.search(r"缺项|补齐|如实", l):
                    bad.append("「%s」：%s" % (w, l.strip()[:36]))
        need(not bad, "无 A 口吻禁词（豁免可行性缺项行）" + ("" if not bad else "；" + "；".join(bad[:3])))
        cite_s = [s for s in re.split(r"[。；\n]", body) if re.search(r"\[\d+\]", s)]
        point_s = [s for s in cite_s if any(k in s for k in ("本项目", "本研究", "研究内容", "拟", "将"))]
        ratio = (len(point_s) / len(cite_s)) if cite_s else 0
        need(ratio >= 0.2, "项目指向句占引用句 ≥20%%（实测 %.0f%%）" % (ratio * 100))
    elif mode == "C1":
        cards = [l for l in paras if "段落卡·" in l]
        need(4 <= len(cards) <= 6, "段落卡 4–6 张（实得 %d）" % len(cards))
        need("引言逻辑框架" in body, "引言逻辑框架")
        for z in ("背景重要性", "研究进展", "现有研究不足", "研究思路与方法", "研究贡献"):
            need(z in body, "段落卡职能「%s」" % z)
        c1_gap_cols = ("研究方向", "已有进展", "现有不足", "文献证据", "与本文研究问题的联系")
        need(has_filled_table(c1_gap_cols, evidence_column="文献证据"),
             "Research Gap 分析表（精确表头、完整数据行及池内 [n] 证据）")
        need("完整引言" in body, "完整英文或中文引言")
        need(substantive_citation_section("完整引言"), "完整引言正文非空且含引用")
        introduction = named_section("完整引言")
        intro_paras = [p.strip() for p in re.split(r"\n\s*\n", introduction)
                       if p.strip() and not p.lstrip().startswith(("#", "|"))]
        need(len(intro_paras) >= 5, "完整引言五段结构（实得 %d 段）" % len(intro_paras))
        if len(intro_paras) >= 3:
            third = intro_paras[2]
            third_lower = third.lower()
            need(re.search(r"\[\d+\]", third) is not None and
                 any(k in third_lower for k in ("不足", "空白", "局限", "缺口", "gap", "limitation", "lack", "remain")),
                 "完整引言第三段写现有研究不足并含池内 [n] 证据")
        if len(intro_paras) >= 5:
            need(any(k in intro_paras[3].lower() for k in ("本文", "本研究", "this study", "this paper", "we ")),
                 "完整引言第四段以本文思路与方法回应空白")
            need(any(k in intro_paras[4].lower() for k in ("贡献", "本文", "本研究", "contribution", "this study", "this paper")),
                 "完整引言第五段以研究贡献回应空白")
        need(("写作逻辑和学术质量检查" in body) or ("写作质量检查" in body), "写作逻辑和学术质量检查")
    elif mode == "C2":
        for z in ("研究主题与检索范围", "关键词和检索策略", "代表性文献清单", "文献分类框架", "完整综述文本", "未来研究方向"):
            need(z in body, "独立综述构件「%s」" % z)
        classification = named_section("文献分类框架")
        for z in ("理论基础", "研究对象", "研究问题", "技术方法", "数据与实验", "研究结论", "研究局限"):
            need(z in classification, "七维分类「%s」位于分类框架内" % z)
        need("综合分析" in body, "不同研究方向的综合分析")
        review_text = named_section("完整综述文本")
        need(substantive_citation_section("完整综述文本"), "完整综述正文非空且含引用")
        need(any(k in review_text for k in ("研究空白", "现有不足", "现有局限", "关键问题")) and
             re.search(r"\[\d+\]", review_text) is not None,
             "完整综述纳入研究空白及池内 [n] 证据")
        need("技术路线" in body and "比较" in body, "主要技术路线横向比较")
        need(("现有研究不足" in body) or ("现有研究局限" in body), "现有研究不足/局限")
        comparison_cols = ("文献", "研究问题", "数据", "核心方法", "主要发现", "局限性")
        need(has_filled_table(comparison_cols), "六列文献比较表（精确表头且至少一行完整数据）")
        gap_cols = ("研究方向", "已有进展", "现有不足", "文献证据", "可深入研究的问题")
        need(has_filled_table(gap_cols, evidence_column="文献证据"),
             "五列研究空白分析表（精确表头、完整数据行及池内 [n] 证据）")
        for line in body.splitlines():
            upper = line.upper()
            if "PRISMA" not in upper and "系统综述" not in line:
                continue
            if any(k in line for k in ("未", "不得", "不能", "不称", "不是")):
                continue
            if "PRISMA" in upper and re.search(r"遵循|采用|按照|依据|筛选", line):
                need(re.search(r"prisma\s*[:=]\s*true", search_log, flags=re.I) is not None,
                     "PRISMA 声明须有 search_log 的 prisma: true 执行记录")
            if "系统综述" in line and re.search(r"本综述|本文为|属于|称为|采用", line):
                need(re.search(r"systematic_review\s*[:=]\s*true", search_log, flags=re.I) is not None,
                     "系统综述声明须有 search_log 的 systematic_review: true 执行记录")
        old_discussion = re.search(r"^#{1,4}\s*.*(?:讨论|discussion).*$", body, flags=re.M | re.I)
        old_result_gate = any(k in body for k in ("必须提供本文结果", "先亮本文主要发现", "本文结果后才能写综述"))
        need(not old_discussion and not old_result_gate, "C2 独立文献综述而非讨论")
        c1_path = os.path.join(D, "C1_引言.md")
        if os.path.exists(c1_path):
            linkage = named_section("衔接与重复检查")
            need(bool(linkage), "C1+C2 衔接与重复检查")
            need("一致" in linkage, "C1+C2 空白点一致性检查")
            need("重复" in linkage, "C1+C2 重复检查与处理")
            need("交叉指向" in linkage or
                 ("指向" in linkage and "引言" in linkage and "综述" in linkage),
                 "C1+C2 空白点交叉指向")
            c1_text = open(c1_path, encoding="utf-8").read().split("## 参考文献")[0]

            def long_paragraphs(text):
                found = set()
                for para in re.split(r"\n\s*\n", text):
                    normalized = re.sub(r"\s+", "", para)
                    if len(normalized) >= 50 and not para.lstrip().startswith(("#", "|")):
                        found.add(normalized)
                return found

            duplicates = long_paragraphs(c1_text) & long_paragraphs(body)
            need(not duplicates, "C1+C2 无重复段落（实得 %d 段）" % len(duplicates))
    elif mode == "D":
        marks = sum(1 for l in paras if ("阅读深度" in l) or ("仅摘要" in l) or ("已读全文" in l))
        need(3 <= marks <= 5, "精读页 3–5 张（阅读深度/仅摘要/已读全文标注行实得 %d）" % marks)
        need("讨论问题" in body, "组会讨论问题清单")
        need(any(k in body for k in ("检索式", "检索策略", "检索词")), "检索概况段（含 检索式/检索策略/检索词）")
        need(any(k in body for k in ("OpenAlex", "arXiv", "数据库")), "检索概况含数据库名")
        need(any(l.strip().startswith("|") and ("方法" in l) and ("局限" in l) for l in paras), "方法对比表（表头行含 方法+局限）")
        for k in ("研究进展", "研究不足", "趋势"):
            need(k in body, "九段构件「%s」" % k)
        ranks = re.findall(r"第\s*[0-9０-９一二三四五]\s*推荐|候选选题|优先推荐", body)
        need(len(ranks) >= 3, "选题排序标记（第 N 推荐/候选选题/优先推荐）≥3（实得 %d）" % len(ranks))
        need(any(k in head for k in ("本次调研", "本汇报", "本报告")), "首段分叉（正文开头含 本次调研/本汇报/本报告）")
    else:
        state["det"].append("模式 %s 无形态检查（基线模式/E）" % mode)
    return state["ok"], state["det"]


if mode_arg:
    ok8, det8 = mode_shape_checks(mode_arg)
    log("⑧模式形态(--mode %s)" % mode_arg, ok8, "；".join(det8))

# 汇总
lines = ["交付前脚本复核报告 verify_report.txt（预置脚本 scripts/verify_delivery.py）",
         "交付正文: %s ｜ 论文池: papers.json (%d篇) ｜ 台账: %d条 ｜ 字数区间: %d-%d" % (draft_name, len(papers), len(rows), LO, HI),
         "=" * 60]
for status, check, detail in report:
    lines.append("[%s] %s：%s" % (status, check, detail))
lines.append("=" * 60)
lines.append("④ 数字→台账原句 绑定明细:")
lines.extend("  " + m for m in bound_map)
lines.append("③ 全文通道明细（双轨证据链，2026-11-22 增）:")
for r in rows:
    if r.get("full_loc") and r.get("full_quote"):
        lines.append("  ref%d → %s｜%s" % (r["ref"], r["full_loc"], r["full_quote"][:90]))
if full_missing:
    lines.append("③ 全文缺失回落（不判失败）:")
    lines.extend("  " + m for m in full_missing)
if unbound:
    lines.append("④ 待人工确认（未绑定台账原句，须交付说明披露并人工判定是否结构性数字）:")
    lines.extend("  " + m for m in unbound)
lines.append("=" * 60)
concl = ("全部 %d 项无失败" % len(report)) if not fails else "存在失败项 %s，须改正后重跑" % list(fails)
if warns:
    concl += "；另有 %d 个数字待人工确认（见上）" % len(warns)
lines.append("总结论: " + concl)
out = "\n".join(lines) + "\n"
open(os.path.join(D, "verify_report.txt"), "w", encoding="utf-8").write(out)
print(out)
sys.exit(0 if not fails else 1)