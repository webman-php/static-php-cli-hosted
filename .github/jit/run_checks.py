#!/usr/bin/env python3
"""Run the same hot-code and coroutine checks with JIT off and tracing on."""
import argparse
import json
from pathlib import Path
import subprocess


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--php", default="php")
    p.add_argument("--swoole")
    p.add_argument("--expect-jit", choices=["yes", "no"], required=True)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    command = [args.php, "-n"]
    loaded = subprocess.run(command + ["-r", "exit(extension_loaded('Zend OPcache') ? 0 : 1);"], capture_output=True)
    if loaded.returncode:
        directory = subprocess.check_output(["php-config", "--extension-dir"], text=True).strip()
        command += ["-d", f"zend_extension={directory}/opcache.so"]
    if args.swoole:
        command += ["-d", f"extension={Path(args.swoole).resolve()}"]
    command += ["-d", "opcache.enable_cli=1", "-d", "opcache.file_update_protection=0",
                "-d", "display_errors=1", "-d", "log_errors=0", "-d", "error_reporting=32767",
                "-d", "opcache.jit_buffer_size=64M", "-d", "opcache.jit_hot_func=2",
                "-d", "opcache.jit_hot_loop=2"]
    reports = {}
    for mode in ("disable", "tracing", "function"):
        result = subprocess.run(command + ["-d", f"opcache.jit={mode}", str(Path(__file__).with_name("probe.php"))], capture_output=True, text=True, timeout=45)
        print(f"--- JIT {mode}, exit {result.returncode} ---\n{result.stdout}{result.stderr}", flush=True)
        if result.returncode:
            raise RuntimeError(f"JIT {mode} process failed ({result.returncode})")
        lines = [line.removeprefix("JIT_REPORT:") for line in result.stdout.splitlines() if line.startswith("JIT_REPORT:")]
        if len(lines) != 1:
            raise RuntimeError("Missing runtime report")
        report = json.loads(lines[0])
        expect = mode != "disable" and args.expect_jit == "yes"
        if bool(report["after"]["on"]) != expect:
            raise RuntimeError(f"Unexpected JIT state: {report}")
        if expect and report["machine_code_bytes"] <= 0:
            raise RuntimeError("JIT enabled but generated no machine code")
        if expect and ("Warning" in result.stdout or result.stderr):
            raise RuntimeError("Unexpected warning with JIT enabled")
        reports[mode] = report
    for mode in ("tracing", "function"):
        if reports["disable"]["integer_result"] != reports[mode]["integer_result"] or abs(reports["disable"]["float_result"] - reports[mode]["float_result"]) > 1e-7:
            raise RuntimeError(f"JIT {mode} numeric results differ")
    plain = subprocess.run(command + ["-d", "opcache.jit=tracing", "-r", "exit(23);"], capture_output=True, text=True, timeout=10)
    if plain.returncode != 23:
        raise RuntimeError(f"Plain CLI exit status changed: {plain.returncode}")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(reports, indent=2) + "\n")
    print("PASS: numeric JIT, channels, exceptions, silence, TCP, coroutine exit, CLI exit")


if __name__ == "__main__":
    main()
