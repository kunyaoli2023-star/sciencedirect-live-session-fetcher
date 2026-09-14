# Codex 使用说明：AIC Review Live-Session Fetcher

这份说明用于让 Codex 在 Windows 上，通过用户已经登录并获授权的 ScienceDirect 浏览器会话，下载 *Automation in Construction* 论文。

本工具只使用用户本人或学校提供的合法访问权限，不绕过付费墙，不使用 Sci-Hub，不导出或重放 Cookie，也不处理验证码。

## 1. 在 Codex 中安装 Skill

在 Codex 新对话中发送：

```text
请从下面的 GitHub 路径安装 Codex Skill：
https://github.com/kunyaoli2023-star/sciencedirect-live-session-fetcher/tree/main/skills/aic-review-live-session-fetcher
```

安装完成后，开始一个新的 Codex 对话，然后使用：

```text
$aic-review-live-session-fetcher
```

如果还没有本地代码目录，先让 Codex 克隆仓库：

```text
请将 https://github.com/kunyaoli2023-star/sciencedirect-live-session-fetcher
克隆到本地，并在该目录中准备运行环境。
```

## 2. 准备输入 CSV

CSV 必须使用 UTF-8 编码。至少提供 `number` 和 `doi`；建议同时提供 `title`、`year`、`journal` 和 `note`。如果有 ScienceDirect 文章页 URL，可以放在 `note` 中。

可以复制并修改 [`examples/input-template.csv`](../examples/input-template.csv)：

```csv
number,title,doi,year,journal,note,formatted
1,Deep learning-based structural health monitoring,10.1016/j.autcon.2024.105328,2024,Automation in Construction,https://doi.org/10.1016/j.autcon.2024.105328,
```

`number` 应保持唯一。DOI 是去重和全文身份核验的主要依据。

## 3. 准备 Python 环境

在仓库根目录执行：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

## 4. 启动专用 Edge 浏览器

建议让 Codex 执行下面的命令：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\launch_edge_clone_remote_debug.ps1 `
  -DirectConnection `
  -DisableExtensions `
  -OneShotProfile `
  -RemoteDebuggingPort 9222 `
  -Url "https://www.sciencedirect.com/"
```

这会打开一个单独的、可见的 Edge 窗口。请在这个新窗口中手动完成：

1. 登录 ScienceDirect；
2. 如需学校 VPN、代理或机构认证，先完成认证；
3. 打开一篇代表性论文；
4. 点击一次 `View PDF`；
5. 保持这个 Edge 窗口打开。

如果学校访问必须经过代理或 VPN，去掉命令中的 `-DirectConnection`。本流程不依赖 Codex 浏览器扩展，因此遇到浏览器桥接版本不匹配、`nodePath` 或 Chrome 扩展错误时，优先使用这个专用 Edge 窗口。

## 5. 先测试一篇论文

先检查 DevTools 连接：

```powershell
.\.venv\Scripts\python.exe .\scripts\attach_sciencedirect_remote_debug.py `
  --browser edge `
  --debugger-address 127.0.0.1:9222
```

再测试一篇：

```powershell
.\.venv\Scripts\python.exe .\scripts\aic_edge_reuse_fetch.py `
  --input-csv .\data\aic_reviews.csv `
  --out-dir .\out\aic-test `
  --debug-port 9222 `
  --page-wait-seconds 8 `
  --pdf-wait-seconds 25 `
  --inter-item-sleep-seconds 0 `
  --limit 1
```

只有当结果显示 `downloaded`，并且验证信息包含 `valid_pdf`，才开始完整批次。

## 6. 批量下载

```powershell
.\.venv\Scripts\python.exe .\scripts\aic_edge_reuse_fetch.py `
  --input-csv .\data\aic_reviews.csv `
  --out-dir .\out\aic-run-001 `
  --debug-port 9222 `
  --page-wait-seconds 8 `
  --pdf-wait-seconds 25 `
  --inter-item-sleep-seconds 8
```

下载器会逐篇访问文章页，读取 ScienceDirect 官方 PDF 路由，并在同一授权浏览器会话中获取全文。必要时会使用 Edge PDF 阅读器的官方 Save 按钮作为后备路径。

## 7. 输出和验证

每次运行会生成：

- `out-dir/pdfs/`：通过验证的 PDF；
- `out-dir/devtools_results.csv`：逐篇结果、状态、路径和验证说明；
- `out-dir/summary.json`：总数、成功数和缺失数。

只有同时满足以下条件的文件才会被接受：

- 文件头是 `%PDF-`；
- 文件大小和页数正常；
- PDF 可以解析；
- DOI 或论文标题与输入记录匹配。

常见状态包括：`downloaded`、`challenge_or_login`、`access_not_in_subscription`、`pdf_bytes_failed` 和 `pdf_validation_failed`。

## 8. 断点续传和失败重试

使用相同的输入文件和输出目录重新运行即可：

```powershell
.\.venv\Scripts\python.exe .\scripts\aic_edge_reuse_fetch.py `
  --input-csv .\data\aic_reviews.csv `
  --out-dir .\out\aic-run-001 `
  --debug-port 9222 `
  --inter-item-sleep-seconds 8
```

已经通过验证的 PDF 会跳过；缺失或失败的记录会继续重试。建议保持每篇之间 5–8 秒的间隔，不要并发运行多个批次。

## 9. 常见问题

### `no reusable Edge page target found`

专用 Edge 没有启动、端口不是 `9222`，或窗口已经关闭。重新启动 Edge 克隆窗口并保持打开。

### `challenge_or_login`

在专用 Edge 窗口中重新登录 ScienceDirect，完成学校认证后再重试。不要把账号密码、Cookie 或签名 PDF URL 提供给 Codex。

### `access_not_in_subscription`

当前学校订阅不包含该论文。工具会保留失败状态，不会绕过访问限制；可以之后使用合法开放获取版本或其他合法机构权限重试。

### `pdf_navigation_failed` 或 `pdf_bytes_failed`

确认 PDF 页面仍在专用 Edge 中打开，增加等待时间后重试。Edge PDF 阅读器的官方 Save 后备路径会自动尝试。

### 浏览器桥接版本不匹配、`nodePath` 错误

这类错误来自 Codex/浏览器扩展桥接，不是论文权限本身。关闭有问题的扩展，使用本说明中的专用可见 Edge 和 `9222` 端口流程。

## 10. 发布和隐私边界

GitHub 仓库只发布代码、Skill 和公开说明。不要上传：

- 出版商 PDF 或包含 PDF 的 ZIP；
- 浏览器用户数据目录、Cookie、账号信息；
- 带签名参数的 ScienceDirect URL；
- 含个人路径、会话标识或学校内部信息的原始日志。
