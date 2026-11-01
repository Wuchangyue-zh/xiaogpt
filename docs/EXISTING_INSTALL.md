# 小米 AI 音箱 S12A：DeepSeek 联网与语音对话增强版

为已经部署的 XiaoGPT Docker 服务制作，版本 1，日期 2026-11-01。本仓库以固定的上游 XiaoGPT Docker 镜像为运行基础，提供可回退的联网、提示词和语音交互扩展。源码都在此目录，没有包含任何真实账号、密码、登录令牌或 API Key。

仓库地址：[Wuchangyue-zh/xiaogpt](https://github.com/Wuchangyue-zh/xiaogpt)。

## 改了什么

- 正式系统提示词：每轮作为 `role=system` 发送，不再把设定拼到第一句用户问题后面。
- 回答长度按问题调整：普通解释约 150—300 字，简单事实一两句话，要求详细时约 300—600 字。这些是提示词指引，不是强制凑字数。
- 按需联网：模型结合当前问题和上下文决定检索词，程序真正调用 DeepSeek 官方 Search API；需要详细资料时最多再抓取一个网页。可以直接说“联网查一下”。
- 思考模式：默认保持 `deepseek-flash`；简单问题关闭思考，多条件问题选择 low/high，也可用“深入分析……”明确启用 high。只播报答案，不播报内部思考。
- 追问上下文：内存保留最近 10 轮，受总字数和 30 分钟空闲时间限制；不建设数据库、不保存长期个人记忆，重启会清空。
- 当前时间：每轮注入服务器时钟对应的北京时间；常见日期时间问题直接计算，避免模型凭记忆猜日期。服务器自身时钟仍需正确。
- 联网失败、余额不足或没有可用结果时，明确说无法确认，不退回训练记忆编造“最新消息”。
- 来源留在 `/opt/xiaogpt/config/smart_voice/last_sources.json`；音箱按提示自然说出来源名称，长链接不播读。该文件是最近一次检索，不是完整日志库。
- 包含前面已验证的 S12A 无声打断和取消等待提示。保留 MiIO User-Agent 修复、Python 3.14 启动修复、5-3 自动唤醒和失败冷却；新问题到达时取消旧请求和旧播报等待。

日常模型输出上限从 512 提高到 2048 tokens；思考模式给出 8192 tokens 的思考及回答空间。提示词负责组织表达，不能替代模型能力或保证每次答案都正确。复杂思考、规划和联网会增加等待时间。

## 参考了哪些实现

1. [XiaoGPT 的 ChatGPT 适配器](https://github.com/yihong0618/xiaogpt/blob/main/xiaogpt/bot/chatgptapi_bot.py)和[主循环](https://github.com/yihong0618/xiaogpt/blob/main/xiaogpt/xiaogpt.py)：沿用现有音箱收发链路，替换模型适配器和取消处理。
2. [XiaoGPT 的 LangChain 搜索适配器](https://github.com/yihong0618/xiaogpt/blob/main/xiaogpt/bot/langchain_bot.py)：参考“检索后再回答”的流程；本包改用现有 DeepSeek Key，不新增 SerpAPI 账号或 LangChain 依赖。
3. [MiGPT 系统提示词与上下文设计](https://github.com/idootop/mi-gpt/blob/main/docs/prompt.md)：参考系统设定、最近对话和人物偏好分开管理。这里只使用这些结构性思路，没有复制其角色扮演模板或长期记忆数据库。MiGPT 原仓库已归档，不要求迁移到它。
4. [DeepSeek 官方 Search/Fetch](https://api-docs.deepseek.com/zh-cn/guides/search/)、[思考模式](https://api-docs.deepseek.com/zh-cn/guides/thinking_mode/)、[模型及价格](https://api-docs.deepseek.com/zh-cn/quick_start/pricing/)：使用当前公开接口，搜索与模型共用同一 API Key。

## 适用的现有部署

- Debian 12 / Linux，已有 Docker、Docker Compose 和 `flock`。
- Compose 文件 `/opt/xiaogpt/compose.yaml`，项目 `xiaogpt-speaker`，服务 `speaker`。
- 配置目录 `/opt/xiaogpt/config`，里面已有 `config.json`、`.mi.token`、`start_compat.py`。
- 已验证的小米 AI 音箱 `S12A`，配置 `bot=chatgptapi`，DeepSeek 官方 API。
- 原镜像固定为 `yihong0618/xiaogpt@sha256:2513ebea5a74b4c1e2fc5374ebbd8d05601dded39b23c3c3d7387bd7cbaf26c8`。

安装不拉取新镜像、不安装系统依赖、不占用公网端口、不调整 OpenClaw/FastGPT 等其他项目。只重启音箱服务。

## 安装

已有上面所述部署时，可以直接在服务器从本仓库下载安装，不需要先在电脑上传文件：

```bash
curl -fL --connect-timeout 10 --max-time 120 \
  https://github.com/Wuchangyue-zh/xiaogpt/archive/refs/heads/main.tar.gz \
  -o /tmp/xiaogpt-smart-voice-github.tar.gz

mkdir -p /opt/xiaogpt-upgrade/xiaogpt-smart-voice
tar -xzf /tmp/xiaogpt-smart-voice-github.tar.gz \
  -C /opt/xiaogpt-upgrade/xiaogpt-smart-voice --strip-components=1

bash /opt/xiaogpt-upgrade/xiaogpt-smart-voice/install.sh
```

也可以下载之前提供的独立安装压缩包，用 SSH 工具上传到服务器 `/tmp/xiaogpt-smart-voice-v1.tar.gz` 后执行：

```bash
mkdir -p /opt/xiaogpt-upgrade
tar -xzf /tmp/xiaogpt-smart-voice-v1.tar.gz -C /opt/xiaogpt-upgrade
bash /opt/xiaogpt-upgrade/xiaogpt-smart-voice/install.sh
```

脚本会先在临时目录使用现有 Key 做一次真实的“规划—搜索—回答”测试。API 余额会按实际使用扣费；测试不向音箱播报。失败时不会切换现有配置。成功后验证启动器、备份、安装、重启。暂存目录会留在配置目录中，便于失败排查。

再次运行时保留你已经编辑过的 `voice_prompt.txt` 和 `smart_voice.json`。配置文件与备份均设置限制性权限；不会复制或修改 `.mi.token`。

备份位于 `/opt/xiaogpt/config/smart_voice_backups/`，其中 config.json 含原有密钥，请留在服务器，不要整份贴到聊天。

## 音箱验收

普通提问：

- “小爱同学，请问天空为什么是蓝色的？举个例子。”
- “小爱同学，请问联网查一下 DeepSeek 目前有哪些官方模型？”
- “小爱同学，请问那价格呢？”（接着上一问，确认能理解指代）
- “小爱同学，请问深入分析，家里用云服务器接音箱和在家里放小主机，各有什么取舍？”
- “小爱同学，请问简短点。”
- “小爱同学，请问现在几点？”
- “小爱同学，请问清空对话。”

连续对话仍用“开始持续对话”和“结束持续对话”。不在连续模式时，后续问题仍需“小爱同学，请问……”唤醒。原厂的云端轮询延迟还存在，可能漏出原回答开头几个字；本包不修改音箱固件。

查看运行状态与最近日志：

```bash
docker inspect xiaogpt-speaker-speaker-1 --format 'Status={{.State.Status}} Restarts={{.RestartCount}}'
docker compose -p xiaogpt-speaker -f /opt/xiaogpt/compose.yaml logs --since=5m --tail=100
```

联网时应出现“联网检索：ok”和来源条数；回答前会记录模式 none/low/high。源回答文本仍可能出现在原项目日志中，是否有抢话以听感为准。

查看最近一次检索的来源：

```bash
docker compose -p xiaogpt-speaker -f /opt/xiaogpt/compose.yaml exec -T speaker \
  pdm run python -m json.tool /config/smart_voice/last_sources.json
```

## 调整提示词和参数

系统提示词：`/opt/xiaogpt/config/smart_voice/voice_prompt.txt`。

参数文件：`/opt/xiaogpt/config/smart_voice/smart_voice.json`。

- `home_city` 默认空字符串；只有你明确填写后才当作常住城市。未填写时，缺少城市的天气问题会提示追问。
- `thinking`: `adaptive` 默认自动选择；`disabled` 全部关闭；`low` 或 `high` 全部启用相应强度。
- `model` 默认 `deepseek-flash`，对应官方当前 Flash 别名。想试 Pro 可自行改为官方支持的 `deepseek-v4-pro`，费用不同。
- `max_answer_tokens` 默认 2048；`max_thinking_tokens` 默认 8192，包含思考和最终输出。
- `max_searches` 最多 2；`search_count` 默认每次 5 条；`fetch_for_detail=false` 可关闭自动抓取详细页面。
- `max_spoken_chars` 默认约 1600 字的长回复保护，通常提示词会让回答远短于该上限；它不是日常回答目标。
- `history_turns` 最近轮数；`history_idle_minutes` 空闲后清空时间。语音“清空对话”也可清空。

修改文件后重启：

```bash
docker compose -p xiaogpt-speaker -f /opt/xiaogpt/compose.yaml restart speaker
```

每轮最多安排两条检索词、一次抓取；临时网络错误、408、429、5xx 最多重试一次。401/402 等错误不盲目重试。搜索结果有时效限制，天气等网页搜索不等于专门的实时数据接口。

## 费用

按 2026-11-01 官方人民币价，Search 和 Fetch 分别每千次成功请求 5 元，普通一次搜索约 0.005 元。若一问两次搜索再抓一次页面，正常成功调用的检索费用约 0.015 元，另计规划、上下文、回答和思考的模型 token 费用。失败、空结果和超时不按成功搜索计费；具体账单以官方平台为准。

## 回退

```bash
bash /opt/xiaogpt-upgrade/xiaogpt-smart-voice/install.sh --rollback
```

恢复最近一次安装前的启动器、配置和已有增强模块版本，然后重启音箱服务。第一次安装前没有增强模块时，回退后增强目录会留在磁盘上，但原启动器不会再加载它。不会修改其他容器。

## 测试边界

本包附带基于真实 OpenAI 兼容 SDK 和 HTTPX MockTransport 的协议测试，以及安装失败回退、来源记录、上下文、取消和播报等待测试。它们不使用真实密钥，不联网，不模拟已经验证了实际音箱效果。

本地验证使用 Python 3.13；服务器安装时还会在你固定的 Python 3.14 镜像中做导入、启动器预检和真实联网测试。最终听感需用你的 S12A 验收。

在具备 `openai`、`httpx` 的环境中运行离线测试：

```bash
python -m unittest -v test_smart_voice
```
