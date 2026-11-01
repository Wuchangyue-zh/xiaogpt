# XiaoGPT Voice

由 **Wuchangyue-zh** 维护的小爱音箱 DeepSeek 语音助手。

在 Linux 服务器上运行，通过小米云端接收语音问题，按需联网查询，再由音箱直接播报回答。项目包含设备通信、对话引擎、语音调度、配置向导、Docker 部署和自动化测试。

## 能做什么

- “小爱同学，请问……”调用 DeepSeek，普通小爱指令继续由音箱处理。
- 按需调用 DeepSeek 官方 Search/Fetch，支持追问、来源记录和复杂问题思考。
- 每轮使用系统提示词和北京时间；普通解释约 150—300 字，可以要求详细或简短。
- 支持持续对话、新问题打断旧回答、清空上下文和自动唤醒失败冷却。
- 自动发现账号下的音箱，使用每位用户自己的账号、设备和 API Key。
- 不需要常开的家庭电脑，不发布公网入站端口。

## 准备条件

1. Linux 服务器，已安装 Git、Docker Engine 和 Docker Compose 插件；当前用户可以使用 Docker。安装说明：[Debian](https://docs.docker.com/engine/install/debian/)、[Ubuntu](https://docs.docker.com/engine/install/ubuntu/)。
2. 音箱已经绑定小米账号，知道账号密码并能接收登录验证码。
3. 自己的 [DeepSeek API Key](https://platform.deepseek.com/api_keys) 和可用余额，服务器能访问小米、DeepSeek、Docker Hub 和 Python 包源。

目前自动配置支持小米 AI 音箱 `S12A` / `S12`，主要设备验证基于 S12A。其他型号需要确认自己的文本播报和唤醒动作编号后手动配置，不保证所有固件通用。

## 部署

在交互式 SSH 终端执行：

```bash
git clone https://github.com/Wuchangyue-zh/xiaogpt.git
cd xiaogpt
bash setup.sh
```

脚本会从源码构建镜像，首次运行时依次引导登录小米、选择音箱、输入 DeepSeek Key、验证真实联网，然后保存配置并启动。

密码、验证码和 Key 输入时不回显。初始化需要真实交互终端，请直接运行 `bash setup.sh`；不要放进 `bash <<'BASH'` 或无 TTY 的管道。一台音箱同一时间运行一个服务实例。

也可以分步执行：

```bash
docker compose build speaker
docker compose run --rm --no-deps -i speaker init
docker compose up -d --no-build speaker
```

首次测试会消耗少量 DeepSeek 余额。登录或联网验证失败时，不保存可启动的运行配置；修复账号、余额或网络后重新运行初始化即可。

## 日常使用

> 小爱同学，请问联网查一下 DeepSeek 目前有哪些官方模型？
>
> 小爱同学，请问那价格呢？
>
> 小爱同学，请问深入分析，云服务器和家里小主机怎么选？
>
> 小爱同学，请问清空对话。

进入连续对话：“小爱同学，开始持续对话。”

退出连续对话：“结束持续对话。”也支持“开始连续对话”和“结束连续对话”。等待音箱进入收听状态后再继续提问。

云端获取问题存在延迟，原回答可能漏出开头几个字。项目通过无声指令尽快打断，不修改音箱固件。联网和复杂思考也会增加回答等待时间。

## 日志与本地检查

在仓库目录执行：

```bash
docker compose ps
docker compose logs --since=10m --tail=200 speaker
docker compose logs -f --tail=80 speaker
```

按 Ctrl+C 退出日志查看，不会停止服务。日志包括用户问题、助手回答、联网来源条数和唤醒状态，不打印密钥或登录令牌。

检查配置、缓存文件和当前时间，不调用收费接口：

```bash
docker compose run --rm --no-deps -T speaker doctor
```

`doctor` 只检查本地状态，不保证登录缓存仍被云端接受。

## 配置和提示词

个人数据只在本机 `data/`，已从 Git 和 Docker 构建中排除：

```text
data/
├── config.json              # 账号 ID、设备和 DeepSeek Key
├── .mi.token                # 小米登录缓存
├── backups/                 # 重配前的备份
└── voice/
    ├── assistant.json       # 模型、思考、搜索和上下文参数
    ├── system_prompt.txt    # 系统提示词
    └── last_sources.json    # 最近一次检索来源
```

小米密码和验证码不写入配置。账号、密钥和登录令牌属于个人数据，不要提交到公开仓库或整份贴到聊天。

修改 `data/voice/system_prompt.txt` 可以调整语气、解释深度和回答风格。修改 `data/voice/assistant.json` 可以调整：

- `model`：默认 `deepseek-flash`。
- `thinking`：`adaptive` 自动选择；也可选 `disabled`、`low`、`high`。
- `home_city`：可留空，缺少城市的天气问题会澄清。
- `history_turns`：默认保留最近 10 轮；空闲 30 分钟或重启后清空内存上下文。
- `max_searches`：每轮最多 2 条查询；详细问题最多再抓取一个网页。
- `max_answer_tokens`：普通回答默认 2048；`max_thinking_tokens` 默认 8192。

修改后执行 `docker compose restart speaker`。更新代码不会覆盖你已经编辑的提示词。

运行配置使用明确的设备动作：`device.text_action` 和 `device.wake_action`。S12A 默认分别为 `[5, 1]` 和 `[5, 3]`；其他型号需根据实际 MIoT 规格填写。配置格式见 [config.example.json](config.example.json)。

## 更新与重配

更新并重新构建：

```bash
git pull --ff-only origin main
bash setup.sh
```

更换音箱或 DeepSeek Key：

```bash
docker compose stop speaker
docker compose run --rm --no-deps -i speaker init --replace
docker compose up -d --no-build speaker
```

小米缓存失效时，重新登录：

```bash
docker compose stop speaker
docker compose run --rm --no-deps -i speaker init --replace --login-again
docker compose up -d --no-build speaker
```

重配会备份已有配置；重新登录会先备份旧登录缓存。停止服务使用 `docker compose stop speaker`。`docker compose down` 也会保留宿主机 `data/`。

## 项目结构

```text
xiaogpt_voice/
├── app.py          # 语音状态、连续对话与打断调度
├── xiaomi.py       # 小米登录、云端对话、播报与唤醒
├── llm.py          # DeepSeek、检索、思考和上下文
├── config.py       # 配置校验与本地存储
├── setup.py        # 首次配置向导
├── cli.py          # init / run / doctor 命令
└── defaults/       # 默认提示词和模型参数
tests/              # 离线协议、配置、调度与取消测试
```

Python 用户也可以安装并运行同一套命令：

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install --no-deps .
xiaogpt-voice init
xiaogpt-voice run
```

## 费用与验证

模型规划、回答、思考和成功的 Search/Fetch 使用自己的 DeepSeek 余额，价格以 [官方说明](https://api-docs.deepseek.com/zh-cn/quick_start/pricing/) 为准。

自动化测试覆盖联网协议、来源记录、上下文、配置向导、令牌刷新、连续对话和新问题取消旧回答。干净 Linux CI 会从源码构建镜像，并验证包安装和命令行入口。

离线测试不代替每个账号地区、设备固件和真实听感的验收。对话内容和联网结果也需要结合来源判断。

## 许可证

本项目以 MIT 许可证发布，版权及第三方许可见 [LICENSE](LICENSE) 和 [LICENSES](LICENSES)。
