# 推送通道攻坚报告

- 探测时间：2026-11-25 13:05–13:10 GMT+8
- 仓库：`/Users/crisprcas_9/WorkBuddy/2026-11-06-20-49-06/purpose-landscape-web`
- 范围：仅网络与凭据通道探测。**未 push、未改代码 / remote / git config、未创建凭据或密钥、未部署**。
- 脱敏说明：本报告不记录任何 token、口令、私钥或代理认证信息；代理只记录地址与端口。

## 0. 结论摘要

1. **“HTTPS/SSH 被网络阻断”的前提已不成立**：本机现在可通过 HTTPS 直连和代理两种方式完成 `git ls-remote origin`（均 rc=0），SSH 的 22/443 端口也完成了 TCP + SSH 握手（报 `Permission denied (publickey)`，属认证失败而非网络失败）。
2. **唯一剩余缺口是写权限凭据**：仓库 origin 为 HTTPS 且不含内嵌凭据；系统无 GitHub token 环境变量、无 `gh`、keychain 无可用凭据、无 SSH 私钥、agent 无身份、无 `~/.ssh/config`。`GET /api.github.com/user` 返回 401。
3. **最优路径**：不需要开代理节点，也不需要改 remote。用户提供一个最小权限凭据后直接 `git push origin main` 即可（9 个提交为快进，无需 force）。
4. 背景中“领先 8 个提交”与实测不符：**实际领先 `origin/main` 9 个提交、落后 0**（`3cfbe6f` vs `ebd9534`）。共 18 个文件变更，未触及 `.github/workflows/`。

## 1. 通道矩阵

| # | 通道 | 关键探测命令（脱敏） | 结果 | 耗时 | 判定 |
|---|---|---|---|---|---|
| 1 | 进程级 HTTP 代理 `http://127.0.0.1:49290` | `curl -sSI --max-time 15 https://github.com` | `HTTP/1.1 200 Connection Established` + `HTTP/2 200` | <15s | 可用 |
| 2 | 同上，`git ls-remote origin` | `GIT_TERMINAL_PROMPT=0 timeout 45 git ls-remote origin` | rc=0，返回 `ebd9534... refs/heads/main` | 3s | **可用** |
| 3 | 直连（清空代理变量） | `env -u HTTP_PROXY -u HTTPS_PROXY -u http_proxy -u https_proxy ... git ls-remote origin` | rc=0，同样返回 `ebd9534...` | 1s | **可用 / 最快** |
| 4 | `api.github.com` HTTPS | `curl -o /dev/null -w '%{http_code}' --max-time 12 https://api.github.com` | 200（代理 0.55s / 直连 2.62s） | 0.5–2.6s | 可用 |
| 5 | 常见本地端口 7890/7891/1080/8118/8080 | `nc -z -G 2 127.0.0.1 <port>` | 全部 CLOSED | 各 <2s | 无代理服务 |
| 6 | macOS 系统代理 | `scutil --proxy`、`networksetup -get{web,secureweb,socksfirewall}proxy Wi-Fi` | 三项均 `Enabled: No`；无代理字典 | — | 未配置 |
| 7 | SSH `github.com:22` | `ssh -T -p 22 github.com -o BatchMode=yes -o UserKnownHostsFile=/dev/null` | `Permission denied (publickey)`（握手成功） | 2s | 网络通，**无授权 key** |
| 8 | SSH `ssh.github.com:443` | `ssh -T -p 443 ssh.github.com ...` | `Permission denied (publickey)`（握手成功） | 3s | 网络通，**无授权 key** |
| 9 | Git over SSH（只读） | `git ls-remote ssh://git@github.com:22/...`、`ssh://git@ssh.github.com:443/...` | 两次均 rc=128：`Permission denied (publickey)` | 2s / 2s | 不可读，需 key |
| 10 | 经 49290 的 CONNECT 隧道（`nc -X connect`） | `nc -X connect -x 127.0.0.1:49290 -z -G 6 <host> <port>` | 4 个目标均 CONNECT_FAILED | 各 <6s | 探针误报，见 §2.2 |
| 11 | 原始 TCP 探测 `nc -z` | `nc -4/-6 -z -G 5 github.com 443` 等 | 全 FAILED，但 curl/ssh 同目标成功 | 各 <5s | **判为探针误报**，不作结论依据 |

## 2. 逐项证据

### 2.1 代理环境变量（只列存在性与地址）

| 变量 | 状态 |
|---|---|
| `HTTP_PROXY` / `HTTPS_PROXY` / `http_proxy` / `https_proxy` | SET，`http://127.0.0.1:49290`（无 userinfo） |
| `ALL_PROXY` / `all_proxy` | UNSET |
| `NO_PROXY` / `no_proxy` | SET，3 条例外（值未展开） |

`127.0.0.1:49290` 端口 OPEN；`curl -I` 经它返回 `HTTP/1.1 200 Connection Established`，说明 CONNECT 隧道可用。表中第 10 行的 `nc -X connect` 失败与该结果矛盾，且同机 `nc -z` 对 443/22 也全部误报（第 11 行），因此以 curl / ssh / git 的应用层结果为准。

### 2.2 凭据面（只读，值一律不输出）

| 项 | 结果 |
|---|---|
| `GITHUB_TOKEN` / `GH_TOKEN` / `GIT_TOKEN` / `GH_PAT` / `PERSONAL_ACCESS_TOKEN` | 全部 UNSET |
| `gh` CLI | 未安装 |
| `credential.helper` | 系统 gitconfig 中为 `osxkeychain`；仓库 local 未覆盖 |
| `git credential fill`（host=github.com，输出仅判断有无字段） | rc=128，`username_present=no password_present=no` |
| `GET https://api.github.com/user`（无凭据） | 401，1.61s |
| `~/.ssh/` | 仅 `agent/` 与 `known_hosts`；无 `config`；`id_rsa/id_ed25519/id_ecdsa` 均不存在 |
| `ssh-add -l` | `The agent has no identities.` |
| `remote.origin.url` | `https://github.com/guzihao123/biblio-purposcape.git`（无内嵌凭据，未修改） |
| git config 覆盖 | 除 remote url/fetch 外无 `http.*`、`url.*`、`credential.*` 覆盖 |

### 2.3 只读 ls-remote 汇总

| 通道 | 命令 | 结果 | 耗时 |
|---|---|---|---|
| 环境代理 | `GIT_TERMINAL_PROMPT=0 timeout 45 git -C <repo> ls-remote origin` | rc=0；`ebd9534f24992faf0861181b9e44e29137f7856a  HEAD` / `refs/heads/main` | 3s |
| 直连 | 同上，前置 `env -u HTTP_PROXY -u HTTPS_PROXY -u http_proxy -u https_proxy -u ALL_PROXY -u all_proxy` | rc=0，同一 SHA | 1s |
| SSH:22 | `git ls-remote ssh://git@github.com:22/guzihao123/biblio-purposcape.git` | rc=128，`Permission denied (publickey)` | 2s |
| SSH:443 | `git ls-remote ssh://git@ssh.github.com:443/guzihao123/biblio-purposcape.git` | rc=128，`Permission denied (publickey)` | 2s |

远端 main 仍为 `ebd9534...`，本地 main 为 `3cfbe6f...`，`git status -sb` 显示 `[ahead 9]`。全部探测后工作区状态未变（无新增/修改跟踪文件）。

## 3. 备选方案评估

### 3.1 GitHub REST Git Data API（可行，但代价高）

**最小权限**（官方 REST 文档口径）：

- 推荐：fine-grained PAT，Resource owner = `guzihao123`，Repository access = 仅 `biblio-purposcape`，权限 **Contents: Read and write**（`write` 已含 `read`）；`Metadata: read` 为固有只读权限，无需单独勾选。本次 18 个文件不含 workflow 文件，故**不需要** `Workflows: write`；不开 PR 则不需要 `Pull requests: write`。
- 等价 classic PAT：仓库为公开（匿名 `ls-remote` 成功），最小 scope 为 `public_repo`；若仓库改私有则需 `repo`。
- 通用请求头：`Accept: application/vnd.github+json`、`X-GitHub-Api-Version: 2026-03-10`、`Authorization: Bearer "$PAT"`（`$PAT` 只在 shell 变量中，禁止写入仓库或命令行历史）。

**调用清单（一次提交，9 个提交需重复 9 轮以保留历史；否则会被压成 1 个 commit）**：

1. `GET /repos/guzihao123/biblio-purposcape/git/ref/heads/main` → 取当前远端 commit SHA（每轮更新）
2. `GET /repos/guzihao123/biblio-purposcape/git/trees/<parent_sha>?recursive=1` → 取 base tree（可选）
3. 对每个改动文件 `POST /repos/guzihao123/biblio-purposcape/git/blobs`，body `{"content":"<base64>","encoding":"utf-8"}` → blob sha
4. `POST /repos/guzihao123/biblio-purposcape/git/trees`，body `{"base_tree":"<tree_sha>","tree":[{"path":"<path>","mode":"100644","type":"blob","sha":"<blob_sha>"}]}` → 新 tree sha
5. `POST /repos/guzihao123/biblio-purposcape/git/commits`，body `{"message":"<msg>","tree":"<new_tree>","parents":["<parent_sha>"],"author":{...},"committer":{...}}` → 新 commit sha
6. `PATCH /repos/guzihao123/biblio-purposcape/git/refs/heads/main`，body `{"sha":"<new_commit>","force":false}` → 200

局限：需自行按 `git rev-list --reverse origin/main..main` 重放 9 次、手工构造 18 个 blob、处理二进制 base64 与文件 mode；易出错且等价于“重写推送”，非首选。

### 3.2 GitLab 镜像（需账号，不推荐）

需另开 GitLab 账号 + 写权限 token，新增 remote 并把 9 个提交推到镜像；这既不能让 GitHub/Render 自动拿到代码，还扩大了凭据面。除非明确要把 GitLab 设为新的源站并同步改 Render 连接源，否则不是最小路径。本次未创建任何 remote 或账号。

### 3.3 Render Deploy Hook（不能解决本问题）

仓库 `render.yaml` 使用 Blueprint 服务，从已连接的 Git 仓库构建；仓库内只检索到 `biblio-purposcape.onrender.com` 健康检查/入口地址，**未发现 deploy hook URL**（也不会把 hook 这类 secret 写进仓库）。Deploy Hook 的作用只是“对 Render 已拉取到的某个提交触发一次重新构建/部署”：它不会去 GitHub 抓取尚未推送的 9 个提交。因此若 origin/main 仍是 `ebd9534`，触发 hook 只会重新部署旧代码。**必须先让 GitHub 收到新提交，hook 才有意义**（或直接由 push 触发自动部署）。

## 4. 建议：最优路径与最小用户操作

**结论：无需代理、无需改配置，补一个写权限凭据即可直接推。**

1. 生成 fine-grained PAT：Resource owner `guzihao123` → 仅选 `biblio-purposcape` → Permissions **Contents: Read and write** → 设短有效期。（classic 等价：最小 `public_repo`。）
2. 在仓库执行（不含任何 secret，PAT 在交互提示的“密码”栏粘贴；已有 `osxkeychain` helper 可选择是否保存）：

   ```bash
   cd /Users/crisprcas_9/WorkBuddy/2026-11-06-20-49-06/purpose-landscape-web
   git push origin main
   ```

3. 推送后只读校验（两者应同为被推上去的新 SHA）：

   ```bash
   git ls-remote origin refs/heads/main
   git rev-parse main
   ```

**备选（若更愿意用密钥，需用户自己创建并赋写权限 deploy key）**：22 与 443 的 SSH 网络均已验证通畅，可用运行时覆盖、不改 git config：

```bash
GIT_SSH_COMMAND='ssh -i <your-key> -o IdentitiesOnly=yes -o ConnectTimeout=8' \
  git push ssh://git@ssh.github.com:443/guzihao123/biblio-purposcape.git main
```

## 5. 已验证失败项（供复核）

| 命令 | 错误 |
|---|---|
| `curl --max-time 12 https://github.com`（完整下载） | `(28) Operation timed out`，但已收到 `http=200` 与 268KB；HEAD 探测为 200，属页面体过大/慢，非通道失败 |
| `nc -z -G 2 127.0.0.1 {7890,7891,1080,8118,8080}` | 全部无监听 |
| `nc -4/-6 -z -G 5 github.com 443` 等 | 全部 FAILED，与 curl/ssh 成功矛盾，判为探针误报 |
| `nc -X connect -x 127.0.0.1:49290 -z -G 6 ...` | CONNECT_FAILED，被 curl 的 `200 Connection Established` 反证 |
| `ssh -T -p 22 github.com` / `-p 443 ssh.github.com` | `Permission denied (publickey)` |
| `git ls-remote ssh://git@...`（22 与 443） | rc=128，`Permission denied (publickey)` |
| `git credential fill`（host=github.com） | rc=128，无 username/password 字段 |
| `curl https://api.github.com/user` | 401 |

## 6. 约束遵守情况

未执行 `git push` / `commit` / `remote` / `config` 写操作；未创建或读取任何私钥、token、keychain 条目内容（仅判断存在性）；SSH 探测使用 `BatchMode` 与 `UserKnownHostsFile=/dev/null`，未写入 known_hosts；未部署、未触发 Render hook；报告内无 secret。唯一新增文件即本报告。

## 复查更新（2026-11-25 13:28 GMT+8）

本节为用户复查后的最新口径，**与上文冲突时以本节为准**；上文保留作为当时探测记录，不再作为部署依据。

- 探测时可用的 `127.0.0.1:49290` **现已关闭**；当时得到的“HTTPS/SSH 已通”不是稳定状态，**不能作为部署路径**。
- 当前主线环境代理为 `127.0.0.1:55855`，CONNECT 返回 **407（需要认证）**；直连 `github.com` 仍然超时。
- 稳定可用端点是 **`api.github.com`（直连 200）**。
- 主线已按 Git Data API 写好推送脚本，dry-run 通过：**15 个提交、29 个文件、约 600KB**，无密钥文件；待 PAT 到位即推，**不需要代理、不改 remote、不 force**。
- 提交数已从 9 增至 **15**；上文的 9、18 个文件等旧数字作废，不再追。
- **最终路径**：fine-grained PAT（仅授权该仓库、`Contents: Read and write`）→ 经 `api.github.com` 重放提交 → 校验 ref。classic token 对私有仓库需要 `repo` 权限，**`public_repo` 不够**（上文 §3.1 的 classic scope 口径作废）。
- SSH 无授权 key 的结论**保持**；GitLab 镜像与 Render Deploy Hook **不作为方案**。
- 本次仅追加本节，未再探测、未尝试 push。
