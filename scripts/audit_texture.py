"""Download the mandatory Starfield texture companion with bounded range requests."""
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
from pathlib import Path
import subprocess
import urllib.request

root=Path(__file__).resolve().parents[1]
item=next(i for i in json.loads((root/'research/items.json').read_text(encoding='utf8')) if i['slug']=='starfield')
folder=root/'research/starfield-textures';folder.mkdir(exist_ok=True)
target=folder/'payload.rar';size=item['additionalFileSize'];url=item['additionalFileUrl']


def piece(n):
    start=size*n//8;end=size*(n+1)//8-1
    marker=folder/f'part-{n}.ok'
    if marker.exists():
        return n
    req=urllib.request.Request(url,headers={'Range':f'bytes={start}-{end}'})
    with urllib.request.urlopen(req,timeout=90) as r,open(target,'r+b') as f:
        if r.status!=206 or r.headers.get('Content-Range')!=f'bytes {start}-{end}/{size}':
            raise ValueError('Unexpected range response')
        f.seek(start);total=0
        while b:=r.read(1024*1024):
            total+=len(b)
            if total>end-start+1:
                raise ValueError('Range overflow')
            f.write(b)
        if total!=end-start+1:
            raise ValueError('Incomplete range')
    marker.write_text('ok')
    return n


if not target.exists():
    with open(target,'wb') as f:
        f.truncate(size)
print('Starfield textures:',round(size/1e9,2),'GB',flush=True)
with ThreadPoolExecutor(max_workers=8) as pool:
    for job in as_completed([pool.submit(piece,n) for n in range(8)]):
        print('Texture part',job.result()+1,'/ 8 OK',flush=True)
sha=hashlib.file_digest(open(target,'rb'),'sha256').hexdigest()
result=subprocess.run(['C:/Program Files/Bandizip/bz.exe','l',str(target)],capture_output=True,check=True)
(folder/'listing.txt').write_text(result.stdout.decode('utf8',errors='replace'),encoding='utf8')
(folder/'archive.json').write_text(json.dumps({'sha256':sha,'size':size,'url':url},indent=2),encoding='utf8')
print('Texture archive verified:',sha,flush=True)
