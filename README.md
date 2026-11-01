# XiaoGPT · DeepSeek 联网语音版

把小爱音箱接入 DeepSeek，支持按需联网、上下文追问、复杂问题思考和适合音箱播报的中文回答。

本仓库包含 **完整 XiaoGPT 上游源码、依赖锁文件、Dockerfile、Compose、首次配置向导和增强代码**。新用户只需克隆本仓库，在自己的服务器上构建和配置，不需要先下载原项目或准备另一个已经运行的 XiaoGPT。

基于 [yihong0618/xiaogpt](https://github.com/yihong0618/xiaogpt)，保留 MIT 许可证及上游版权。源码来源、快照版本和修改范围见 [UPSTREAM.md](UPSTREAM.md)，原始说明见 [docs/upstream/README.md](docs/upstream/README.md)。

## 功能

- DeepSeek 官方 Search/Fetch，复用自己的 DeepSeek API Key，返回可核对的来源。
- 每轮使用正式系统提示词，注入北京时间，支持“那价格呢”等上下文追问。
- 默认使用 `deepseek-flash`，日常问题快速回答，复杂分析按需启用思考。
- 普通解释约 150—300 字；支持“详细讲讲”“举例”“简短点”，不再统一限制为 100 字。
- 最近 10 轮内存上下文、空闲过期、语音“清空对话”。不建设长期个人记忆数据库。
- S12A 原声无声打断、取消“正在问……”提示、连续对话、失败冷却和新问题取消旧回答。
- 小米密码和验证码只用于交互登录，不写入运行配置。每个用户使用自己的账号、音箱和密钥。
- 新建部署不发布入站端口，通过小米云端收取问题和使用原生 TTS 播报。

## 新用户：从零部署

准备条件：

1. Linux 服务器，已安装 Git、Docker Engine 和 Docker Compose 插件，当前用户可以运行 Docker。Docker 官方安装说明：[Debian](https://docs.docker.com/engine/install/debian/)、[Ubuntu](https://docs.docker.com/engine/install/ubuntu/)。
2. 音箱已经在小爱音箱 App 或米家绑定，知道对应小米账号及密码，能接收登录验证码。
3. 自己的 [DeepSeek API Key](https://platform.deepseek.com/api_keys)，账户有可用余额；服务器能够访问小米、DeepSeek、Docker Hub 和 Python 包下载源。

当前主要验证 Linux amd64 和小米 AI 音箱 `S12A`。上游其他型号的源码和指令映射也已保留；首次配置会识别账号下的 hardware，其他型号的连续唤醒和原声打断效果需实际验证。

在交互式 SSH 终端执行：

```bash
git clone https://github.com/Wuchangyue-zh/xiaogpt.git
cd xiaogpt
bash setup.sh
```

`setup.sh` 会：

1. 从当前仓库源码和冻结的 `requirements.txt` 构建本地镜像，依赖来自同一份 `pdm.lock`，不依赖预先部署的 XiaoGPT 服务或上游成品镜像。
2. 首次运行时提示输入自己的小米账号、密码和验证码，自动列出设备；有多台音箱时选择编号。
3. 自动填写所选设备的 hardware 和 miotDID，提示输入自己的 DeepSeek Key，可选填写常住城市。
4. 真实验证联网搜索和模型回答，成功后才保存运行配置，随后启动服务。

密码、验证码和 Key 输入时不回显。初始化需要交互终端，请直接运行 `bash setup.sh`；不要把首次配置放进 `bash <<'BASH'` 或无 TTY 的流水线中。

安装后的个人数据都在本机 `data/`，已经被 Git 和 Docker 构建排除：

```text
data/
├── config.json                 # 自己的账号 ID、设备 DID 和 DeepSeek Key
├── .mi.token                   # 自己的小米登录缓存
└── smart_voice/
    ├── voice_prompt.txt        # 可修改的系统提示词
    ├── smart_voice.json        # 模型、思考、搜索、上下文参数
    └── last_sources.json       # 最近一次联网的来源
```

不需要复制本仓库维护者的账号、设备 ID、密钥或服务器配置。示例配置 [config.example.json](config.example.json) 中凭据全部为空。

### 手动执行首次配置

如果想分步操作，等价命令是：

```bash
docker compose build speaker
docker compose run --rm --no-deps -i --entrypoint python speaker configure.py
docker compose up -d --no-build speaker
```

配置向导执行中如账号验证、余额或网络检查失败，先解决对应问题再重试；失败时不会生成可启动的 `config.json`。登录成功后的小米缓存可在下次初始化时复用。

## 已经有旧版 XiaoGPT 的用户

如果你已经按此前步骤部署在 `/opt/xiaogpt`，Compose 项目是 `xiaogpt-speaker`，**继续使用升级入口**，不需要重新登录，也不要再为同一台音箱启动另一个新实例：

```bash
git -C /opt/xiaogpt-upgrade/xiaogpt pull --ff-only origin main
bash /opt/xiaogpt-upgrade/xiaogpt/install.sh
```

`install.sh` 保留上一版兼容方式：用服务器上已固定的上游镜像执行验证，备份现有配置，再更新现有音箱服务，不调整 OpenClaw/FastGPT 等其他服务。新用户使用的是上面的 `setup.sh`，两条入口用途不同。

旧部署详细说明见 [docs/EXISTING_INSTALL.md](docs/EXISTING_INSTALL.md)。旧部署回退：

```bash
bash /opt/xiaogpt-upgrade/xiaogpt/install.sh --rollback
```

## 使用与日志

普通模式：

> 小爱同学，请问联网查一下 DeepSeek 目前有哪些官方模型？
>
> 小爱同学，请问那价格呢？
>
> 小爱同学，请问深入分析，云服务器和家里小主机各有什么取舍？
>
> 小爱同学，请问清空对话。

连续模式用“开始持续对话”进入，用“结束持续对话”退出。仍需等待音箱处于收听状态后说话。云端获取对话存在延迟，原声可能漏出开头几个字；本项目不修改音箱固件。

新部署在仓库目录内查看状态与日志：

```bash
docker compose ps
docker compose logs --since=10m --tail=200 speaker
docker compose logs -f --tail=80 speaker
```

按 Ctrl+C 退出日志查看不会停止服务。旧部署仍使用自己的项目及 Compose 路径：

```bash
docker compose -p xiaogpt-speaker -f /opt/xiaogpt/compose.yaml logs --since=10m --tail=200 speaker
```

## 参数与提示词

新部署修改 `data/smart_voice/voice_prompt.txt` 和 `data/smart_voice/smart_voice.json` 后重启：

```bash
docker compose restart speaker
```

- `thinking`: 默认 `adaptive` 自动决定，也可选 `disabled`、`low`、`high`。
- `model`: 默认 `deepseek-flash`。使用其他官方型号前请核对支持情况和价格。
- `home_city`: 默认空，不从云服务器 IP 猜测用户住址；缺少城市的天气问题应先澄清。
- `history_turns`: 默认最近 10 轮；`history_idle_minutes`: 默认空闲 30 分钟后清空。重启也会清空内存聊天。
- `max_searches`: 每轮最多 2 条查询；`fetch_for_detail`: 是否为详细问题再抓取一个页面。
- `max_answer_tokens`: 日常默认 2048；`max_thinking_tokens`: 思考模式默认 8192。

完整链接记录在 `data/smart_voice/last_sources.json`。检索失败、余额不足或无结果时会说明无法确认，不把训练记忆冒充实时查询。

## 更新、重配与停止

更新新部署：

```bash
git pull --ff-only origin main
docker compose up -d --build speaker
```

`data/` 中自己的配置、提示词、密钥和登录缓存不会放进镜像或被 Git 更新覆盖。首次配置生成的提示词是可编辑副本，更新源码不会强行覆盖你的提示词。

重新选择音箱或更换 Key：

```bash
docker compose stop speaker
docker compose run --rm --no-deps -i --entrypoint python speaker configure.py --reconfigure
docker compose up -d --no-build speaker
```

重配会在成功验证后备份旧运行配置。若小米缓存已失效而无法重新登录，可以先将 `data/.mi.token` 改名保存，再重配，向导将重新询问账号密码。

停止新部署：`docker compose stop speaker`。重新启动：`docker compose up -d speaker`。`docker compose down` 也会保留宿主机 `data/`；个人配置不要提交到公开仓库或整份发到聊天。

## 费用、依赖与测试边界

联网查询会消耗自己的 DeepSeek 余额，包括规划、回答、思考 token，以及成功的 Search/Fetch 请求。价格可能变化，请以 [官方价格](https://api-docs.deepseek.com/zh-cn/quick_start/pricing/) 和账单为准。复杂思考和联网可能增加首句等待时间。

上游所有模型、TTS、工具源码以及冻结依赖已纳入仓库，外部 Python 依赖在构建时从包源安装。当前 Docker 入口是 `runtime.py`，集中应用兼容修复和增强适配；原始上游能力仍可查阅原文档。

GitHub Actions 从干净 Linux 环境构建当前源码镜像，检查首次配置入口、上游测试及增强测试，不使用真实账号或 API Key，也不推送镜像到第三方账号。测试说明见 [VALIDATION.md](VALIDATION.md)。

离线测试不等于所有音箱型号和账号地区都已实测；实际登录验证、网络可达性、设备固件、搜索质量和听感仍需自己的设备验收。
