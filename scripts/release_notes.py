"""Extract one release's notes from CHANGELOG.md for GitHub Releases."""
from pathlib import Path
import re
import sys

version=sys.argv[1].removeprefix('v')
text=(Path(__file__).resolve().parents[1]/'CHANGELOG.md').read_text(encoding='utf8')
match=re.search(r'^## v'+re.escape(version)+r'\b[^\n]*\n(.*?)(?=^## |\Z)',text,re.M|re.S)
if not match:
    raise SystemExit('Missing changelog entry: '+version)
print(match.group(1).strip())
