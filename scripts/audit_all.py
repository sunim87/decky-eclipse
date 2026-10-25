"""Developer audit: preserve upstream instructions and inspect all release archives.

No archive payload is executed. Downloads stay outside the distributable runtime.
"""
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
from pathlib import Path
import re
import subprocess
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'research'
OUT.mkdir(exist_ok=True)
BZ = Path('C:/Program Files/Bandizip/bz.exe')


def fetch(url, target):
    if target.exists() and target.stat().st_size:
        return target.read_bytes()
    with urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent':'Decky-Eclipse-Audit/0.2'}), timeout=60) as r:
        raw = r.read()
    target.write_bytes(raw)
    return raw


def catalog():
    page = fetch('https://www.steamdeckbase.org/optimization', OUT / 'catalog.html').decode('utf8')
    decoder = json.JSONDecoder()
    items = {}
    for s in re.findall(r'self\.__next_f\.push\((.*?)\)</script>', page, re.S):
        v = json.loads(s)
        if len(v)<2 or not isinstance(v[1], str):
            continue
        for m in re.finditer(r'\{"id":', v[1]):
            try:
                obj, _ = decoder.raw_decode(v[1][m.start():])
                if obj.get('slug') and obj.get('modFileUrl') and obj.get('type')=='ready':
                    items[obj['slug']] = obj
            except ValueError:
                pass
    (OUT/'items.json').write_text(json.dumps(list(items.values()),ensure_ascii=False,indent=2),encoding='utf8')
    return list(items.values())


def texts(node):
    if isinstance(node,dict):
        if node.get('type')=='text':
            yield node.get('text','')
        elif node.get('type')=='hardBreak':
            yield '\n'
        for child in node.get('content',[]):
            yield from texts(child)
        if node.get('type') in ('paragraph','heading','listItem'):
            yield '\n'


def archive(item):
    slug = item['slug']
    folder = OUT / slug
    folder.mkdir(exist_ok=True)
    (folder/'instructions.txt').write_text(''.join(texts(item.get('bodyEn') or item['body'])),encoding='utf8')
    target = folder / 'payload.rar'
    for attempt in range(3):
        try:
            # Resume completed downloads; use a separate partial name until EOF.
            if not target.exists():
                partial = folder/'payload.part'
                with urllib.request.urlopen(item['modFileUrl'], timeout=60) as r, open(partial,'wb') as f:
                    expected = int(r.headers.get('Content-Length',0))
                    total = 0
                    while chunk := r.read(1024*1024):
                        total += len(chunk)
                        f.write(chunk)
                if expected and total != expected:
                    raise ValueError('Incomplete response')
                partial.replace(target)
            result = subprocess.run([str(BZ),'l',str(target)],capture_output=True)
            if result.returncode:
                raise ValueError(result.stderr.decode(errors='replace') or 'Archive listing failed')
            listing = result.stdout.decode('utf8',errors='replace')
            (folder/'listing.txt').write_text(listing,encoding='utf8')
            sha = hashlib.file_digest(open(target,'rb'),'sha256').hexdigest()
            (folder/'archive.json').write_text(json.dumps({'sha256':sha,'size':target.stat().st_size,'url':item['modFileUrl']},indent=2),encoding='utf8')
            return slug, target.stat().st_size, None
        except Exception as e:
            if attempt==2:
                return slug, 0, str(e)
            time.sleep(2)


if __name__=='__main__':
    items = catalog()
    print('Catalog:',len(items),'archives',round(sum(i.get('modFileSize') or 0 for i in items)/1e9,2),'GB',flush=True)
    with ThreadPoolExecutor(max_workers=8) as pool:
        jobs = {pool.submit(archive,i):i for i in items}
        for n, job in enumerate(as_completed(jobs),1):
            slug,size,error=job.result()
            print(f'[{n}/{len(items)}] {slug}: '+(error or f'{size/1e6:.1f} MB OK'),flush=True)
