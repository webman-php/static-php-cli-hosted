# static-php-cli-hosted
Self-Hosted [static-php-cli](https://github.com/crazywhalecc/static-php-cli) build action.

## Introduction

This repository is used to automatically compile static-php-cli related content for different architectures and operating systems.

## List of Actions

- [Archive download sources weekly](https://github.com/crazywhalecc/static-php-cli-hosted/blob/master/.github/workflows/download-cache.yml)
- [Build PHP - Unix](https://github.com/webman-php/static-php-cli-hosted/actions/workflows/build-php-unix.yml)
- [Build PHP - Windows](https://github.com/webman-php/static-php-cli-hosted/actions/workflows/build-php-windows.yml)
- [Extension matrix tests (8.0)](https://github.com/static-php/static-php-cli-hosted/blob/master/.github/workflows/ext-matrix-tests-php80.yml)
- [Extension matrix tests (8.4)](https://github.com/static-php/static-php-cli-hosted/blob/master/.github/workflows/ext-matrix-tests-php84.yml)
- [Build pre-built packages](https://github.com/static-php/static-php-cli-hosted/blob/master/.github/workflows/pack-libs.yml)

## workerman.net 静态 PHP 更新

实际构建入口为本仓库的 [Actions → Build Self-Hosted PHP Binary (Unix) → Run workflow](https://github.com/webman-php/static-php-cli-hosted/actions/workflows/build-php-unix.yml)。
`walkor/static-php-cli` 是旧的编译器 fork，本仓库直接检出上游 SPC v3 的固定提交（含本次 PHP 安全版本的 IMAP、Swoole、静态 libpq 兼容修复）。

各分支的完整构建版本与官方源码 SHA-256 统一保存在 [`.github/php-releases.json`](.github/php-releases.json)，由更新检查自动维护。
PHP 8.1 不再构建或列入支持列表。
所有 Unix CLI 和 micro.sfx 均不包含 intl/ICU，保留原有其余扩展；不提供 intl 变体，也不使用 UPX。
CI 直接检查未压缩文件的 ICU 数据、扩展和大小（每个可执行文件不超过 80 MiB），并实际执行 webman 的 build:bin 和打包后的 HTTP 服务。
可勾选 `validation-only`，先仅编译 PHP 8.3 Linux x86_64，比较旧版与新版的实际文件大小、同一 webman 应用的进程树 PSS 内存；此模式不会发布。

Unix 流程编译 Linux 和 macOS 的 x86_64、aarch64，共 16 个组合。
每个任务从 PHP 官方地址重新下载源码，验证官方 SHA-256；编译后核对完整版本号、关键扩展和 TCP socket 通信。
默认勾选 `include-glibc`，额外生成 glibc 2.17 兼容的 Linux x86_64/aarch64，共 24 个组合。glibc 包以 `-glibc.tar.gz` 结尾；默认下载文件仍为 musl 全静态版。
完整矩阵会从源码编译大量依赖，macOS 任务可能排队，需等待每个 job 的运行验证完成。
glibc 产物还会通过 ELF 符号检查，确认所需 glibc 不高于 2.17。
所有选定组合通过后才合并产物，调用可复用的 `Publish static PHP` workflow，使用已有 `DEPLOY_SERVER_SECRET_KEY` 上传服务器。
发布经过 `workerman.net` 连接下载机 `ubuntu@10.0.24.5`，目标固定为 `/home/www/download.workerman.net/public/php/`；不再依赖过期的 HOST、USER、PORT、TARGET secrets。
服务器在每次上传前，将原下载目录保存到公开目录之外的 `/home/www/php-release-backups/<UTC时间>-<PID>/`。备份使用硬链接，上传使用临时文件和原子替换。
部署公钥在网关上仅可连接下载机 SSH 端口，在下载机上仅可通过 rrsync 写入 PHP 下载目录，不能启动 shell 或删除文件。
SSH 主机公钥固定在 `.github/php-deploy-known-hosts`，连接配置位于 `.github/php-deploy-ssh-config`。
Actions artifacts 同时保留压缩包、SHA-256、扩展列表和版本 JSON。
上传后会通过公开下载地址再次核对每个包的校验文件与版本 JSON，避免上传目标或缓存错误导致页面仍提供旧版本。
macOS 使用 `macos` 文件名，同时提供兼容旧安装脚本的 `mac` 别名。
Linux x86_64 继续发布 `php8.x`、`php8.x.micro.sfx` 与对应 ZIP。

### 每周自动更新

[Check PHP releases weekly](https://github.com/webman-php/static-php-cli-hosted/actions/workflows/check-php-updates.yml) 在每周一北京时间 04:23（UTC 周日 20:23）检查，也可手动 Run workflow。
检查运行在 GitHub，不需要本地电脑开机。使用 PHP 官方 release JSON API，分别读取 8.2、8.3、8.4、8.5 的最新正式版及 tar.gz 的 SHA-256，不采用 RC/开发版，不自动增加新的 PHP 分支。
与下载站全部 24 个 Linux/macOS 包的实际版本比较；没有新版且包齐全时，跳过构建和上传，不产生版本提交。
有新版时自动提交版本清单，并触发包含 musl、glibc 2.17、macOS 的完整 Unix 构建、验证和发布流程；上传前仍会备份旧下载文件。
以上定时任务维护下载站的静态 PHP 包。Windows 保持手动构建；业务服务器的运行中 PHP 仍按需单独升级。
如果上次编译或发布失败，即使清单已经提交了新版本，下次仍会根据下载站实际版本重试；已有构建或发布运行中时暂缓，避免重复任务。
官方数据异常、校验和发生意外变化或检测到版本回退时，检查会失败并保留现有下载文件。

手动指定版本时，修改 `.github/php-releases.json` 的 `version`、`sha256`（来自 https://www.php.net/downloads.php），再运行 Unix 构建。Windows 也读取同一清单。
不要恢复以前仅按 `8.x` 缓存的 PHP 源码，以免把旧漏洞版本再次发布。
失败时查看对应 job 的 Download/Build 日志与 `logs-*` artifact。网络等临时错误可重新运行失败任务；修改 workflow 或编译器提交后，必须重新 Run workflow，使新提交生效。发布 job 会等待全部编译通过。

如果编译已通过、仅上传失败，可打开 [Actions → Publish static PHP → Run workflow](https://github.com/webman-php/static-php-cli-hosted/actions/workflows/deploy-php-unix.yml)，
填入原构建的 run ID 和包数量（含 glibc 为 24，否则为 16），直接重试上传，无需重新编译。产物保留 30 天。
部署公钥可在 Configure restricted SSH deployment 步骤查看；服务器授权接收器源码位于 `.github/scripts/receive-static-php-rsync.py`。

上线后检查 https://download.workerman.net/php/list 与 https://www.workerman.net/download，
并在对应系统解压运行 `./php -n -v`、`./php -n -m`。
站点安装脚本来自 `webman-php/workerman.net` 的 `app/controller/Download.php`。

编译器固定 libevent 2.1.13-stable（含 2026-07 安全修复）与 event 3.1.6，避免自动选择标记不准确的 libevent alpha 版。
event 使用上游 Bitbucket 的 3.1.6 源码并验证 SHA-256；PECL 多版本目录压缩包会破坏 PHP 静态构建的扩展头文件生成。
