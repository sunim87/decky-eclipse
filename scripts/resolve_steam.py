"""Record Steam store search evidence for catalog AppIDs (developer tool)."""
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
from pathlib import Path
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
items = json.loads((ROOT/'research/items.json').read_text(encoding='utf8'))


def query(i):
    title = i['title'] if i['slug']!='optimizaciya-dlya-007-first-light' else '007 First Light'
    url = 'https://store.steampowered.com/api/storesearch/?' + urllib.parse.urlencode({'term':title,'l':'english','cc':'us'})
    try:
        with urllib.request.urlopen(url,timeout=30) as r:
            value = json.loads(r.read())
        return i['slug'], {'url':url,'items':[{'id':v['id'],'name':v['name']} for v in value.get('items',[])]}
    except Exception as e:
        return i['slug'], {'error':str(e)}


result={}
with ThreadPoolExecutor(max_workers=4) as pool:
    for future in as_completed([pool.submit(query,i) for i in items]):
        slug,value=future.result();result[slug]=value
(ROOT/'research/steam-search.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
print('Steam search evidence:',len(result),flush=True)
