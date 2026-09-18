# 本 fork 的部署方式

GitHub Actions 运行 `folder_reader.py`，每次打开指定微信读书文件夹，读取其中最新的书单。使用真实网页阅读器翻页，不再调用上游 `main.py` 中的随机书籍/章节模板。

## 日常使用

在微信读书 App 中把需要自动阅读的书移入「在读列表」，移出即停止将该书纳入后续任务。下次运行自动获取最新内容，不需要重新部署。每天按北京时间日期在书单中轮换选一本；书单变化会改变轮换顺序。同一天重复运行通常选同一本。

标题包含「三体」「三體」或「Three-Body / Three Body」的书始终排除。文件夹不存在、为空、登录失效、阅读请求失败或无法继续翻页时会停止，不使用其他文件夹或默认书籍补位。

## GitHub 配置

Settings → Secrets and variables → Actions：

- Secret `WXREAD_CURL_BASH`：本人登录后的阅读请求，Copy as cURL (bash)。不要提交到代码仓库。
- Variable `READ_FOLDER_URL`：目标文件夹的完整网页地址，如 `https://weread.qq.com/web/shelf/archive/123`。
- Variable `READ_FOLDER_NAME`：用于确认目标文件夹的名称。
- Variable `READ_NUM`：默认 `40`，约 20 分钟。每单位等待 30 秒并翻页，页面加载另计；支持 1–100。

工作流每天 17:07 UTC（次日北京时间 01:07）执行。手动 Run workflow 可以设置 `read_num=2` 做约一分钟的验证，不修改每日默认时长。浏览器在 GitHub runner 上运行，本机无需开机。

实际读数由微信读书服务决定。日志统计成功的 `read` 响应和请求中报告的秒数，并不能单独证明排行榜或挑战赛已计入对应时长。日志不打印 Cookie、书名、页面截图或书架内容。登录失效后重新捕获请求并更新 Secret；没有承诺登录永久有效。

本文件夹模式不发送上游的第三方推送通知。上游 `main.py` / Docker 部署仍保留原有行为，不适用上述文件夹限制；请使用本 fork 的 Actions 工作流。

## 验证

```sh
python -m unittest discover -s tests -v
```

Actions 会安装固定版本 Playwright 和对应 Chromium。失败时保持失败状态，不伪报完成。
