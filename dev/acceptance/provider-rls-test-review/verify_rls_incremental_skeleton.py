"""RLS 增量可重入验证脚本骨架 · 独立审计起草（未实现，未执行）

状态：SKELETON ONLY。本文件不包含任何可运行的测试逻辑；每个用例体均显式
raise NotImplementedError。主线后续实现各用例并在真实 Supabase 测试项目实际
执行后，方可将对应条目标记为通过——本骨架自身不产生任何 passed/成功证据，
也不改变 test_matrix_relabel 中 T-01~T-10 的现有状态（T-01~T-06 partial、
T-07~T-10 not_covered）。

设计约束（对实现者的硬性要求）：
1. 每次运行生成唯一 RUN_ID（UTC 时间戳 + 随机后缀）；所有 session/task/
   skill/answer/artifact/quota 主键均以 f'{RUN_ID}-...' 派生。禁止固定主键、
   清库、删数据、重建角色、重新迁移——上一轮 verify_rls.py 的固定字面量 ID
   使其不可重入，本骨架必须根治（见 mainline-recheck.json OBS-01）。
2. 输出写到 Path(__file__).resolve().parent / f'rls-verification-{RUN_ID}.json'，
   不依赖 cwd，不覆盖任何既有报告（含旧 rls-verification.json）。
3. 连接串与三个角色密码只从环境变量读取：
   DATABASE_URL / APP_USER_PASSWORD / APP_ADMIN_PASSWORD / AUDIT_READER_PASSWORD。
   保留 Supabase pooler 用户名租户后缀：连接 user 为 app_user 时改为
   f'app_user.{tenant_suffix}'（tenant_suffix 取自 DATABASE_URL 原 user
   中 '.' 之后的部分），与 verify_rls.py 的 parameters() 语义一致。
4. 日志与异常不得输出连接串、密码或完整 SQL 参数；连接参数与语句参数
   一律经 redact() 过滤。
5. 每个用例写明：前置数据、执行步骤、逐条断言、解除的 missing 项。
6. 本骨架禁止打印 passed、禁止生成'全部通过'类证据；main() 默认不连接
   数据库（连接动作只在各用例实现体内部发生）。

用例与 mainline-recheck.json test_matrix_relabel 的对应关系：
  T-01 partial  -> INC-01/INC-02 补齐 artifacts/quota 同会话路径
  T-02 partial  -> INC-03/INC-04 补齐横断覆盖与错误等价性
  T-03 partial  -> INC-08（含 T-08 发布并发）
  T-04 partial  -> INC-09
  T-05 partial  -> INC-05（审计写拒绝）
  T-06 partial  -> INC-06（已撤销/已过期会话的业务表读写拒绝）
  T-07 not_covered -> INC-07（会话创建双路径）
  T-09 not_covered -> INC-10（同连接 GUC 复用串号）
  T-10 not_covered -> INC-11（revision CAS）、INC-12（答案插入回滚）、
                      INC-13（幂等单扣费）
"""

from __future__ import annotations

import json
import os
import secrets
import string
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
REQUIRED_ENV = (
    'DATABASE_URL',
    'APP_USER_PASSWORD',
    'APP_ADMIN_PASSWORD',
    'AUDIT_READER_PASSWORD',
)
SENSITIVE_KEYS = ('password', 'dbname', 'host', 'port', 'user', 'sslpassword')


def make_run_id() -> str:
    """UTC 时间戳 + 随机后缀，保证跨次运行全局唯一且不依赖本地时区。"""
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    suffix = ''.join(secrets.choice(string.ascii_lowercase + string.digits) for _ in range(8))
    return f'{stamp}-{suffix}'


def output_path(run_id: str) -> Path:
    """输出到脚本所在目录，文件名含 RUN_ID，永不覆盖旧报告。"""
    return HERE / f'rls-verification-{run_id}.json'


def redact(value: object) -> object:
    """过滤日志/异常载体：连接串键名与长随机串（密码形态）一律打码。"""
    if isinstance(value, dict):
        return {
            (k if not any(s in k.lower() for s in SENSITIVE_KEYS) else f'<redacted:{k}>')
            : redact(v)
            for k, v in value.items()
        }
    if isinstance(value, str):
        if len(value) >= 20 and all(c.isalnum() or c in '-_' for c in value):
            return f'<redacted:{len(value)}chars>'
        return value
    if isinstance(value, (list, tuple)):
        return [redact(item) for item in value]
    return value


def require_env() -> None:
    missing = [name for name in REQUIRED_ENV if not os.environ.get(name)]
    if missing:
        raise RuntimeError('missing env: ' + ', '.join(missing))


def role_parameters(role: str) -> dict:
    """实现约束 3：连接串与密码仅来自环境变量，保留 pooler 租户后缀。

    实现要点（供主线实现时遵循）：
    - base = psycopg.conninfo.conninfo_to_dict(os.environ['DATABASE_URL'])
    - original_user = base.get('user', '')
    - 若 '.' in original_user：tenant_suffix = original_user.split('.', 1)[1]
      user = f'{role}.{tenant_suffix}'（Supabase pooler 要求）
      否则 user = role
    - password = os.environ[f'{role.upper()}_PASSWORD']
    - connect_timeout = 10；返回值不得打印、不得写入报告
    """
    raise NotImplementedError('skeleton: connection parameter wiring not implemented')


def bind_session(connection, session_id: str) -> None:
    """实现约束的事务级 GUC 绑定（INC-10 依赖此函数的事务级语义）。

    必须为：SELECT set_config('app.session_id', %s, true)——第三参数 true
    （事务级）。禁止任何字符串拼接；禁止持久 SET；禁止 set_config 第三
    参数为 false。调用点必须位于目标业务语句的同一事务内、且先于业务语句。
    """
    raise NotImplementedError('skeleton: GUC bind helper not implemented')


def expect_denied(fn, label: str) -> None:
    """断言 fn 必以 RLS/权限错误失败（psycopg.errors.InsufficientPrivilege）。

    通过后必须回滚当前事务残留状态，保证同连接后续用例不受污染。
    """
    raise NotImplementedError('skeleton: denial assertion helper not implemented')


# ---------------------------------------------------------------------------
# 用例实现体（全部 not_implemented）
# ---------------------------------------------------------------------------

def inc_01_same_session_artifacts(run_id: str) -> dict:
    """INC-01 · 同会话 artifacts 读写（解除 T-01 missing: artifacts 未验证）。

    前置数据：{run_id}-s01 会话（未撤销、未过期）+ {run_id}-skill 已发布
    + {run_id}-task01（skill_version_id 指向该 skill）。
    执行步骤：
      1. 以 app_user 连接，事务内 bind_session({run_id}-s01)；
      2. INSERT sites_task_artifacts (task_id={run_id}-task01, name='{run_id}-a.docx',
         object_path='artifacts/{run_id}-task01/{run_id}-a.docx', ...)；
      3. SELECT 回读同一行；
      4. 同事务再 UPDATE size_bytes 后回读。
    断言：2/3/4 全部成功且字段一致；断言记入报告 pass 证据。
    解除 missing：T-01 的 artifacts 缺口。
    """
    raise NotImplementedError('INC-01 not_implemented')


def inc_02_same_session_quota(run_id: str) -> dict:
    """INC-02 · 同会话 quota 扣减与读回（解除 T-01 missing: quota 未验证）。

    前置数据：{run_id}-s02 会话 + {run_id}-skill + {run_id}-task02。
    执行步骤：
      1. bind_session({run_id}-s02)；
      2. 执行 consumeQuota 等价语句（INSERT ... ON CONFLICT DO UPDATE，
         used +1，limit=5）；
      3. SELECT sites_task_quota_windows WHERE session_id={run_id}-s02。
    断言：扣减成功、used=1、读回一致。
    解除 missing：T-01 的 quota 缺口。
    """
    raise NotImplementedError('INC-02 not_implemented')


def inc_03_cross_session_artifacts_quota(run_id: str) -> dict:
    """INC-03 · 跨会话 artifacts/quota 横断拒绝（解除 T-02 missing）。

    前置数据：INC-01/02 产生的 {run_id}-s01/{run_id}-s02 数据保留。
    执行步骤：以 GUC={run_id}-s02 对 s01 的 artifacts 行执行
      SELECT / UPDATE / DELETE（各一次，每次独立尝试并回滚）；
      对 quota 窗口执行 SELECT / UPDATE / DELETE 同法。
    断言：artifacts 与 quota 各 6 次尝试全部 0 行或 42501；
      并断言两类失败形态（0 行 vs 42501）均不向调用方泄漏行存在性差异
      之外的语义（记录观察，不作硬断言——见 INC-04）。
    解除 missing：T-02 的 artifacts/quota、UPDATE/DELETE 缺口。
    """
    raise NotImplementedError('INC-03 not_implemented')


def inc_04_cross_session_command_matrix(run_id: str) -> dict:
    """INC-04 · 四表 × 四命令错误等价性（解除 T-02 missing: 错误等价性）。

    前置数据：{run_id}-s03 会话（无数据）。
    执行步骤：以 GUC={run_id}-s03 对 {run_id}-task01 依次尝试
      SELECT / INSERT(session_id 指向他人) / UPDATE / DELETE；
      answers 与 sessions 表同法（sessions 表 INSERT 例外——属 INC-07 范围）。
    断言：全部拒绝；对每次拒绝记录错误码（42501 vs 0 行）入报告 observability
      字段；不输出 SQL 参数原文。
    解除 missing：T-02 的命令覆盖与错误等价性记录。
    """
    raise NotImplementedError('INC-04 not_implemented')


def inc_05_audit_write_denied(run_id: str) -> dict:
    """INC-05 · 审计角色写拒绝（解除 T-05 missing: 审计写拒绝未验证）。

    前置数据：INC-01/02 已写入的数据保留。
    执行步骤：以 audit_reader 连接（BYPASSRLS 仅绕过行可见性，不绕过
      GRANT），对六张表依次尝试 INSERT/UPDATE/DELETE 各一次（会话表用
      全新 {run_id}-s99 主键，避免与既有行纠缠）。
    断言：18 次尝试全部 42501；随后对任一表执行 SELECT 仍成功（证明
      连接与角色本身有效，拒绝来自 GRANT 层而非连接故障）。
    解除 missing：T-05 的写拒绝缺口。
    """
    raise NotImplementedError('INC-05 not_implemented')


def inc_06_revoked_expired_session_blocked(run_id: str) -> dict:
    """INC-06 · 已撤销/已过期会话的业务表读写拒绝（解除 T-06 核心缺口）。

    前置数据：{run_id}-s04 会话 + 其任务/答案各一。
      另备 {run_id}-s05（expires_at 为过去时间——注意：按现有 INSERT
      策略该会话无法创建，故改用'先创建未过期、再经后端/admin 路径置
      过期'；若 admin 路径不可用，则改为直接 UPDATE expires_at，
      实现注释中须记录所用途径）。
    执行步骤：分别对 revoked 的 s04 与 expired 的 s05，以 GUC 绑定后
      尝试 INSERT task / INSERT answer / INSERT artifact / 扣 quota /
      SELECT task / SELECT answer。
    断言：写全部 42501；读全部 0 行（当前主线 SELECT 策略下读仍放行——
      此断言按 AUD-05 口径落地后的期望填写；若主线尚未落地 AUD-05，
      实现者须在此记录 actual 与期望的差异并标 partial，不得硬改断言）。
    解除 missing：T-06 的'撤销/过期后再写业务表'缺口。
    """
    raise NotImplementedError('INC-06 not_implemented')


def inc_07_session_create_dual_path(run_id: str) -> dict:
    """INC-07 · 会话创建双路径（解除 T-07 not_covered）。

    前置数据：无（全新运行前缀）。
    执行步骤：
      1. GUC 未绑定（新连接、无 set_config）→ INSERT {run_id}-s06：
         期望成功（NULL 门）；
      2. 同事务先 bind_session({run_id}-s06) → 再 INSERT {run_id}-s07：
         期望 42501（GUC 已绑定时不等于新 id）；
      3. bind_session({run_id}-s08) → INSERT id={run_id}-s08：
         期望成功（GUC 与新 id 一致）。
    断言：成功/拒绝/成功各一次，共 3 条断言。
    解除 missing：T-07 全部。
    """
    raise NotImplementedError('INC-07 not_implemented')


def inc_08_admin_skill_lifecycle(run_id: str) -> dict:
    """INC-08 · app_admin Skill 全生命周期 + 发布并发（解除 T-03 missing 与
    T-08 not_covered）。

    前置数据：无。
    执行步骤：
      1. app_admin 连接：INSERT draft（{run_id}-skill-d）→ 读回（应可见，
         验证 read 策略的 current_user 分支）；
      2. 同角色 UPDATE state='published'；
      3. 并发发布：双连接/双线程同时 INSERT 两个不同 id、state='published'
         的行（版本号不同），barrier 同步启动；
      4. 输家重试 state='archived' 后，再 INSERT 新的 published。
    断言：3 中恰好一个赢家一个 23505 唯一冲突；输家不残留 published 态；
      4 完成后全表恰好一行 published；app_admin 全程可读 draft/archived。
    解除 missing：T-03 的全流转/ON CONFLICT、T-08 发布并发。
    """
    raise NotImplementedError('INC-08 not_implemented')


def inc_09_app_user_skill_visibility(run_id: str) -> dict:
    """INC-09 · app_user 对 skill 的可见性（解除 T-04 missing）。

    前置数据：INC-08 留下的 draft/archived/published 各一。
    执行步骤：以 app_user 连接（GUC 任意）SELECT 全表；再尝试
      INSERT/UPDATE/DELETE skill_versions 各一次。
    断言：SELECT 仅返回 published 行；写全部 42501。
    解除 missing：T-04 的读可见性缺口。
    """
    raise NotImplementedError('INC-09 not_implemented')


def inc_10_connection_guc_reuse(run_id: str) -> dict:
    """INC-10 · 同连接复用串号回归（解除 T-09 not_covered）。

    前置数据：{run_id}-s01/{run_id}-s02 各自的数据（可复用 INC-01/03）。
    执行步骤：在同一物理连接上：
      1. 事务 A：bind_session({run_id}-s01) → 读自身任务（应 1 行）→ 提交；
      2. 事务 B：bind_session({run_id}-s02) → 读 s01 的任务（应 0 行）
         → 读 s02 自身数据（应可见）→ 提交；
      3. 事务 C：不调用 bind_session → 读两会话数据（应均 0 行——
         证明 GUC 随事务结束复位，无持久残留）。
    断言：3 组各条可见性断言；任一残留即失败。
    实现红线：bind_session 必须事务级（set_config 第三参数 true）；实现后
    在本用例注释中记录所用连接池模式（transaction/session pooling）与
    获取途径（Supabase 项目设置），这是 AUD-06 的证据载体。
    解除 missing：T-09 全部。
    """
    raise NotImplementedError('INC-10 not_implemented')


def inc_11_revision_cas(run_id: str) -> dict:
    """INC-11 · 真实库 revision CAS（解除 T-10 missing）。

    前置数据：{run_id}-s07 会话 + {run_id}-task03（revision=1）。
    执行步骤：并发 N=8 线程同时执行 updateOwnedTaskState 等价语句
      （WHERE id AND session_id AND revision=1，SET revision=revision+1）。
    断言：恰好 1 个赢家返回行、7 个 0 行（或等价空结果）；最终表内
      revision=2 且仅一次自增；无报错异常路径。
    解除 missing：T-10 的 CAS 缺口。
    """
    raise NotImplementedError('INC-11 not_implemented')


def inc_12_answer_insert_rollback(run_id: str) -> dict:
    """INC-12 · 答案插入失败整体回滚（解除 T-10 missing）。

    前置数据：{run_id}-s08 会话 + {run_id}-task04（revision=1）。
    执行步骤：单事务内先执行 updateOwnedTaskState（revision→2），
      再执行一条必失败的答案 INSERT（如违反 card_id CHECK 的非法值，
      或制造配额不足后的 answers 写入——实现者选其一并注释）；
      捕获错误后回滚。
    断言：回滚后 task 的 revision 与 updated_at 与事务前一致；answers 表
      无新增行；quota（若涉及）无变化。
    解除 missing：T-10 的回滚语义缺口。
    """
    raise NotImplementedError('INC-12 not_implemented')


def inc_13_idempotent_single_charge(run_id: str) -> dict:
    """INC-13 · 幂等重放单扣费（真实库，解除 T-10 missing）。

    前置数据：{run_id}-s09 会话 + {run_id}-skill + limit=5 的配额窗口。
    执行步骤：N=8 并发对同一 (session_id, idempotency_key) 执行
      findTaskByKey → insertTask(ON CONFLICT DO NOTHING) → consumeQuota
      的事务序列。
    断言：最终恰好 1 个任务行、配额 used 恰好 +1；8 个调用均收到成功
      语义（赢家创建、其余幂等命中），无报错路径。
    解除 missing：T-10 的并发幂等缺口。
    """
    raise NotImplementedError('INC-13 not_implemented')


# ---------------------------------------------------------------------------
# 报告骨架
# ---------------------------------------------------------------------------

CASES = [
    ('INC-01', inc_01_same_session_artifacts),
    ('INC-02', inc_02_same_session_quota),
    ('INC-03', inc_03_cross_session_artifacts_quota),
    ('INC-04', inc_04_cross_session_command_matrix),
    ('INC-05', inc_05_audit_write_denied),
    ('INC-06', inc_06_revoked_expired_session_blocked),
    ('INC-07', inc_07_session_create_dual_path),
    ('INC-08', inc_08_admin_skill_lifecycle),
    ('INC-09', inc_09_app_user_skill_visibility),
    ('INC-10', inc_10_connection_guc_reuse),
    ('INC-11', inc_11_revision_cas),
    ('INC-12', inc_12_answer_insert_rollback),
    ('INC-13', inc_13_idempotent_single_charge),
]

RESULT_TEMPLATE = {
    'run_id': '<filled at runtime>',
    'generated_at_utc': '<filled at runtime>',
    'skeleton_origin': 'dev/acceptance/provider-rls-test-review/verify_rls_incremental_skeleton.py',
    'status': 'not_implemented',
    'note': (
        '本报告由骨架首次实际运行时生成；在主线实现各用例并执行前，'
        '所有用例状态均为 not_implemented，不构成任何 passed 证据，'
        '不改变 test_matrix_relabel 中 T-01~T-10 的现有状态。'
    ),
    'cases': {name: {'status': 'not_implemented'} for name, _ in CASES},
}


def main() -> None:
    """骨架入口：只生成 RUN_ID 与报告文件占位（全部 not_implemented），
    不连接数据库、不执行任何 SQL。主线实现用例后，此入口才允许连接。"""
    require_env()  # 骨架也要求环境变量齐备，防止半配置运行
    run_id = make_run_id()
    report = dict(RESULT_TEMPLATE)
    report['run_id'] = run_id
    report['generated_at_utc'] = datetime.now(timezone.utc).isoformat()
    path = output_path(run_id)
    path.write_text(
        json.dumps(redact(report), ensure_ascii=False, indent=2),
        encoding='utf-8',
    )
    # 禁止输出 'passed'、禁止输出连接信息；只打印报告文件名。
    print(f'skeleton report written: {path.name}')


if __name__ == '__main__':
    main()
