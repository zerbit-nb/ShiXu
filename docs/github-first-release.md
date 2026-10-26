# 第一次将拾序发布到 GitHub

本文按 Windows + GitHub Desktop 说明，无需把密码、验证码或 Token 发给其他人。GitHub 仓库保存代码，Releases 保存供用户下载的安装包。创建和公开发布由你在自己账号中完成。

## 1. 找到已整理的文件

- `releases/github-v1.0.0/Shixu/`：干净源码目录。只上传这个目录，不上传整个开发目录。
- `releases/github-v1.0.0/`：安装包、校验文件、源码压缩包及本指南。除 Shixu 子目录中的源码外，发布文件放到 GitHub Release。
- `source-audit.json`、本地验证日志：本地核对使用，无需全部上传。

不会上传旧开发目录的 `.git` 历史。原开发目录、历史备份和 preview.10 安装包继续保留。源码目录不包含 `.venv`、data、runtime、*.local.json、聊天客户端、参赛文档、实验库和私有配置。

## 2. 准备 GitHub 和 Desktop

1. 在 https://github.com 注册并登录自己的账号，建议开启两步验证。
2. 从 https://desktop.github.com 安装 GitHub Desktop，用浏览器登录自己的 GitHub。
3. 在 Desktop 的 Settings / Options → Git 中设置提交显示名和邮箱。若不想公开个人邮箱，使用 GitHub Settings → Emails 中显示的 noreply 邮箱。提交作者信息会进入 Git 历史。
4. 本次已整理目录会初始化一个全新本地仓库（main 分支），不会继承旧历史。如果重新用导出脚本生成的新目录还未初始化，在该目录打开 PowerShell 执行 `git init -b main` 即可。不要在原开发目录执行清空历史操作。

## 3. 上传源码

1. Desktop 选择 File → Add local repository，选择干净的 `Shixu` 源码目录。
2. 在 Changes 中检查待提交列表：应为 app、scripts、tests、packaging、文档和 requirements 等。不能出现 config.local.json、qq.local.json、wechat.local.json、数据库、聊天、二维码、runtime、.venv、Setup.exe 或 source-audit.json。
3. Summary 填 `chore: prepare Shixu 1.0.0 release`，点击 Commit to main。先检查再提交，不要只依赖 .gitignore。
4. 点击 Publish repository，Name 建议 `Shixu`；Description 可填“拾序：多源消息驱动的智能待办管理助手”。第一次建议保留 Keep this code private，先发布为私有仓库。
5. 点击 View on GitHub，确认 README 能显示、文件完整、没有隐私内容。当前 LICENSE.md 是权利说明，不是 MIT 等开放授权；暂不在 GitHub 添加通用许可证。
6. 确认需要公开后，在仓库 Settings → General → Danger Zone → Change repository visibility 中改为 Public，按 GitHub 提示确认。公开后内容可能被复制，重新设为私有不能收回别人的副本。也可以先保持私有继续核对。

不需要先在网页创建另一个同名仓库。如果网页已创建同名仓库，先不要重复 Publish；可换一个空名称或按 GitHub Desktop 的克隆流程重新准备，避免误合并历史。

## 4. 发布 1.0.0 安装包

1. 仓库网页点击 Releases → Draft a new release / Create a new release。
2. Tag 填 `v1.0.0`，选择在发布时创建新标签，Target 选 `main`，核对该分支已包含刚才的提交。
3. Release title 填“拾序 1.0.0”。将干净源码中的 `docs/release-v1.0.0.md` 粘贴到说明框，再补上本地验证说明中的实际通过项和未验证项。
4. 拖入本次整理目录中的：
   - Shixu-1.0.0-win-x64-Setup.exe
   - SHA256SUMS.txt
   - Shixu-1.0.0-source.zip（可选，GitHub 也会自动生成标签对应的源码压缩包）
   - 使用说明.md、验证说明.md（可选，方便下载者离线查看）
5. 你已决定以 1.0 正式编号发布，因此不勾选 Set as a pre-release。先点 Save draft，检查文件、标签和说明，再点 Publish release。若页面提供 Set as latest release，可保留默认。
6. 从 Release 下载一次安装包，运行 `Get-FileHash .\Shixu-1.0.0-win-x64-Setup.exe -Algorithm SHA256`，与 SHA256SUMS.txt 比对。可在备用电脑验证，避免为了测试卸载自己的真实使用环境。

仓库网址适合分享项目代码；Release 网页适合分享给普通用户下载。自动生成的 Source code.zip 不是安装包。不要把安装包作为普通源码文件反复提交进 Git。

## 5. 后续更新

修改源码后在 Desktop 检查差异、Commit，再 Push origin。修复发布用 1.0.1，新功能用 1.1.0；同步版本与 CHANGELOG，重建并验证安装包，创建新的标签和 Release。不要用新文件悄悄替换旧标签下的发布内容。

原开发目录和本次公开快照是独立目录，导出后不会自动同步。可以将干净仓库作为后续开发起点，重新创建 .venv 并在本机配置；旧数据备份保留在原目录。若仍在原开发目录修改，请重新导出到新目录并人工核对，再同步到公开仓库，绝不要把私人数据整目录复制过去。

## 许可与反馈

公开源码不自动等于授予商用或再分发许可。内置 NapCat 限非商业用途，各第三方许可保留。若想将原创部分正式开源，需先确认团队授权，再选择合适许可，不能覆盖第三方原许可。

启用 Issues 收集问题时，要求提供拾序版本、Windows/QQ/微信版本、复现步骤和脱敏错误码；不要索取密码、令牌或完整聊天。SECURITY.md 中有隐私说明。

官方帮助：

- https://docs.github.com/en/desktop/adding-and-cloning-repositories/adding-a-repository-from-your-local-computer-to-github-desktop
- https://docs.github.com/en/desktop/adding-and-cloning-repositories/adding-an-existing-project-to-github-using-github-desktop
- https://docs.github.com/en/repositories/releasing-projects-on-github/managing-releases-in-a-repository
- https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/managing-repository-settings/setting-repository-visibility
