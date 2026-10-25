"""Offline integration audit of all real release archives in disposable Steam fixtures.

Only network transport and the native Steam launch-options acknowledgement are
substituted. Archive hashing, selective 7-Zip extraction, discovery, backup,
installation, conflict detection and file restoration use the production code.
No downloaded executable is run.
"""
import hashlib
import json
from pathlib import Path
import shutil
import sys
import time
import os

ROOT=Path(__file__).resolve().parents[1]
if os.name=='nt' and not str(ROOT).startswith('\\\\?\\'):
    ROOT=Path('\\\\?\\'+str(ROOT))  # Preserve deep shader paths on the Windows QA host.
sys.path.insert(0,str(ROOT))
from eclipse import EclipseManager, digest

recipes=json.loads((ROOT/'recipes.json').read_text(encoding='utf8'))
assert len(recipes)==58
base=ROOT/'research/roundtrip';base.mkdir(exist_ok=True)
tool=ROOT/'research/7zip-win/7z.exe'
report=[]
started=time.time()
for n,(slug,recipe) in enumerate(recipes.items(),1):
    case=base/slug
    assert case.resolve().is_relative_to(base.resolve())
    if case.exists():
        shutil.rmtree(case)
    home=case/'home';steam=home/'.local/share/Steam/steamapps'
    root=steam/'common'/slug;root.mkdir(parents=True)
    appid=recipe.get('appid') or '777777'
    build=(recipe.get('builds') or ['99999999'])[0]
    (steam/f'appmanifest_{appid}.acf').write_text(
        f'"appid" "{appid}" "name" "{slug}" "installdir" "{slug}" "buildid" "{build}"',encoding='utf8')
    for directory in recipe.get('anchor_dirs',[]):
        (root/directory).mkdir(parents=True,exist_ok=True)
    for path in set(recipe.get('anchors',[]) + recipe['files'][:1]):
        f=root/path;f.parent.mkdir(parents=True,exist_ok=True);f.write_bytes(('ORIGINAL '+path).encode())
    for removal in recipe.get('remove',[]):
        if 'path' in removal:
            path=removal['path']
        else:
            name='test-hq.bin' if 'hq' in removal['glob'] else 'test-optional.pak'
            path=removal['folder']+'/'+name
        f=root/path;f.parent.mkdir(parents=True,exist_ok=True);f.write_bytes(b'ORIGINAL REMOVED ASSET')
    prefix=steam/'compatdata'/appid/'pfx/drive_c/windows/system32'
    if recipe.get('prefix_copies'):
        prefix.mkdir(parents=True);(prefix/'cryptbase.dll').write_bytes(b'ORIGINAL WINE BUILTIN')
    original={f.relative_to(root).as_posix():digest(f) for f in root.rglob('*') if f.is_file()}
    manager=EclipseManager(ROOT,case/'settings',case/'runtime',home)
    manager.extractor=lambda:str(tool)
    def download(asset,target):
        folder='starfield-textures' if asset['url']!=recipe['url'] else slug
        source=ROOT/'research'/folder/'payload.rar'
        assert digest(source)==asset['sha256'], 'Pinned archive hash mismatch: '+folder
        shutil.copyfile(source,target)
    manager.download=download
    result=manager.apply(slug,appid,'MANGOHUD=1 %command%' if recipe.get('launch') else None)
    assert result['ok'],(slug,result)
    if result.get('launch_pending'):
        task=manager.launch_task(appid)
        assert 'MANGOHUD=1' in task['options']
        manager.finish_launch(appid)
    state=json.loads(manager.journal(appid).read_text(encoding='utf8'))
    roots={k:Path(v) for k,v in state['roots'].items()}
    for entry in state['entries']:
        target=roots[entry['scope']]/entry['path']
        if entry['action']=='remove':
            assert not target.exists(),(slug,entry['path'])
        else:
            assert digest(target)==entry['installed'],(slug,entry['path'])
    result=manager.restore(appid)
    assert result['ok'],(slug,result)
    if result.get('launch_pending'):
        assert manager.launch_task(appid)['options']=='MANGOHUD=1 %command%'
        manager.finish_launch(appid)
    restored={f.relative_to(root).as_posix():digest(f) for f in root.rglob('*') if f.is_file()}
    assert original==restored,(slug,'Round-trip file mismatch')
    if recipe.get('prefix_copies'):
        assert (prefix/'cryptbase.dll').read_bytes()==b'ORIGINAL WINE BUILTIN'
    assert not manager.journal(appid).exists()
    report.append(dict(slug=slug,passed=True,installed_files=sum(e['action']=='write' for e in state['entries']),
                       removed_files=sum(e['action']=='remove' for e in state['entries']),
                       launch_options=bool(recipe.get('launch')),assets=1+len(recipe.get('extras',[])),
                       sha256=recipe['sha256']))
    docs=ROOT/'docs';docs.mkdir(exist_ok=True)
    (docs/'archive-validation.json').write_text(json.dumps(dict(
        method='Real release archives, production file transaction engine, disposable Steam fixtures; Steam native option acknowledgement simulated. No gameplay validation.',
        games=report),ensure_ascii=False,indent=2),encoding='utf8')
    shutil.rmtree(case)
    print(f'[{n}/58] {slug}: actual archive install + restore PASS',flush=True)
print('All 58 real-archive round trips passed in',round(time.time()-started),'seconds',flush=True)
