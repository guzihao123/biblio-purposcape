#!/usr/bin/env python3
"""check_render_contract.py — Render B-01/B-03/B-04 阻断的离线静态检查器。

只读检查以下主线文件（绝不修改）：
  Dockerfile / render.yaml / .env.example
  frontend/src/api.ts / frontend/vite.config.ts
  backend/app/config.py / backend/app/main.py
以及 dev/acceptance/render-preflight/ 下的历史快照（只读参考）。

三档判定口径（本脚本只做第一档）：
  config_declaration  配置声明存在与否的静态事实（本脚本能给 pass/fail）
  runtime_security    运行时安全（启动守卫、真实密钥注入等）——静态不可判定，一律 not_verified
  cloud_verification  真实云端验证——本脚本不触碰任何云资源，一律 not_verified

红线：不修改 Dockerfile 等任何主线文件制造通过；静态通过不得冒充运行时或云端通过。

用法：
  python3 check_render_contract.py [--root <项目根目录>]
                                   [--out <result.json 输出路径>]

退出码：0 = 全部静态阻断已解除；1 = 仍有静态阻断失败（或脚本自身出错）。
"""

from __future__ import annotations

import argparse
import datetime
import json
import re
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# 三档定义
# ---------------------------------------------------------------------------
TIERS = {
    "config_declaration": {
        "label": "配置声明存在（静态，本脚本可判定）",
        "decidable": True,
    },
    "runtime_security": {
        "label": "运行时安全（需真实进程/密钥注入证据，静态不可判定）",
        "decidable": False,
    },
    "cloud_verification": {
        "label": "真实云端验证（需 Render 云端环境，本脚本不触碰云资源）",
        "decidable": False,
    },
}

STATIC_UNVERIFIED_NOTE = (
    "静态检查只证明文件内容，不等于运行时或云端行为已通过；"
    "运行时与云端档位在本脚本中一律记为 not_verified，禁止据此宣称解除阻断。"
)

RUNTIME_UNVERIFIED = [
    "未设置 SESSION_SECRET/ADMIN_TOKEN 时生产模式是否启动即报错（无启动守卫证据）",
    "真实密钥值是否已在创建服务时注入并离线存档（本脚本不读取任何真实密钥）",
    "数据库增量迁移（initialize_database 的 ALTER）未在外部 Postgres 实测",
    "前端构建产物内 API_BASE 实际烘焙值未在容器/vite preview 中核验",
]

CLOUD_UNVERIFIED = [
    "未创建 Render 服务、未部署、未执行真实 HTTP 回归（登录/建单/轮询/工件下载）",
    "未连接真实 Postgres，web/worker 同实例一致性未核对",
    "未验证重启/重新部署后会话保持有效、ADMIN_TOKEN 可调通受保护端点",
    "未调用任何付费模型、未做云端故障注入",
]


def ev(file_rel: str, line: int | None, snippet: str) -> dict:
    """构建一条带行号的证据（snippet 原样摘录，不改写）。"""
    e = {"file": file_rel}
    if line is not None:
        e["line"] = line
    e["snippet"] = snippet.strip()
    return e


def check(
    cid: str,
    tier: str,
    blocker: str | None,
    description: str,
    status: str,
    evidence: list[dict],
    unverified: list[str] | None = None,
    remediation: str | None = None,
) -> dict:
    assert tier in TIERS
    item = {
        "id": cid,
        "tier": tier,
        "blocker": blocker,
        "description": description,
        "status": status,  # pass | fail | not_verified
        "evidence": evidence,
    }
    if unverified:
        item["unverified_boundaries"] = unverified
    if remediation:
        item["remediation"] = remediation
    return item


# ---------------------------------------------------------------------------
# 文本工具
# ---------------------------------------------------------------------------
def read_lines(root: Path, rel: str) -> list[str]:
    return (root / rel).read_text(encoding="utf-8").splitlines()


def find_line(lines: list[str], pattern: str, flags: int = 0) -> int | None:
    rx = re.compile(pattern, flags)
    for i, ln in enumerate(lines, start=1):
        if rx.search(ln):
            return i
    return None


def find_line_with_text(lines: list[str], pattern: str, flags: int = 0) -> tuple[int | None, str]:
    rx = re.compile(pattern, flags)
    for i, ln in enumerate(lines, start=1):
        if rx.search(ln):
            return i, ln
    return None, ""


# ---------------------------------------------------------------------------
# render.yaml 的最小行级解析（标准库无 YAML，只取本检查需要的字段）
# ---------------------------------------------------------------------------
def parse_render_services(lines: list[str]) -> dict[str, dict]:
    """返回 {service_name: {"type":..., "env": {key: {"sync":..., "value":..., "fromService": bool}}}}"""
    services: dict[str, dict] = {}
    current: dict | None = None
    in_envvars = False
    current_key: str | None = None
    for raw in lines:
        stripped = raw.strip()
        if re.match(r"^-\s+type:\s*(\w+)", stripped):
            stype = re.match(r"^-\s+type:\s*(\w+)", stripped).group(1)
            current = {"type": stype, "env": {}}
            in_envvars = False
            current_key = None
            continue
        if current is None:
            continue
        m = re.match(r"^name:\s*(.+)$", stripped)
        if m and not in_envvars and current.get("name") is None and "name" not in current:
            name = m.group(1).strip()
            if name and name not in current:
                current["name"] = name
                services[name] = current
                continue
        if stripped == "envVars:":
            in_envvars = True
            continue
        if in_envvars:
            m = re.match(r"^-\s+key:\s*(\S+)", stripped)
            if m:
                current_key = m.group(1)
                current["env"][current_key] = {"sync": None, "value": None, "fromService": False}
                continue
            if current_key is None:
                continue
            m = re.match(r"^sync:\s*(\S+)", stripped)
            if m:
                current["env"][current_key]["sync"] = m.group(1).lower() == "true"
                continue
            m = re.match(r"^value:\s*(.+)$", stripped)
            if m:
                current["env"][current_key]["value"] = m.group(1).strip()
                continue
            if stripped.startswith("fromService:"):
                current["env"][current_key]["fromService"] = True
                continue
    return services


# ---------------------------------------------------------------------------
# 各检查项
# ---------------------------------------------------------------------------

def check_b01_dockerfile_api_base(root: Path) -> dict:
    rel = "Dockerfile"
    lines = read_lines(root, rel)
    line_no, text = find_line_with_text(lines, r"^ARG\s+VITE_API_BASE_URL=")
    evidence = []
    if line_no is not None:
        evidence.append(ev(rel, line_no, text))
        m = re.match(r"^ARG\s+VITE_API_BASE_URL=(.*)$", text.strip())
        default = (m.group(1).strip() if m else "").strip('"\'')
    else:
        default = None
        evidence.append(ev(rel, None, "未找到 ARG VITE_API_BASE_URL 声明"))

    # 参考点：api.ts 的运行时回退值（只读证据，证明生产期望 /api）
    api_lines = read_lines(root, "frontend/src/api.ts")
    fallback_line, fallback_text = find_line_with_text(api_lines, r"VITE_API_BASE_URL\s*\|\|")
    if fallback_line:
        evidence.append(ev("frontend/src/api.ts", fallback_line, fallback_text))

    suitable = default == "/api"
    if default is None:
        status, remediation = "fail", "Dockerfile 缺少 VITE_API_BASE_URL ARG 声明，需显式声明并默认 /api"
    elif not suitable:
        status = "fail"
        remediation = (
            f"B-01 未解除：Dockerfile 第 {line_no} 行将前端 API 基址烘焙为 {default!r}，"
            "而 FastAPI 同源服务实际路由前缀为 /api（main.py /api/*），"
            "生产调用会被 SPA 回退吞掉。修复方式是把 ARG 默认值改为 /api（或构建时显式传 /api），"
            "本检查器只报告、不修改 Dockerfile。"
        )
    else:
        status, remediation = "pass", None
    return check(
        "C-01", "config_declaration", "B-01",
        "Dockerfile VITE_API_BASE_URL 默认值是否适合 FastAPI 同源 /api",
        status, evidence,
        unverified=[STATIC_UNVERIFIED_NOTE, *RUNTIME_UNVERIFIED[3:4], *CLOUD_UNVERIFIED[0:1]],
        remediation=remediation,
    )


def check_b01_env_example_alignment(root: Path) -> dict:
    rel = ".env.example"
    lines = read_lines(root, rel)
    line_no, text = find_line_with_text(lines, r"^VITE_API_BASE_URL=")
    evidence = []
    value = None
    if line_no:
        evidence.append(ev(rel, line_no, text))
        value = text.split("=", 1)[1].strip()
    docker_lines = read_lines(root, "Dockerfile")
    dline, dtext = find_line_with_text(docker_lines, r"^ARG\s+VITE_API_BASE_URL=")
    if dline:
        evidence.append(ev("Dockerfile", dline, dtext))
    aligned = value == "/api"
    return check(
        "C-02", "config_declaration", "B-01",
        ".env.example 的 VITE_API_BASE_URL 与 /api 口径是否一致",
        "pass" if aligned else "fail", evidence,
        unverified=[STATIC_UNVERIFIED_NOTE] if not aligned else None,
        remediation=None if aligned else
        f".env.example 第 {line_no} 行仍为 {value!r}，与 Dockerfile 口径一致地偏离 /api；"
        "按 mainline-recheck 口径，B-01 静态通过要求 render.yaml 与 .env.example 口径一致为 /api。",
    )


def check_render_service_env_consistency(root: Path) -> list[dict]:
    rel = "render.yaml"
    lines = read_lines(root, rel)
    services = parse_render_services(lines)
    out = []
    web = next((s for s in services.values() if s["type"] == "web"), None)
    worker = next((s for s in services.values() if s["type"] == "worker"), None)
    redis = next((s for s in services.values() if s["type"] == "redis"), None)

    # C-03: web/worker 环境变量集合一致
    if web and worker:
        wk, kk = set(web["env"]), set(worker["env"])
        only_web, only_worker = sorted(wk - kk), sorted(kk - wk)
        status = "pass" if not only_web and not only_worker else "fail"
        evidence = [ev(rel, None, f"web env keys: {sorted(wk)}"),
                    ev(rel, None, f"worker env keys: {sorted(kk)}")]
        for key in ("DATABASE_URL", "SESSION_SECRET", "ADMIN_TOKEN", "REDIS_URL"):
            ln, _t = find_line_with_text(lines, rf"key:\s*{re.escape(key)}$")
            if ln:
                evidence.append(ev(rel, ln, f"- key: {key}"))
        out.append(check(
            "C-03", "config_declaration", None,
            "render.yaml web/worker 必需变量声明集合一致（DATABASE_URL、SESSION_SECRET、ADMIN_TOKEN 等）",
            status, evidence,
            remediation=None if status == "pass" else
            f"web 独有: {only_web}；worker 独有: {only_worker}，两侧需一致",
        ))

    # C-04: 必需变量在两侧均以 sync:false 声明（声明存在 ≠ 值已注入）
    required = ["DATABASE_URL", "SESSION_SECRET", "ADMIN_TOKEN",
                  "QODER_SITES_ORIGIN", "WORKER_SHARED_SECRET", "QWEN_API_KEY"]
    missing, not_sync = [], []
    evidence = []
    for key in required:
        ln, _t = find_line_with_text(lines, rf"key:\s*{re.escape(key)}$")
        if ln:
            evidence.append(ev(rel, ln, f"- key: {key}"))
        for svc_name, svc in (("web", web), ("worker", worker)):
            if svc is None:
                missing.append(f"{key}@{svc_name}(服务缺失)")
                continue
            spec = svc["env"].get(key)
            if spec is None:
                missing.append(f"{key}@{svc_name}")
            elif spec["sync"] is not False and spec["value"] is None and not spec["fromService"]:
                not_sync.append(f"{key}@{svc_name}")
    status = "fail" if missing else ("fail" if not_sync else "pass")
    out.append(check(
        "C-04", "config_declaration", None,
        "DATABASE_URL/SESSION_SECRET/ADMIN_TOKEN 等必需变量在 web/worker 均以 sync:false 声明"
        "（仅证明声明存在，不证明值已注入）",
        status, evidence,
        unverified=[
            "sync:false 仅声明'由部署者在创建服务时注入'，本脚本无法验证真实值是否已设置",
            "本脚本不读取任何真实密钥值",
        ],
        remediation=f"缺失声明: {missing}；非 sync 声明: {not_sync}" if status == "fail" else None,
    ))

    # C-05: REDIS_URL fromService 两侧一致指向同一 redis 服务
    if web and worker:
        ok = (web["env"].get("REDIS_URL", {}).get("fromService")
              and worker["env"].get("REDIS_URL", {}).get("fromService"))
        ln, _t = find_line_with_text(lines, r"name:\s*landscape-redis")
        evidence = [ev(rel, ln, "landscape-redis")] if ln else []
        if redis is None:
            ok = False
        out.append(check(
            "C-05", "config_declaration", None,
            "REDIS_URL 经 fromService 自动注入且 web/worker 一致",
            "pass" if ok else "fail", evidence,
            remediation=None if ok else "REDIS_URL 未使用 fromService 或两侧不一致，或 redis 服务缺失",
        ))

    # C-06: B-03 —— DATABASE_URL 来源与 SQLite 回落证据
    cfg_rel = "backend/app/config.py"
    cfg = read_lines(root, cfg_rel)
    db_line, db_text = find_line_with_text(cfg, r"database_url\s*:\s*str\s*=")
    evidence = [ev(cfg_rel, db_line, db_text)] if db_line else []
    if web:
        spec = web["env"].get("DATABASE_URL", {})
        if not spec.get("fromService") and spec.get("value") is None:
            # sync:false 且无 Postgres 服务 → 漏配即回落
            ln, _t = find_line_with_text(lines, r"key:\s*DATABASE_URL")
            if ln:
                evidence.append(ev(rel, ln, "- key: DATABASE_URL / sync: false"))
        has_postgres = redis is not None and any(
            s["type"] == "pserv" or "postgres" in (s.get("name") or "") for s in services.values()
        )
        if not has_postgres:
            evidence.append(ev(rel, None, "render.yaml 未声明 Postgres 服务；DATABASE_URL 依赖人工注入"))
    fallback_evident = db_line is not None and "sqlite" in db_text.lower()
    if fallback_evident:
        status = "fail"
        remediation = (
            f"B-03 未解除：config.py 第 {db_line} 行 database_url 默认仍为 SQLite"
            "（漏配 DATABASE_URL 时静默回落），render.yaml 无 Postgres 服务、"
            "DATABASE_URL 为 sync:false 人工注入。证据链仍在，"
            "静态解除条件：生产模式漏配拒绝启动 / 外部 Postgres 成为唯一事实源的声明与守卫。"
        )
    else:
        status = "pass"
        remediation = None
    out.append(check(
        "C-06", "config_declaration", "B-03",
        "DATABASE_URL 漏配回落 SQLite 的危险证据是否仍在（B-03）",
        status, evidence,
        unverified=[STATIC_UNVERIFIED_NOTE,
                    "外部 Postgres 上的增量迁移（initialize_database ALTER）未实测",
                    *CLOUD_UNVERIFIED[1:2]],
        remediation=remediation,
    ))

    # C-07: B-04 —— 生产密钥随机轮换风险证据
    sec_line, sec_text = find_line_with_text(cfg, r"session_secret.*token_urlsafe")
    adm_line, adm_text = find_line_with_text(cfg, r"admin_token.*token_urlsafe")
    evidence = []
    if sec_line:
        evidence.append(ev(cfg_rel, sec_line, sec_text))
    if adm_line:
        evidence.append(ev(cfg_rel, adm_line, adm_text))
    rotation_evident = sec_line is not None and adm_line is not None
    declared = web and worker and all(
        web["env"].get(k, {}).get("sync") is False and worker["env"].get(k, {}).get("sync") is False
        for k in ("SESSION_SECRET", "ADMIN_TOKEN")
    )
    if rotation_evident:
        status = "fail"
        remediation = (
            f"B-04 未解除：config.py 第 {sec_line} 行 session_secret、第 {adm_line} 行 admin_token "
            "缺省时仍由 secrets.token_urlsafe 随机生成——漏配即每次启动全员掉线/admin 不可用。"
            "声明侧（render.yaml sync:false）已在 C-04 覆盖，但运行时启动守卫证据不存在。"
        )
    else:
        status = "pass"
        remediation = None
    out.append(check(
        "C-07", "config_declaration", "B-04",
        "SESSION_SECRET/ADMIN_TOKEN 漏配随机轮换风险证据是否仍在（B-04）",
        status, evidence,
        unverified=[STATIC_UNVERIFIED_NOTE,
                    "无启动守卫证据：漏配密钥时生产模式是否拒绝启动未验证",
                    "云端重启/重部署后会话保持性未验证"],
        remediation=remediation,
    ))
    return out


def check_runtime_and_cloud_placeholders(root: Path) -> list[dict]:
    """显式记录运行时与云端两档为 not_verified，防止静态结果被误读为解除阻断。"""
    return [
        check(
            "R-01", "runtime_security", "B-01/B-03/B-04",
            "运行时安全档位：启动守卫、真实密钥注入、构建产物烘焙值核验",
            "not_verified", [],
            unverified=RUNTIME_UNVERIFIED,
        ),
        check(
            "R-02", "cloud_verification", "B-01/B-03/B-04",
            "真实云端验证档位：Render 部署、真实 HTTP 回归、真实 Postgres 一致性",
            "not_verified", [],
            unverified=CLOUD_UNVERIFIED,
        ),
    ]


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Render B-01/B-03/B-04 离线静态契约检查器（只读）")
    parser.add_argument("--root", default=None,
                        help="项目根目录（默认取本脚本 ../../../../，即 purpose-landscape-web）")
    parser.add_argument("--out", default=None,
                        help="result.json 输出路径（默认 <本目录>/result.json）")
    args = parser.parse_args(argv)

    script_dir = Path(__file__).resolve().parent
    root = Path(args.root).resolve() if args.root else script_dir.parents[2]
    out_path = Path(args.out).resolve() if args.out else script_dir / "result.json"

    # 只读文件清单（存在性校验；缺失记为检查失败而非崩溃）
    readonly_files = [
        "Dockerfile", "render.yaml", ".env.example",
        "frontend/src/api.ts", "frontend/vite.config.ts",
        "backend/app/config.py", "backend/app/main.py",
    ]
    checks: list[dict] = []
    missing = [f for f in readonly_files if not (root / f).is_file()]
    if missing:
        checks.append(check(
            "C-00", "config_declaration", "B-01/B-03/B-04",
            "只读输入文件齐备性", "fail",
            [ev(f, None, "文件缺失") for f in missing],
            remediation=f"缺少输入: {missing}",
        ))

    try:
        checks.append(check_b01_dockerfile_api_base(root))
        checks.append(check_b01_env_example_alignment(root))
        checks.extend(check_render_service_env_consistency(root))
        checks.extend(check_runtime_and_cloud_placeholders(root))
    except OSError as exc:
        checks.append(check(
            "C-00", "config_declaration", "B-01/B-03/B-04",
            f"读取输入文件失败: {exc}", "fail", [],
        ))

    # 历史快照参考（只读，不改写 render-preflight）
    preflight_ref = root / "dev/acceptance/render-preflight/mainline-recheck.json"
    reference = None
    if preflight_ref.is_file():
        reference = {
            "file": "dev/acceptance/render-preflight/mainline-recheck.json",
            "role": "历史快照（只读参考）；冲突时以最新复核口径为准，本脚本不改写 render-preflight 下任何文件",
        }

    failed = [c for c in checks if c["status"] == "fail"]
    blocker_status = {}
    for c in checks:
        if c["blocker"]:
            cur = blocker_status.get(c["blocker"])
            blocker_status[c["blocker"]] = "fail" if c["status"] == "fail" else (
                cur if cur == "fail" else c["status"])

    result = {
        "task": "Render B-01/B-03/B-04 阻断离线静态检查（可重复运行）",
        "date": datetime.datetime.now().astimezone().strftime("%Y-%m-%d %H:%M %Z"),
        "root": str(root),
        "scope_note": (
            "纯静态检查：未修改任何主线文件与 render-preflight 工地文件；未安装依赖、未运行 "
            "Node/Docker、未启动 HTTP 服务、未连接数据库/Redis、未读取真实密钥、"
            "未创建云资源、未部署、未调用付费模型。"
        ),
        "tiers": TIERS,
        "tier_policy": (
            "status=pass 仅表示 config_declaration 档的静态事实成立；"
            "runtime_security 与 cloud_verification 两档在本脚本中恒为 not_verified，"
            "任何 pass 都不得被解读为运行时或云端阻断已解除。"
        ),
        "checks": checks,
        "blocker_status": blocker_status,
        "overall_verdict": "BLOCKED" if failed else "STATIC_PASS",
        "overall_reason": (
            "存在未解除的静态阻断（见 checks 中 status=fail 项）；"
            "即使全部静态通过，也仍需运行时与云端两档证据才能宣称 B-01/B-03/B-04 真正解除。"
            if failed else
            "静态声明档全部通过；运行时与云端档位仍未验证，不得宣称部署就绪。"
        ),
        "historical_reference": reference,
        "generated_by": "dev/acceptance/render-config-contract/check_render_contract.py",
    }

    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"root: {root}")
    print(f"result: {out_path}")
    for c in checks:
        print(f"  [{c['status']:>12}] {c['id']} ({c['tier']}) {c['description']}")
    print(f"overall: {result['overall_verdict']}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
