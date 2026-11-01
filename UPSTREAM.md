# 上游来源与修改说明

- 上游项目：[yihong0618/xiaogpt](https://github.com/yihong0618/xiaogpt)
- 本次纳入的源码版本：`4258b0b53cf6af062f1a01af993d47a161382a0f`
- 上游许可证：MIT，原始 `LICENSE` 与 `Copyright (c) 2023 yihong` 原样保留。
- 上游原始说明和 Dockerfile 放在 `docs/upstream/`。
- 上游的模型适配、语音服务、配置、工具、测试、依赖和锁文件均已纳入本仓库，不需要用户另行下载上游项目。

本项目增加了 DeepSeek Search/Fetch、系统提示词、上下文、语音打断处理、独立运行入口、首次配置向导、Compose 和从源码构建流程。上游 `xiaogpt/cli.py` 的事件循环启动改成 `asyncio.run`，兼容 Python 3.14；其他上游 Python 源码保持本次快照内容。

新的 Dockerfile 在独立 Python 虚拟环境中安装上游 `pdm.lock` 导出的冻结 `requirements.txt`，避免旧版构建工具与新版本 HTTP 依赖冲突。上游原 Dockerfile 仍保存于 `docs/upstream/Dockerfile`；已有服务的 `install.sh` 升级路径继续使用原固定镜像，不改变现有环境。

上游原始 CI/发布工作流保存于 `docs/upstream/workflows/` 供查阅；本仓库使用自己的 `.github/workflows/standalone.yml`，只构建和测试，不向上游 Docker Hub/PyPI 账号发布。

本仓库包含的新增增强代码同样按根目录 MIT License 提供。不会随源码发布真实小米账号、密码、验证码、API Key 或登录令牌；每个用户在自己的服务器上完成配置。
