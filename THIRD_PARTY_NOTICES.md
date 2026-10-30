# 第三方资源说明

本清单对应当前 1.1.0 源码、依赖锁定文件与安装包构建方式。项目原创源代码及随附文档，除另有说明外，采用 Apache-2.0，见 LICENSE.md、NOTICE 和 LICENSE_SCOPE.md。此授权不改变下列第三方许可，也不代表腾讯、模型服务商或组件作者对拾序的认可。安装包保留 Python、依赖 dist-info、微信模块及 NapCat 的许可文件；含 NapCat 的完整安装包仍受其非商业用途等限制。

| 资源 | 来源及版本 | 用途 | 许可或使用条件 |
|---|---|---|---|
| Python | https://www.python.org/ ，构建时为 64 位 Python 3.12 | 独立运行时 | Python 许可，安装包 `python/LICENSE.txt` |
| FastAPI / Pydantic | https://github.com/fastapi/fastapi 、https://github.com/pydantic/pydantic ，版本见 requirements.txt | API 与数据校验 | MIT |
| Starlette / Uvicorn / HTTPX | https://github.com/Kludex/starlette 、https://github.com/Kludex/uvicorn 、https://github.com/encode/httpx | ASGI 与 HTTP 通信 | BSD-3-Clause |
| pywebview | https://github.com/r0x0r/pywebview ，6.2.1 | Windows 桌面窗口 | BSD-3-Clause |
| pythonnet / clr-loader | https://github.com/pythonnet/pythonnet 、https://github.com/pythonnet/clr-loader | .NET 桌面桥接 | 以包内许可为准；pythonnet 元数据为 MIT |
| cryptography | https://github.com/pyca/cryptography | 本地加密数据库读取依赖 | Apache-2.0 OR BSD-3-Clause |
| python-zstandard | https://github.com/indygreg/python-zstandard | 微信数据解压 | BSD-3-Clause，底层库另保留其许可 |
| qrcode / pypng | https://github.com/lincolnloop/python-qrcode 、https://gitlab.com/drj11/pypng | 二维码图像 | BSD / MIT，以包内许可为准 |
| 微信只读数据库模块 | https://github.com/fanyuantaier/wechatauto-replica ，提交 62503d76a0db069171cb4e42e87090ad285db489 | 本机数据库适配，仅固定 db.py | Apache-2.0，原文件与许可见 third_party/wechat_db |
| NapCatQQ Shell | https://github.com/NapNeko/NapCatQQ/releases/tag/v4.18.38 | QQ 登录及 OneBot 11 群文本上报 | Limited Redistribution License，限非商业用途，保留完整许可与来源；安装包采用未修改的官方发行组件 |
| Inno Setup | https://jrsoftware.org/isinfo.php ，构建工具 6.7.3 | Windows 安装器 | 按其官方许可使用；源码快照不含编译器 |
| pytest / Playwright | https://github.com/pytest-dev/pytest 、https://github.com/microsoft/playwright | 自动化测试 | MIT / Apache-2.0；不作为应用运行依赖整体打包 |

完整 Python 依赖版本见 requirements.txt、requirements-desktop.txt、requirements-wechat.txt；安装包 release-manifest.json 记录实际复制版本和文件哈希。表中未逐项展开的传递依赖仍保留自己的许可。

QQ、微信、WebView2、.NET Framework 和 LM Studio 由用户自行取得，按各自软件条款使用，安装包不分发 QQ/微信客户端或模型权重。OpenAI、DeepSeek 是用户可选服务，遵循服务商条款并使用自己的凭证及额度；不因接入接口取得其模型权重或训练数据的权利。

界面使用系统字体栈，不包含商业字体文件；不分发真实聊天数据集或第三方音视频。项目图标为开发过程中经 AI 辅助设计并由团队选择的品牌素材；本说明不保证独占性。界面参考过 Taste Skill 等设计指导，清理后的仓库不包含下载的技能仓库。

wxauto4_plus、pywechat 等曾用于调查的完整目录不包含在公开源码或安装包中，当前微信采集不依赖它们。
