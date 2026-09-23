"""Scan staged or tracked text without printing any matching secret."""
import re
import subprocess
import sys
from pathlib import Path

staged='--staged' in sys.argv
cmd=['git','diff','--cached','--name-only','--diff-filter=ACM'] if staged else ['git','ls-files']
names=subprocess.check_output(cmd,text=True).splitlines()
patterns=[re.compile(rb'sk-(?:proj-)?[A-Za-z0-9_-]{30,}'),re.compile(rb'gh[pousr]_[A-Za-z0-9]{30,}'),
    re.compile(rb'github_pat_[A-Za-z0-9_]{30,}')]
bad=[]
for name in names:
    data=subprocess.check_output(['git','show',':'+name]) if staged else Path(name).read_bytes()
    if any(p.search(data) for p in patterns): bad.append(name)
if bad:
    print('Possible credentials in: '+', '.join(bad)); sys.exit(1)
print('Secret scan passed ('+str(len(names))+' files).')
