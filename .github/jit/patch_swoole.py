#!/usr/bin/env python3
"""Reproducible, test-only patches for pinned Swoole 6.2.3 sources."""
import argparse
from pathlib import Path


def replace_once(path, before, after):
    text = path.read_text()
    if text.count(before) != 1:
        raise RuntimeError(f"Unexpected source layout in {path}: {before!r}")
    path.write_text(text.replace(before, after, 1))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("--legacy-exit-hook", action="store_true")
    args = parser.parse_args()
    # Same PHP 8.5 compatibility guard used by the pinned static-php-cli builder.
    replace_once(args.source / "include/swoole_api.h", "PHP_VERSION_ID > 80500", "PHP_VERSION_ID >= 80600") if (args.source / "include/swoole_api.h").exists() and "PHP_VERSION_ID > 80500" in (args.source / "include/swoole_api.h").read_text() else None
    private = args.source / "ext-src/php_swoole_private.h"
    if private.exists() and "PHP_VERSION_ID > 80500" in private.read_text():
        replace_once(private, "PHP_VERSION_ID > 80500", "PHP_VERSION_ID >= 80600")
    if not args.legacy_exit_hook:
        return
    path = args.source / "ext-src/swoole_coroutine.cc"
    before = """#if PHP_VERSION_ID < 80400
        ori_exit_handler = zend_get_user_opcode_handler(ZEND_EXIT);
        zend_set_user_opcode_handler(ZEND_EXIT, coro_exit_handler);
#endif"""
    replace_once(path, before, before.replace("#if PHP_VERSION_ID < 80400", "#if PHP_VERSION_ID < 80400 && defined(ZTS)"))
    before = """void php_swoole_coroutine_rinit() {
    PHPCoroutine::init_main_context();"""
    after = """void php_swoole_coroutine_rinit() {
#if PHP_VERSION_ID < 80400 && !defined(ZTS)
    // Restore the pre-6.1 NTS CLI registration phase; keep ZTS unchanged.
    if (SWOOLE_G(cli)) {
        ori_exit_handler = zend_get_user_opcode_handler(ZEND_EXIT);
        zend_set_user_opcode_handler(ZEND_EXIT, coro_exit_handler);
    }
#endif
    PHPCoroutine::init_main_context();"""
    replace_once(path, before, after)


if __name__ == "__main__":
    main()
