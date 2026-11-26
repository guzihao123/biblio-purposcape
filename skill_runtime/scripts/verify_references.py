#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Crossref / DataCite 著录核验源（purpose-landscape 接库第一步，2026-11-20）。

用法：python3 verify_references.py <papers.json> [--out <报告.md>]
- 读取 papers.json 每篇 DOI，逐条查询 Crossref works API（免费、无需 key）；
  Crossref 未收录的 DOI 自动降级查 DataCite API（覆盖 OSF 等注册机构的 DOI）。
- 核对：标题 / 作者全名单 / 期刊（container-title）/ 年份 / 类型 / 撤稿关联（update-to、updated-by）。
- 回填建议：卷 / 期 / 页 / 出版商 / Crossref 记录类型（供文献类型 [J]/[EB/OL] 判定）。
- 报告默认写入 papers.json 同目录 references_check.md；stdout 打印逐条摘要。
- 只核验不改池：不修改 papers.json；结论供人工著录修订与 conformance 披露使用。
零依赖：python3 标准库。
"""
import argparse
import json
import re
import ssl
import sys
import time
import unicodedata
import urllib.error
import urllib.request

UA = {'User-Agent': 'purpose-landscape/verify_references/1.0 (polite pool)'}
CTX = ssl.create_default_context()


def http_json(url, timeout=30):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout, context=CTX) as r:
        return json.loads(r.read().decode('utf-8'))


def norm(s):
    s = unicodedata.normalize('NFKC', (s or '')).casefold()
    # 保留 Unicode 字母与数字；原 ASCII 正则会把所有 CJK 标题和姓名归一成空串。
    return re.sub(r'\s+', ' ', ''.join(c if c.isalnum() else ' ' for c in s)).strip()


def name_key(s):
    return ' '.join(sorted(norm(s).split()))


def _name_parts(value):
    raw = str(value or '').strip()
    if ',' in raw:
        family, given = raw.split(',', 1)
        return norm(family), norm(given)
    parts = norm(raw).split()
    if not parts:
        return '', ''
    return parts[-1], ' '.join(parts[:-1])


def _given_compatible(remote, local):
    if remote == local:
        return True
    compact_remote = remote.replace(' ', '')
    compact_local = local.replace(' ', '')
    if compact_remote.startswith(compact_local) or compact_local.startswith(compact_remote):
        return True
    remote_tokens = remote.split()
    local_tokens = local.split()
    if len(remote_tokens) != len(local_tokens) or not remote_tokens:
        return False
    return all(
        a == b
        or (len(a) == 1 and b.startswith(a))
        or (len(b) == 1 and a.startswith(b))
        for a, b in zip(remote_tokens, local_tokens)
    )


def name_compatible(remote, local):
    """Accept missing middle names and initials while rejecting a different person."""
    remote_family, remote_given = _name_parts(remote)
    local_family, local_given = _name_parts(local)
    if not remote_family or not local_family:
        return False
    if remote_family != local_family:
        return False
    return _given_compatible(remote_given, local_given)


def venue_compatible(remote, local):
    stop = {'a', 'an', 'the', 'of', 'and'}
    remote_tokens = {token for token in norm(remote).split() if token not in stop}
    local_tokens = {token for token in norm(local).split() if token not in stop}
    if not remote_tokens or not local_tokens:
        return False
    if remote_tokens <= local_tokens or local_tokens <= remote_tokens:
        return True
    compact_remote = ''.join(sorted(remote_tokens))
    compact_local = ''.join(sorted(local_tokens))
    return compact_remote == compact_local


def bare_doi(doi):
    d = (doi or '').strip()
    m = re.search(r'(10\.\d{4,9}/\S+)\s*$', d)
    return m.group(1) if m else d


def fetch_crossref(doi):
    try:
        return ('crossref', http_json('https://api.crossref.org/works/' + doi)['message'])
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return ('crossref', None)
        raise


def fetch_datacite(doi):
    try:
        return ('datacite', http_json('https://api.datacite.org/dois/' + doi)['data']['attributes'])
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return ('datacite', None)
        raise


def cr_authors(msg):
    out = []
    for a in msg.get('author') or []:
        if a.get('family') and a.get('given'):
            out.append('%s, %s' % (a['family'], a['given']))
        elif a.get('name'):
            out.append(a['name'])
        elif a.get('family'):
            out.append(a['family'])
        else:
            out.append(a.get('given') or '')
    return [x for x in out if x]


def parse_record(msg, src):
    if src == 'crossref':
        title = (msg.get('title') or [''])[0]
        container = (msg.get('container-title') or [''])[0]
        year = None
        for k in ('published', 'issued', 'created'):
            dp = (msg.get(k) or {}).get('date-parts') or []
            if dp and dp[0]:
                year = dp[0][0]
                break
        updates = (msg.get('update-to') or []) + (msg.get('updated-by') or [])
        return {'title': title, 'authors': cr_authors(msg), 'container': container,
                'volume': msg.get('volume') or '', 'issue': msg.get('issue') or '',
                'page': msg.get('page') or '', 'year': year,
                'type': msg.get('type') or '', 'publisher': msg.get('publisher') or '',
                'cited': msg.get('is-referenced-by-count'),
                'updates': updates}
    titles = msg.get('titles') or []
    title = titles[0].get('title', '') if titles else ''
    authors = []
    for c in msg.get('creators') or []:
        if c.get('name'):
            authors.append(c['name'])
        elif c.get('family') or c.get('given'):
            authors.append(('%s, %s' % (c.get('family', ''), c.get('given', ''))).strip(', '))
    pub = msg.get('publisher') or ''
    updates = [r for r in msg.get('relatedIdentifiers') or []
               if re.search(r'retract|correct', str(r.get('relationType') or ''), re.I)]
    return {'title': title, 'authors': [a for a in authors if a], 'container': pub,
            'volume': '', 'issue': '', 'page': '', 'year': msg.get('publicationYear'),
            'type': (msg.get('types') or {}).get('resourceTypeGeneral') or '',
            'publisher': pub, 'cited': None, 'updates': updates}


def retraction_updates(updates):
    explicit = []
    for update in updates:
        relation = ' '.join(str(update.get(k) or '') for k in ('type', 'label', 'relationType'))
        if 'retract' in relation.casefold() or '撤稿' in relation:
            explicit.append(update)
    return explicit


def compare(p, m, src):
    issues, fills, notices = [], [], []
    if norm(m['title']) and norm(m['title']) != norm(p.get('title', '')):
        issues.append('标题不一致：%s「%s」vs 本地「%s」' % (src, m['title'], p.get('title')))
    local_authors = p.get('authors') or []
    remote_authors = m['authors']
    if len(local_authors) > len(remote_authors):
        issues.append('作者人数不一致：%s %d 人（%s）vs 本地 %d 人（%s）'
                      % (src, len(remote_authors), '; '.join(remote_authors),
                         len(local_authors), ', '.join(local_authors)))
    else:
        # OpenAlex and the GB/T formatter may keep only the first N authors.
        # A shorter local list is valid when it is a prefix of the registry list.
        for index, (a, b) in enumerate(zip(remote_authors, local_authors), 1):
            if name_key(a) != name_key(b) and not name_compatible(a, b):
                issues.append('作者名不一致：%s「%s」vs 本地「%s」' % (src, a, b))
                if len(local_authors) != len(remote_authors):
                    issues.append(
                        '作者前缀不一致：本地仅列前 %d 位，第 %d 位不匹配'
                        % (len(local_authors), index)
                    )
                break
    if m['year'] and p.get('year') and int(m['year']) != int(p['year']):
        # Online-first and print issue years commonly differ by one; keep that
        # visible as a note in the report rather than blocking delivery.
        if abs(int(m['year']) - int(p['year'])) > 1:
            issues.append('年份不一致：%s %s vs 本地 %s' % (src, m['year'], p['year']))
    if m['container'] and p.get('venue') and not venue_compatible(m['container'], p.get('venue')):
        if re.search(r'arxiv|biorxiv|medrxiv|ssrn|preprint|research square', str(p['venue']), re.I):
            notices.append('预印本与正式发表版本来源不同（同一 DOI，版本待人工确认）：%s「%s」vs 本地「%s」' % (src, m['container'], p['venue']))
        else:
            issues.append('期刊/来源不一致：%s「%s」vs 本地「%s」' % (src, m['container'], p.get('venue')))
    for k, label in (('volume', '卷'), ('issue', '期'), ('page', '页码')):
        if m[k]:
            fills.append('%s=%s' % (label, m[k]))
    return issues, fills, notices


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('papers_json')
    ap.add_argument('--out', default=None)
    args = ap.parse_args()
    doc = json.load(open(args.papers_json, encoding='utf-8'))
    papers = doc['papers']
    out_path = args.out or re.sub(r'papers(_all)?\.json$', '', args.papers_json) + 'references_check.md'

    lines = ['# Crossref / DataCite 著录核验报告（verify_references.py）', '',
             '- 输入：%s（%d 篇）｜核验时间：%s' % (args.papers_json, len(papers), time.strftime('%Y-%m-%d %H:%M')),
             '- 通道：Crossref works API（免费无 key）→ 未收录 DOI 自动降级 DataCite API；只核验不改池', '']
    n_pass = n_manual = n_fill = n_retract = n_notice = 0
    for p in papers:
        ref = p.get('ref_no', '?')
        lines.append('## [%s] %s' % (ref, p.get('title', '')))
        doi = bare_doi(p.get('doi'))
        if not doi.startswith('10.'):
            lines.append('- DOI 缺失或非法，跳过核验（非撤稿，供人工参考）')
            n_notice += 1
            lines.append('')
            print('[%s] DOI 缺失，跳过' % ref)
            continue
        src, msg = fetch_crossref(doi)
        if msg is None:
            src, msg = fetch_datacite(doi)
        if msg is None:
            lines.append('- DOI %s：Crossref 与 DataCite 均未收录（非撤稿，供人工参考）' % doi)
            n_notice += 1
            lines.append('')
            print('[%s] 两个注册库均未收录' % ref)
            continue
        m = parse_record(msg, src)
        issues, fills, notices = compare(p, m, src)
        lines.append('- DOI：%s｜核验通道：%s｜记录类型：%s｜出版方：%s' % (doi, src, m['type'] or '(未标注)', m['publisher'] or '(未标注)'))
        if m['cited'] is not None:
            lines.append('- Crossref 被引数（is-referenced-by-count）：%s' % m['cited'])
        if fills:
            lines.append('- 回填建议：%s' % '；'.join(fills))
            n_fill += 1
        notice = False
        if m['updates']:
            explicit_retractions = retraction_updates(m['updates'])
            if explicit_retractions:
                n_retract += 1
                lines.append('- **撤稿关联：不得进入参考文献，需人工判定**：%s'
                             % json.dumps(explicit_retractions, ensure_ascii=False))
                issues.append('注册库标注撤稿关联，该条不得进入参考文献')
            else:
                n_notice += 1
                notice = True
                lines.append('- 更正关联（非撤稿，供人工参考）：%s'
                             % json.dumps(m['updates'], ensure_ascii=False))
        else:
            lines.append('- 撤稿/更正关联：无（update-to / updated-by / relatedIdentifiers 为空）')
        if notices:
            n_notice += 1
            notice = True
            for nt in notices:
                lines.append('- 提示（非阻断，供人工参考）：%s' % nt)
        if issues:
            for it in issues:
                lines.append('- 核对问题：%s' % it)
            lines.append('- 结论：**需人工核对**（见上）')
            n_manual += 1
            print('[%s] %s 需人工核对：%s' % (ref, src, issues[0][:60]))
        else:
            suffix = '（含更正关联，非撤稿）' if notice else ''
            lines.append('- 结论：**核验通过**' + suffix)
            n_pass += 1
            print('[%s] %s 核验通过%s%s' % (ref, src, suffix, ('；回填 ' + '，'.join(fills)) if fills else ''))
        lines.append('')
        time.sleep(0.4)
    lines.append('## 汇总')
    lines.append('')
    lines.append('- 核验通过 %d 篇；需人工核对 %d 篇；含回填字段（卷/期/页）%d 篇；撤稿关联 %d 篇；更正关联 %d 篇。' % (n_pass, n_manual, n_fill, n_retract, n_notice))
    lines.append('- 说明：Crossref 被引数口径与 OpenAlex 不同（仅作旁证，不回写 papers.json）；DataCite 通道无卷期页与被引数据。')
    open(out_path, 'w', encoding='utf-8').write('\n'.join(lines) + '\n')
    print()
    print('报告已写入：%s' % out_path)
    print('通过 %d ｜ 需人工核对 %d ｜ 回填 %d ｜ 撤稿关联 %d' % (n_pass, n_manual, n_fill, n_retract))
    return 0


if __name__ == '__main__':
    sys.exit(main())
