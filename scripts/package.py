"""Package runtime files only, excluding dependencies, reference mods and backups."""
import hashlib
import json
from pathlib import Path
import zipfile

root = Path(__file__).resolve().parents[1]
version = json.loads((root / 'package.json').read_text(encoding='utf8'))['version']
out = root.parent / f'Decky-Eclipse-v{version}.zip'
names = ['main.py', 'eclipse.py', 'operations.py', 'steamdata.py', 'plugin.json', 'package.json', 'catalog.json',
         'recipes.json', 'README.md', 'CHANGELOG.md', 'LICENSE', 'THIRD_PARTY_NOTICES.md']
files = [root / p for p in names] + list((root / 'dist').glob('*')) + list((root / 'bin').glob('*')) + list((root / 'docs').glob('*')) + list((root / 'certs').glob('*'))
assert (root / 'dist/index.js').is_file(), 'Build the frontend first'
with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as z:
    for p in files:
        if p.is_file():
            info = zipfile.ZipInfo('Decky Eclipse/' + p.relative_to(root).as_posix())
            info.create_system = 3
            mode = 0o100755 if p.name == '7zzs' else 0o100644
            info.external_attr = mode << 16
            z.writestr(info, p.read_bytes(), compress_type=zipfile.ZIP_DEFLATED)
sha = hashlib.sha256(out.read_bytes()).hexdigest()
out.with_suffix('.zip.sha256').write_text(f'{sha}  {out.name}\n', encoding='ascii')
print(f'{out}\nSHA256: {sha}')
