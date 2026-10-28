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
所有 Unix CLI 和 micro.sfx 均不包含 intl/ICU，保留原有其余扩展，不提供 intl 变体。Linux CLI 和已发布的 micro.sfx 默认使用固定版本 UPX 5.2.1 `--best`，macOS 不加壳。ARM64 glibc CLI 遇到该版本 UPX 的加载器边界问题时，保留已通过原生验证的未加壳文件，并在元数据中记录原因。
CI 在加壳前直接检查 ICU 数据、扩展、实际大小（不超过 80 MiB）以及 glibc 2.17 符号基线；加壳后核对完整版本、全部扩展和 TCP 通信，并实际执行 webman 的 build:bin 和打包后的 HTTP 服务。CLI 和 micro.sfx 的加壳前后大小、SHA-256 记录在发布元数据中。
可勾选 `validation-only`，先仅编译 PHP 8.3 Linux x86_64，比较旧版与新版的实际文件大小、同一 webman 应用的进程树 PSS 内存；此模式不会发布。

Unix 流程编译 Linux 和 macOS 的 x86_64、aarch64，共 16 个组合。
每个任务从 PHP 官方地址重新下载源码，验证官方 SHA-256；编译后核对完整版本号、关键扩展和 TCP socket 通信。
默认勾选 `include-glibc`，额外生成 glibc 2.17 兼容的 Linux x86_64/aarch64，共 24 个组合。glibc 包以 `-glibc.tar.gz` 结尾；默认下载文件仍为 musl 全静态版。
完整矩阵会从源码编译大量依赖，macOS 任务可能排队，需等待每个 job 的运行验证完成。
glibc 产物还会通过 ELF 符号检查，确认所需 glibc 不高于 2.17。
所有选定组合通过后才合并产物，调用可复用的 `Publish static PHP` workflow，使用已有 `DEPLOY_SERVER_SECRET_KEY` 上传服务器。
发布经过 `workerman.net` 连接下载机 `ubuntu@10.0.24.5`，目标固定为 `/home/www/download.workerman.net/public/php/`；不再依赖过期的 HOST、USER、PORT、TARGET secrets。
服务器在每次上传前，将原下载目录保存到公开目录之外的 `/home/www/php-release-backups/<UTC时间>-<PID>/`。备份使用硬链接，发布使用私有暂存目录和原子替换，最后更新版本 JSON。
部署公钥在网关上仅可连接下载机 SSH 端口，在下载机上仅可写入 PHP 下载目录，不能启动 shell、执行上传文件或删除下载文件。正式发布由下载机经 HTTPS 拉取经过校验的 GitHub artifact，SSH 只传短效下载清单，避免跨境 SSH 大文件传输超时；保留兼容 rrsync 接口。
SSH 主机公钥固定在 `.github/php-deploy-known-hosts`，连接配置位于 `.github/php-deploy-ssh-config`。
Actions artifacts 同时保留压缩包、SHA-256、扩展列表和版本 JSON。
上传后会通过公开下载地址再次核对每个包的校验文件与版本 JSON，避免上传目标或缓存错误导致页面仍提供旧版本。
macOS 使用 `macos` 文件名，同时提供兼容旧安装脚本的 `mac` 别名。
Linux x86_64 继续发布 `php8.x`、`php8.x.micro.sfx` 与对应 ZIP。

### UPX 对比试验（2026-10-23）

使用 PHP 8.3.36 Linux x86_64 musl 无 intl 产物和 UPX 5.2.1 `--best`，试验通过后，正式 Linux 包及后续每周更新采用该配置。

| 文件 | 加壳前 | 加壳后 |
| --- | ---: | ---: |
| CLI | 63,337,528 B | 19,522,892 B |
| micro.sfx | 63,195,416 B | 19,482,480 B |
| 同一 webman 应用 | 66,809,311 B | 23,096,375 B |
| micro.sfx ZIP | 22,654,519 B | 19,109,200 B |

CLI 的版本、完整扩展列表和 UPX 完整性检查通过；micro 在加壳后按 [SPC 的补丁](https://github.com/crazywhalecc/static-php-cli/blob/84ff669ee513609bc75aa43a87e2f3a349b37109/src/Package/Target/php/unix.php#L689) 截去尾段，再附加同一份 PHAR，实际启动并验证 HTTP 响应。
在同一服务器交替运行三次，8 个业务 worker（含 master、monitor 共 10 个进程）的进程树 PSS 中位数为 66,449 → 85,469 KiB，HTTP 就绪时间中位数为 87.45 → 330.70 ms。
UPX 明显缩小磁盘文件；本次测试运行内存增加约 18.6 MiB。以上数据仅代表这个 PHP 版本、平台和测试应用。

四个正式 Linux x86_64 打包运行时均通过原生 PHP 和实际 webman HTTP 检查。下表为磁盘文件大小，MB 按 1,000,000 字节计算；webman 列使用同一示例应用：

| PHP | 原含 intl 的 micro | 去除 intl、未加壳 micro | UPX micro | UPX webman 程序 |
| --- | ---: | ---: | ---: | ---: |
| 8.2.35 | 96.86 MB | 62.13 MB | 19.41 MB | 23.02 MB |
| 8.3.36 | 97.96 MB | 63.20 MB | 19.48 MB | 23.10 MB |
| 8.4.27 | 101.03 MB | 66.25 MB | 20.31 MB | 23.92 MB |
| 8.5.12 | 108.32 MB | 70.39 MB | 20.76 MB | 24.37 MB |

如已完成无 intl 的源码构建，可使用 [Pack existing Linux PHP with UPX](https://github.com/webman-php/static-php-cli-hosted/actions/workflows/repack-php-upx.yml)，填入原构建 run ID，复用原始 Linux 产物加壳，保留 macOS 包。发布要求原构建的全部 24 个 PHP 编译任务成功，并等待原发布进程结束；原上传失败或取消时也能复用已验证的产物。随后验证并发布完整 24 个组合，避免旧发布覆盖 UPX 文件。

UPX 5.2.1 的 ARM 加载器在可执行段末页没有 8 字节跳转空间时存在内部断点。本次通过原生 gdb/strace 定位到 PHP 8.4.27 ARM64 glibc 的这个布局；该 CLI 使用 `packing=none`、`packing_reason=upx-5.2.1-arm64-hatch`，仍包含同一 PHP 安全修复且不含 intl/ICU。其它 Linux CLI 与全部四个 x86_64 打包运行时已通过 UPX 原生运行检查。后续安全版本会重新检查布局，允许加壳时自动恢复 UPX。每周检查识别这个兼容策略，避免对已正确发布的包反复编译。

### JIT 构建兼容性（2026-10-28）

正式构建显式使用 `--disable-swoole-stdext`。`stdext` 是 Swoole 的实验性功能，注册的 opcode handlers 会导致 PHP 在启动时禁用 JIT；关闭它不移除 Swoole 核心功能。PHP 8.2/8.3 的静态对照测试证明不需要额外修改协程 `exit()` 钩子。

PHP 8.5 在本次 Zig 0.17 构建中会自动选择 TAILCALL VM；关闭 stdext 后，完整静态包仍可在 JIT 与协程测试中崩溃或执行错乱。PHP 上游记录了 [TAILCALL VM 的 opcode handler 执行帧问题](https://github.com/php/php-src/issues/24081)。构建时通过 `SPC_EXTRA_PHP_VARS=php_cv_preserve_none=no` 选择传统 VM，保留 `--enable-opcache-jit`，避免更改 PHP 核心或 Swoole 的退出钩子。

构建流程检查 CLI 的 tracing/function JIT 是否实际生成机器码，并对比关闭 JIT 时的整数、浮点结果；还检查协程 channel、异常、跨 yield 的错误抑制、TCP、协程 `exit()` 和普通 CLI 退出状态。Linux 加壳后重跑 JIT 检查，PHP 8.5 还必须通过原始崩溃复现脚本。micro 保持原有 OPcache 默认关闭的配置，单独验证协程和实际 webman 打包 HTTP 服务；不能把 CLI 的 JIT 结果当成 micro 开启 OPcache/JIT 的兼容承诺。

定向隔离测试使用完整扩展列表、Linux x86_64 musl 和真正的 Windows/WSL2。关闭 stdext 需要重新编译 CLI 和 micro，不能只修改 INI 或重新 UPX。正式发布仍须等待选定平台全部构建和运行验证通过，再替换下载站包并恢复网站安装脚本的默认 JIT 配置。

验证记录：[PHP 8.2.35 / 8.3.36 / 8.4.27 的 Linux、UPX、webman 和 WSL2 测试](https://github.com/webman-php/static-php-cli-hosted/actions/runs/40705761788)，[PHP 8.5.12 传统 VM、原始崩溃样例和 WSL2 测试](https://github.com/webman-php/static-php-cli-hosted/actions/runs/40705761826)，均已通过。本轮验证未发布到下载站，ARM、macOS、glibc 组合仍须经过正式全量构建验证。

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
部署公钥可在 Configure restricted SSH deployment 步骤查看；服务器授权入口位于 `.github/scripts/receive-static-php-rsync.py`，HTTPS 接收器为 `.github/scripts/receive-static-php-pull.py`，两者安装到 `/usr/local/libexec/` 并由 root 持有。接收器仅接受 GitHub 官方 artifact 存储域名，核对整个 artifact 和每个 PHP 文件的 SHA-256、文件名、版本及扩展清单，备份后才替换公开文件；不会运行上传的代码。

上线后检查 https://download.workerman.net/php/list 与 https://www.workerman.net/download，
并在对应系统解压运行 `./php -n -v`、`./php -n -m`。
站点安装脚本来自 `webman-php/workerman.net` 的 `app/controller/Download.php`。

编译器固定 libevent 2.1.13-stable（含 2026-07 安全修复）与 event 3.1.6，避免自动选择标记不准确的 libevent alpha 版。
event 使用上游 Bitbucket 的 3.1.6 源码并验证 SHA-256；PECL 多版本目录压缩包会破坏 PHP 静态构建的扩展头文件生成。
