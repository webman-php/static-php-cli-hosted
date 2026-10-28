#!/usr/bin/env python3
"""Collect a backtrace and isolate static PHP 8.5 tracing failures."""
import os
from pathlib import Path
import subprocess

binary = str(Path('candidate/buildroot/bin/php').resolve())
Path(binary).chmod(0o755)
results = Path('diagnostics')
results.mkdir(exist_ok=True)
general = subprocess.check_output([binary, '-n', '-r', 'phpinfo(INFO_GENERAL);'], text=True)
print('\n'.join(s for s in general.splitlines() if any(k in s for k in ('Configure Command', 'Zend VM', 'Compiler', 'Architecture'))), flush=True)
vm = subprocess.run(['gdb', '-q', '-batch', '-ex', 'disassemble zend_vm_kind', '-ex', 'disassemble zend_gcc_global_regs', binary], capture_output=True, text=True, timeout=20)
print(vm.stdout + vm.stderr, flush=True)
base = [binary, '-n', '-d', 'opcache.enable_cli=1', '-d', 'opcache.file_update_protection=0',
        '-d', 'opcache.jit_buffer_size=64M', '-d', 'opcache.jit_hot_func=2', '-d', 'opcache.jit_hot_loop=2',
        '-d', 'display_errors=1', '-d', 'log_errors=0']
for fixture in ('repro-php85-jit.php', 'probe.php'):
    for mode in ('disable', 'tracing', 'function'):
        cmd = base + ['-d', f'opcache.jit={mode}', str(Path(__file__).with_name(fixture).resolve())]
        try:
            run = subprocess.run(cmd, capture_output=True, text=True, timeout=12)
        except subprocess.TimeoutExpired as error:
            print(f'TIMEOUT {fixture} {mode}', flush=True)
            continue
        label = f'{fixture}-{mode}'
        output = f'Exit {run.returncode}\n{run.stdout}{run.stderr}'
        (results / f'{label}.log').write_text(output)
        print(label, output, flush=True)
        if run.returncode < 0:
            dbg = subprocess.run(['gdb', '-q', '-batch', '-ex', 'set pagination off', '-ex', 'run',
                                  '-ex', 'bt', '-ex', 'x/20i $pc-24', '-ex', 'info registers',
                                  '--args'] + cmd, capture_output=True, text=True, timeout=20)
            (results / f'{label}.gdb.log').write_text(dbg.stdout + dbg.stderr)
            print((dbg.stdout + dbg.stderr)[-12000:], flush=True)
    # Markers are diagnostic only; keep the original unmodified reproducer above.
    source = Path(__file__).with_name(fixture).read_text()
    for before, label in [("$before = opcache_get_status", 'numeric-start'),
                           ("$after = opcache_get_status", 'numeric-complete'),
                           ("$events = [];", 'coroutines-start'),
                           ("$events[] = 'channel';", 'channel-complete'),
                           ("$events[] = 'exception';", 'exception-complete'),
                           ("$events[] = 'silence';", 'silence-complete'),
                           ("$events[] = 'tcp';", 'tcp-complete'),
                           ("$events[] = 'exit';", 'exit-complete')]:
        source = source.replace(before, f'fwrite(STDERR, "STAGE {label}\\n");\n' + before)
    marked = Path(__file__).with_name('marked-probe.php')
    marked.write_text(source)
    run = subprocess.run(base + ['-d', 'opcache.jit=tracing', str(marked.resolve())], capture_output=True, text=True, timeout=45)
    (results / f'{fixture}-stages.log').write_text(f'Exit {run.returncode}\n{run.stdout}{run.stderr}')
    print('STAGES', fixture, run.returncode, run.stdout, run.stderr, flush=True)
    marked.unlink()
