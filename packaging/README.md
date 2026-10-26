# Windows 安装包构建

当前版本：拾序 1.0.0。保持 preview.10 业务功能，使用 Python/FastAPI/pywebview 与 Inno Setup。

## 构建环境

- Windows 10/11 x64、64 位 Python 3.12。
- 在 `.venv` 中安装 requirements.txt、requirements-desktop.txt、requirements-wechat.txt 的固定版本。
- 从 https://jrsoftware.org/isdl.php 安装 Inno Setup；本次使用 6.7.3。源码不附带编译器。
- 从 https://github.com/NapNeko/NapCatQQ/releases/tag/v4.18.38 下载官方 `NapCat.Shell.zip`，放在 `runtime/napcat-vendor/NapCat.Shell.zip`。
- 固定压缩包 SHA256：`735f2e633247df3ffd6e8ee8b84d7039c315b2655f5807e5f0029f93d2c30016`。打包脚本会核对哈希并拒绝其他版本及可疑路径，不使用已登录的 NapCat 目录。

## 构建命令

在仓库根目录运行，stage 必须是未创建的新目录：

```powershell
..venvScriptspython.exe -B packaging/build_payload.py --stage runtime/package-build/v1-clean --napcat-shell runtime/napcat-vendor/NapCat.Shell.zip
$payload = (Resolve-Path runtime/package-build/v1-clean).Path
$output = Join-Path $PWD 'releases'
& 'C:Program Files (x86)Inno Setup 6ISCC.exe' "/DPayload=$payload" "/DOutput=$output" packaging/Shixu.iss
Get-FileHash releases/Shixu-1.0.0-win-x64-Setup.exe -Algorithm SHA256
```

编译器路径请按实际安装位置调整。不要在 stage 中运行应用，避免污染发布文件。版本调整需同步 app/main.py、packaging/build_payload.py、packaging/Shixu.iss 与 FIRST-RUN.txt。

## 发布内容

build_payload.py 只复制应用、指定脚本、图标、固定微信模块、运行时依赖和经过哈希校验的未修改 NapCat 发行组件。源码目录中的 data、runtime、*.local.json、虚拟环境、模型、QQ/微信客户端不进入包。release-manifest.json 记录版本、文件哈希和依赖；哈希不是数字签名，也不保证逐字节可重现构建。

Inno 安装器允许选择路径，以当前用户权限运行，无需管理员权限。安装后不直接启动应用；请关闭安装器，从桌面或开始菜单打开。升级使用新包自带的只读运行检查，检查码 10 为运行中，20 为无法确认；不强制杀进程或关闭系统安全保护。卸载保留生成的数据和配置。

## 验证

先执行 `..venvScriptspython.exe -m pytest -q`。安装验证必须使用无现有已注册安装的测试环境、独立目录和合成数据，检查新安装、启动与退出、接收过滤、重启保存、覆盖升级及卸载保留数据。不要在自己的真实数据库上执行清理或卸载测试。

源码清理导出命令：

```powershell
..venvScriptspython.exe -B scripts/prepare_github_release.py --destination releases/github-v1.0.0/Shixu
```

导出拒绝覆盖目录；只使用明确清单，不复制旧 Git 历史。导出仍需人工检查，不是安全或许可合规保证。源码和安装包分别发布：源码进入仓库，安装包及 SHA256 进入 GitHub Releases。
