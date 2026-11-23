# PHP 8.6 构建说明

PHP 8.6 使用 event 3.2.0，省略 Swoole 及其协程数据库钩子。CLI 与 micro 均编入原生 PDO MySQL、PostgreSQL 和 SQLite 驱动。

glibc 2.17 兼容包使用 PHP 自带的 `epoll_wait` 路径，构建时关闭 `epoll_pwait2` 的函数与声明探测结果。

APCu、Redis、igbinary、msgpack 和 xlswriter 保留各自的发布版本。兼容补丁来自 [Remi 的扩展构建](https://github.com/remicollet/remirepo/issues/342)及 [xlswriter 上游](https://github.com/viest/php-ext-xlswriter/pull/591)。

本目录在 master 的变更会触发 PHP 8.6 的六平台构建、验证与发布。
