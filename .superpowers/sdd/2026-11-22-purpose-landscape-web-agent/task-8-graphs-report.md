# Task 8：七类图谱数据模块报告

## 完成范围

本次实现七类前端可直接消费的图数据：引用网络、主题分布、比较分析、总体趋势、因素→结局、方法思维导图、语义关系图谱。保留 `dashboard_data.json` 原有主要字段，并补充统一的 `ready` / `empty` 状态、空状态说明、双范围切换元数据和逐条证据。

实现只使用输入的真实论文池、OpenAlex 聚合统计和分析结果，不调用模型、不发起检索，也不根据标题相似度、引用关系或论文池计数补造关系或聚合数据。

## 文件

### 新增实现与测试

- `backend/app/graphs.py`：七类图数据组装、二次证据审计、重复数据去重、可选 JSON 与证据台账写入。
- `backend/tests/test_graphs.py`：14 项专项测试。

### 新增专用真实 fixture

目录：`backend/tests/fixtures/graphs/`

- `papers.json`、`papers_all.json`：真实双范围论文池。
- `stats_year.json`：真实年度聚合。
- `stats_topics_all.json`、`stats_topics_limited.json`：真实双范围主题聚合。
- `stats_series_1.json` 至 `stats_series_4.json`：真实前四主题年度序列。
- `analysis.json`：由真实主题归类、方法归类、因素投票和语义关系结果整理；方法审计引文取自对应论文的真实摘要。

未修改 `models.py`、`main.py`、`task_flow.py`、`queueing.py`、`analysis.py`、`search.py` 或前端源码；未部署、未初始化 Git、未调用付费模型。

## 接口

```python
GraphService().build(
    pools,
    stats,
    analysis,
    topic='',
    condition='',
    sources='',
    translations=None,
    generated_at=None,
    output_dir=None,
    task_dir=None,
)
```

### 输入

- `pools`：`{'all': papers_all, 'limited': papers}`；也接受 `unlimited` 作为 `all` 的别名。每个范围包含 `papers` 列表及可选 `from_year`。
- `stats`：`year`、`topics['all'|'limited']`、`series`。主题序列可按主题 key/name 映射，或按前四主题顺序提供；同时兼容编排层传入的 `year_all`、`topics_all`、`topics_limited` JSON 文件路径。
- `analysis`：各范围或共享的 `classify`／`clusters`、`methods`、`factor_votes`／`votes`、`relations`，直接兼容 `AnalysisService` 的字典或 dataclass 结果。
- `translations`：可选主题中文名映射；未提供时保留真实英文名，不生成翻译。
- `output_dir`：可选。提供时写入 `dashboard_data.json`、`relations.json`、`graph_evidence.md`、`relations_evidence.md`。
- `task_dir`：`output_dir` 的编排兼容别名；二者同时提供时必须指向同一目录。写入四个文件时返回 `artifact_count: 4`，未写入时为 0。

### 输出结构

顶层保留：

- `topic`、`generated_at`、`condition`、`sources`
- `trend_all`、`compare`
- `scopes.all`，以及输入存在限定范围时的 `scopes.limited`

新增：

- `chart_order`：固定七类图顺序。
- `scope_switch.available`：实际可切换范围。
- `scope_switch.scoped_charts`：`network`、`topics`、`knowledge`、`methods`、`relations`。
- `scope_switch.fixed_all_charts`：`compare`、`trend`。
- `trend_status` / `trend_message`、`compare_status` / `compare_message`。

每个范围保留 `topics`、`network`、`knowledge`、`methods`、`relations`，并增加：

- `topics_status` / `topics_message`
- 各池内图的 `status` / `message`
- 引用网络的 `edge_status` / `edge_message`，明确区分“有孤立论文节点”和“有真实互引边”
- 因素边的 `evidence`，每项含 `ref`、`ref_no`、摘要原句、极性和效应量
- 方法叶子的 `evidence`，每项含 `ref`、`ref_no` 和摘要原句
- 语义边的 `evidence`，分别保留 evidence/basis 两侧的 `ref_no` 与摘要原句

## 数据完整性与空状态

- 引用边仅由论文真实 `referenced_works` 与池内 OpenAlex/DOI/URL 标识匹配产生，方向为引用者→被引者；不使用标题或语义相似度补边。
- 分布、比较和趋势只使用全量聚合；统计缺失时返回空数组与明确空状态，不以论文池计数替代。
- 因素投票必须具有池内有效 `ref_no`、非空因素/结局、合法极性和对应摘要的逐字原句；支撑篇数按不同论文去重，相反极性边可并存并标记争议。
- 方法证据必须来自对应论文摘要；树严格为根→数据获取方法族→具体技术。方法族或技术命中主题堆名、二者同名、无摘要或引文错误时整条舍弃，不自动归入“其他”。
- 语义边要求两个不同池内端点、合法类型与置信度，且 evidence/basis 引用编号正好是两端点；两侧原句分别通过对应摘要审计后才保留。
- 无摘要论文可保留为引用网络节点，但不能提供因素、方法或语义关系证据。
- 重复论文、重复投票、重复方法和重复语义边不会增加节点、支撑篇数或边数。

## 测试输出

同步后专项测试：

```text
python -m pytest backend/tests/test_graphs.py -q
14 passed in 0.58s
```

此前相关回归：

```text
python -m pytest backend/tests/test_graphs.py backend/tests/test_analysis.py backend/tests/test_search.py -v
44 passed, 1 skipped in 5.32s
```

同步并兼容编排接口后的完整后端回归：

```text
python -m pytest backend/tests -q
186 passed, 1 skipped, 1 failed in 8.23s
```

唯一失败为 `test_missing_graph_builder_fails_instead_of_claiming_dashboard_ready`。该旧测试仍假设 GraphService 不存在并要求抛出 RuntimeError；当前真实 GraphService 已存在且 `task_dir` 编排调用成功，因此断言失效。未修改该编排测试，也未通过故意报错制造全绿结果。

跳过项为既有 `test_live_openalex_smoke_returns_five_real_records` 联网冒烟测试；本次未发起实时检索。

专项覆盖：真实互引、双范围与七类图结构、无摘要、空数据、重复论文与重复分析记录、错误因素证据、错误语义关系证据、方法层级与主题堆名拦截、统计缺失禁止池计数替代、JSON 与证据台账序列化、`task_dir` 编排别名及统计 JSON 路径。

## 未完成边界

- 按本任务文件限制，未新增 `artifacts.py`，未生成 `desktop.html`、`mobile.html`、`index.html`、SVG 或 PNG，也未做浏览器点击与栅格化验收；本次交付是七类图数据及可选 JSON/Markdown 证据台账。
- 未将图谱组装接入 `main.py`、队列或任务状态机，需由后续任务在允许修改这些文件时接线。
- 未进行高被引补充检索；网络只展示输入论文池内的真实节点与互引。
- 未调用模型生成主题中文翻译；调用方需传入真实翻译映射，否则 `name_zh` 回退为原英文名。
- 图数据保留原渲染器所需字段，但新增状态与证据字段仍需前端/原仪表盘构建器在后续任务中实际消费和验收。
