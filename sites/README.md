# Qoder Sites 混合部署入口

本目录是 Qoder Sites 的本地 Functions 适配层，未执行部署、后端开通、PAT 创建或公开发布。

## 边界

- Qoder Sites 负责公开网页、同源 Functions、任务数据和下载入口。
- 外部 Python 服务继续执行 OpenAlex 检索、PDF/OCR、图谱和 Office 生成。
- `functions/index.ts` 只允许健康检查、匿名会话和单个任务读取，不提供通用代理或任意 URL 转发。

## 配置

部署前通过服务器环境变量设置 `PYTHON_API_ORIGIN`，指向外部 Python 后台的 HTTPS 根地址。禁止把数据库密钥、模型密钥或 QODER_PAT 写入前端或仓库。

## 公开访问

匿名会话不需要邀请码。外部 Python 的 `POST /api/session` 接受空 JSON `{}` 并签发 HttpOnly 会话 Cookie。任务读取继续按会话所有者隔离，非所有者的任务返回 404。
