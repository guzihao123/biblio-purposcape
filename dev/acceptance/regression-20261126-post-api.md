# 最新本地回归（2026-11-26，含 5xx 回读修复）

基线：integration3 `0b83b2f`（5xx 后答案状态回读）；桌面描述修正提交 `64bf6ef` 不影响测试结果。

| 套件 | 命令 | 结果 |
|---|---|---|
| 后端 | `.venv/bin/python -m pytest backend/tests -q -p no:cacheprovider` | 622 passed / 5 skipped |
| 前端单测 | `cd frontend && npm test` | 41 passed |
| Deno 函数 | `deno test --allow-all --import-map=dev/import_map.json sites/functions/*.test.mjs` | 65 passed |
| Playwright 主流程 | `node node_modules/playwright/cli.js test --config=playwright.config.ts` | 11 passed |

合计 **739 passed / 5 skipped / 0 failed**。此前基于 `030a443` 的 738 条回归已过期，以本记录为准。

边界：本次仅验证本地自动化；A 模式线上验收仍未拿到 Word，不因本地全绿而解除 blocked。