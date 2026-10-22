# static-php-cli-hosted
Self-Hosted [static-php-cli](https://github.com/crazywhalecc/static-php-cli) build action.

## Introduction

This repository is used to automatically compile static-php-cli related content for different architectures and operating systems.

## List of Actions

- [Archive download sources weekly](https://github.com/crazywhalecc/static-php-cli-hosted/blob/master/.github/workflows/download-cache.yml)
- [Build PHP - Unix](https://github.com/crazywhalecc/static-php-cli-hosted/blob/master/.github/workflows/build-php-unix.yml)
- [Build PHP - Windows](https://github.com/crazywhalecc/static-php-cli-hosted/blob/master/.github/workflows/build-php-windows.yml)
- [Extension matrix tests (8.0)](https://github.com/static-php/static-php-cli-hosted/blob/master/.github/workflows/ext-matrix-tests-php80.yml)
- [Extension matrix tests (8.4)](https://github.com/static-php/static-php-cli-hosted/blob/master/.github/workflows/ext-matrix-tests-php84.yml)
- [Build pre-built packages](https://github.com/static-php/static-php-cli-hosted/blob/master/.github/workflows/pack-libs.yml)

## workerman.net 静态 PHP 更新

实际构建入口为本仓库的 **Actions → Build Self-Hosted PHP Binary (Unix) → Run workflow**。
`walkor/static-php-cli` 是旧的编译器 fork，本仓库直接检出上游 SPC v3 的固定提交（含本次 PHP 安全版本的 IMAP、Swoole、静态 libpq 兼容修复）。

当前发布版本：PHP 8.2.35、8.3.36、8.4.27、8.5.12，均包含 2026-10-21 的安全修复。
PHP 8.1 不再构建或列入支持列表。

Unix 流程编译 Linux 和 macOS 的 x86_64、aarch64，共 16 个组合。
每个任务从 PHP 官方地址重新下载源码，验证官方 SHA-256；编译后核对完整版本号、关键扩展和 TCP socket 通信。
默认勾选 `include-glibc`，额外生成 glibc 2.17 兼容的 Linux x86_64/aarch64，共 24 个组合。glibc 包以 `-glibc.tar.gz` 结尾；默认下载文件仍为 musl 全静态版。
glibc 产物还会通过 ELF 符号检查，确认所需 glibc 不高于 2.17。
所有选定组合通过后才合并产物，使用已有 `DEPLOY_SERVER_*` secrets 上传服务器；替换的文件备份到目标目录旁的 `php-backups/run-<run_id>/`。
Actions artifacts 同时保留压缩包、SHA-256、扩展列表和版本 JSON。
macOS 使用 `macos` 文件名，同时提供兼容旧安装脚本的 `mac` 别名。
Linux x86_64 继续发布 `php8.x`、`php8.x.micro.sfx` 与对应 ZIP。

下次安全更新时，修改 Unix workflow 中每个分支的 `version`、`sha256`（来自 https://www.php.net/downloads.php），
以及 Windows workflow 的 `PHP_RELEASE` 映射，再执行 Run workflow。
不要恢复以前仅按 `8.x` 缓存的 PHP 源码，以免把旧漏洞版本再次发布。
失败时查看对应 job 的 Download/Build 日志，修复后重新运行失败任务；发布 job 会等待全部编译通过。

上线后检查 https://download.workerman.net/php/list 与 https://www.workerman.net/download，
并在对应系统解压运行 `./php -n -v`、`./php -n -m`。
站点安装脚本来自 `webman-php/workerman.net` 的 `app/controller/Download.php`。

编译器固定 libevent 2.1.13-stable（含 2026-07 安全修复）与 event 3.1.6，避免自动选择标记不准确的 libevent alpha 版。
