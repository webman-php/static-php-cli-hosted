#!/usr/bin/python3
"""Forced SSH command: snapshot PHP downloads and receive files through rrsync."""
import datetime
import os
from pathlib import Path
import shlex
import subprocess
import sys

PUBLIC = Path('/home/www/download.workerman.net/public/php')
BACKUPS = Path('/home/www/php-release-backups')
COMMAND = '/usr/local/libexec/receive-static-php-rsync'

args = sys.argv[1:]
if len(args) == 1:
    command = shlex.split(args[0])
    if not command or command.pop(0) not in ('rsync', COMMAND):
        sys.exit('Only PHP rsync uploads are permitted')
    args = command
if not args or args[0] != '--server' or '--sender' in args:
    sys.exit('Only PHP rsync uploads are permitted')
if any(arg.startswith(('--inplace', '--append')) for arg in args):
    sys.exit('Uploads must preserve existing backup inodes')
if len(args) < 3 or args[-2:] != ['.', './']:
    sys.exit('Upload destination must be ./')
os.environ['SSH_ORIGINAL_COMMAND'] = shlex.join(['rsync', *args])
stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
backup = BACKUPS / (stamp + '-' + str(os.getpid()))
BACKUPS.mkdir(mode=0o700, exist_ok=True)
subprocess.run(['cp', '-al', str(PUBLIC), str(backup)], check=True)
os.execv('/usr/bin/rrsync', ['rrsync', '-wo', '-munge', '-no-del', str(PUBLIC)])
