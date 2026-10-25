"""Multi-archive installation transactions, including removals and Proton files."""
import json
import os
from pathlib import Path
import re
import shutil
import stat

from eclipse import digest, inside, save
from steamdata import steam_root


def merge_launch(current, spec):
    value = current
    for name, wanted in spec.get('env', {}).items():
        pattern = re.compile(r'(?<!\S)' + re.escape(name) + r'=(?:"([^"]*)"|\x27([^\x27]*)\x27|(\S+))')
        match = pattern.search(value)
        if name == 'WINEDLLOVERRIDES' and match:
            old = next((v for v in match.groups() if v is not None), '')
            required = set(wanted.split('=')[0].lower().split(','))
            keep = []
            for group in old.split(';'):
                if '=' not in group:
                    continue
                names, setting = group.split('=',1)
                names = ','.join(n for n in names.split(',') if n.lower() not in required)
                if names:
                    keep.append(names + '=' + setting)
            wanted = ';'.join(keep + [wanted])
        assignment = name + '="' + wanted + '"'
        value = pattern.sub(lambda _: assignment, value, count=1) if match else assignment + ' ' + value
    if '%command%' not in value:
        # Steam's default argument-only form becomes explicit when environment variables are added.
        env_prefix = re.match(r'^(?:[A-Za-z_][A-Za-z0-9_]*=(?:"[^"]*"|\S+)\s*)*', value).group(0)
        value = env_prefix + '%command%' + (' ' + value[len(env_prefix):].strip() if value[len(env_prefix):].strip() else '')
    args = spec.get('args', '')
    if args and args not in value:
        value = value.rstrip() + ' ' + args
    return value.strip()


def prefix_root(manager, game):
    root = Path(game['path'])
    libraries = [root.parents[1]] if game.get('source') != 'shortcut' else []
    libraries.append(steam_root(manager.home)/'steamapps')
    for library in libraries:
        path = library/'compatdata'/game['appid']/'pfx/drive_c/windows/system32'
        if path.is_dir():
            return path.resolve()
    raise ValueError('Proton 프리픽스가 없습니다. 게임을 한 번 실행한 뒤 종료하고 설치하세요.')


def target_path(root, rel, scope):
    # Proton's Windows directory is case-insensitive to Wine, but not to Linux.
    if scope == 'prefix':
        parts = []
        parent = root
        for part in Path(rel).parts:
            matches = [p.name for p in parent.iterdir() if p.name.casefold()==part.casefold()] if parent.is_dir() else []
            if len(matches)>1:
                raise ValueError('대소문자가 충돌하는 Proton 파일입니다: ' + rel)
            parts.append(matches[0] if matches else part)
            parent = parent/parts[-1]
        rel = '/'.join(parts)
    return inside(root, rel, allow_leaf_link=scope=='prefix')


def backup_path(journal, entry, state):
    rel = entry['path']
    if state.get('format', 1) >= 2:
        rel = entry.get('scope','game') + '/' + rel
    return inside(journal.parent/'original', rel)


def add_plan(plans, roots, source, scope, rel, action='write'):
    if scope not in roots:
        raise ValueError('허용되지 않은 설치 영역입니다.')
    target = target_path(roots[scope], rel, scope)
    key = (scope, target.relative_to(roots[scope]).as_posix())
    if key in plans:
        raise ValueError('중복된 설치 대상입니다: ' + rel)
    plans[key] = dict(source=source, scope=scope, path=key[1], action=action, target=target)


def validate_files(dest, asset):
    payload = inside(dest, asset['payload'])
    files = {f.relative_to(payload).as_posix():f for f in payload.rglob('*') if f.is_file()}
    if set(files) != set(asset['files']):
        missing=set(asset['files'])-set(files);extra=set(files)-set(asset['files'])
        raise ValueError(f'압축 파일 구성이 검증된 목록과 다릅니다. 누락 {len(missing)}개, 추가 {len(extra)}개.')
    return files


def apply(manager, slug, appid, launch_before=None, allow_build_mismatch=False):
    journal = None
    work = None
    wrote_journal = False
    try:
        manager.update('prepare', '게임 및 설치 조건 확인 중', 0, str(appid))
        recipe = manager.recipes.get(slug)
        game = manager.game(appid)
        if not recipe or not game or game.get('mod_slug') != slug:
            raise ValueError('선택한 게임과 모드가 일치하지 않습니다.')
        current = next(i for i in manager.catalog()['items'] if i['slug']==slug)
        if not current['supported']:
            raise ValueError('배포 파일 주소가 변경되었습니다. 플러그인을 업데이트하세요.')
        mismatch=bool(recipe.get('builds') and game.get('source')!='shortcut' and game['build'] not in recipe['builds'])
        if mismatch and allow_build_mismatch is not True:
            raise ValueError('설치된 게임 빌드가 다릅니다. 지원 빌드: ' + ', '.join(recipe['builds']))
        journal = manager.journal(appid)
        if journal.exists():
            raise ValueError('기존 백업이 있습니다. 먼저 원상 복구하세요.')
        if pending_launch(manager):
            raise ValueError('다른 게임의 시작 옵션 설정을 먼저 완료하세요.')
        if recipe.get('launch') and not isinstance(launch_before,str):
            raise ValueError('Steam 시작 옵션을 읽지 못했습니다. 게임을 수정하지 않았습니다.')
        root = Path(game['path'])
        roots = {'game':root}
        for anchor in recipe.get('anchors',[]):
            if not inside(root,anchor).is_file():
                raise ValueError('게임의 필수 파일을 찾을 수 없습니다: ' + anchor)
        for folder in recipe.get('anchor_dirs',[]):
            if not inside(root,folder).is_dir():
                raise ValueError('게임 설치 구조가 다릅니다: ' + folder)
        if recipe.get('prefix_copies'):
            roots['prefix'] = prefix_root(manager,game)
        manager.stopped(appid,root)
        if not manager.extractor():
            raise ValueError('RAR 압축 해제 도구를 찾을 수 없습니다.')
        assets = [recipe] + recipe.get('extras',[])
        work = manager.runtime/'work'
        if work.exists():
            if work.is_symlink():
                raise ValueError('작업 폴더가 심볼릭 링크입니다.')
            shutil.rmtree(work)
        work.mkdir()
        total_download = sum(a.get('size',0) for a in assets)
        unpacked = sum(a.get('unpacked_size',a.get('size',0)*4) for a in assets)
        if shutil.disk_usage(manager.runtime).free < total_download + unpacked + 64*1024**2:
            raise ValueError('모드 다운로드와 압축 해제를 위한 공간이 부족합니다.')
        downloaded = 0
        for n,asset in enumerate(assets):
            start=2+63*downloaded/max(total_download,1)
            downloaded += asset.get('size',0)
            manager.download_window=(start,2+63*downloaded/max(total_download,1))
            manager.download(asset,work/f'payload-{n}.rar')
        plans = {}
        primary_files = {}
        for n,asset in enumerate(assets):
            dest=work/f'extracted-{n}';dest.mkdir()
            manager.extraction_files=[asset['payload']+'/'+p for p in asset['files']]
            manager.extract_percent=68+7*n/len(assets)
            manager.extract(work/f'payload-{n}.rar',dest)
            files=validate_files(dest,asset)
            if n==0:
                primary_files=files
            for rel,source in files.items():
                add_plan(plans,roots,source,asset.get('scope','game'),rel)
        manager.update('verify','설치 파일 검사 중',76)
        for entry in recipe.get('prefix_copies',[]):
            add_plan(plans,roots,primary_files[entry['source']],'prefix',entry['path'])
        for removal in recipe.get('remove',[]):
            if 'glob' in removal:
                folder=inside(root,removal['folder'])
                targets=list(folder.glob(removal['glob'])) if folder.is_dir() else []
            else:
                targets=[inside(root,removal['path'])]
            for target in targets:
                if target.is_file():
                    rel=target.relative_to(root).as_posix()
                    add_plan(plans,roots,None,'game',rel,'remove')
        entries=[]; created_dirs=set()
        for plan in plans.values():
            target=plan['target']; link=target.is_symlink()
            if target.exists() and not target.is_file() and not link:
                raise ValueError('대상 경로가 파일이 아닙니다: '+plan['path'])
            parent=target.parent
            while parent!=roots[plan['scope']] and not parent.exists():
                created_dirs.add((plan['scope'],parent.relative_to(roots[plan['scope']]).as_posix()))
                parent=parent.parent
            entries.append(dict(scope=plan['scope'],path=plan['path'],action=plan['action'],
                                existed=target.exists() or link,original_link=os.readlink(target) if link else None,
                                original=digest(target) if target.exists() and not link else None,
                                installed=digest(plan['source']) if plan['source'] else None,
                                mode=stat.S_IMODE(target.stat().st_mode) if target.exists() and not link else 0o644))
        backup_bytes=sum(p['target'].stat().st_size for p in plans.values()
                         if p['target'].exists() and not p['target'].is_symlink())
        write_bytes=sum(p['source'].stat().st_size for p in plans.values() if p['source'])
        if shutil.disk_usage(manager.settings).free < backup_bytes+64*1024**2:
            raise ValueError('원본 백업을 저장할 공간이 부족합니다.')
        if shutil.disk_usage(root).free < write_bytes+64*1024**2:
            raise ValueError('게임 폴더에 모드를 저장할 공간이 부족합니다.')
        reservations={}
        for directory,amount in [(manager.settings,backup_bytes)] + [
                (roots[scope],sum(p['source'].stat().st_size for p in plans.values() if p['source'] and p['scope']==scope))
                for scope in roots]:
            device=directory.stat().st_dev
            previous=reservations.get(device,(directory,0))
            reservations[device]=(directory,previous[1]+amount)
        if any(shutil.disk_usage(directory).free<amount+64*1024**2 for directory,amount in reservations.values()):
            raise ValueError('같은 저장 장치에 모드와 원본 백업을 함께 저장할 공간이 부족합니다.')
        state=dict(format=2,slug=slug,appid=str(appid),root=str(root),roots={k:str(v) for k,v in roots.items()},
                   build=game['build'],phase='applying',entries=entries,
                   build_mismatch_confirmed=mismatch and allow_build_mismatch is True,
                   created_dirs=[dict(scope=s,path=p) for s,p in sorted(created_dirs,key=lambda x:len(x[1]),reverse=True)])
        if recipe.get('launch'):
            state.update(launch_before=launch_before,launch_after=merge_launch(launch_before,recipe['launch']))
        manager.stopped(appid,root)
        manager.update('backup','원본 파일 백업 중',80);copied=0
        for entry in entries:
            if entry['existed'] and entry['original_link'] is None:
                b=backup_path(journal,entry,state);b.parent.mkdir(parents=True,exist_ok=True)
                target=plans[(entry['scope'],entry['path'])]['target']
                copied=manager.copy_progress(target,b,'backup','원본 백업 중 · '+target.name,80,90,copied,backup_bytes)
                if digest(b)!=entry['original']:
                    raise ValueError('원본 백업 검증 실패: '+entry['path'])
        save(journal,state);wrote_journal=True
        manager.update('apply','게임 폴더에 복사 중',90);copied=0
        for entry in entries:
            plan=plans[(entry['scope'],entry['path'])];target=plan['target']
            if plan['action']=='remove':
                manager.update('apply','원본 파일 제외 중 · '+target.name)
                target.unlink(missing_ok=True)
                continue
            target.parent.mkdir(parents=True,exist_ok=True)
            tmp=inside(roots[entry['scope']],entry['path']+'.decky-eclipse-tmp')
            if tmp.exists():
                raise ValueError('임시 파일이 이미 존재합니다: '+str(tmp))
            try:
                copied=manager.copy_progress(plan['source'],tmp,'apply','복사 중 · '+target.name,90,98,copied,write_bytes)
                os.chmod(tmp,entry['mode']);os.replace(tmp,target)
            finally:
                tmp.unlink(missing_ok=True)
        if state.get('launch_before')!=state.get('launch_after'):
            state['phase']='install_launch_pending';save(journal,state)
            manager.update('launch','Steam 시작 옵션 적용 중',99)
            return {'ok':True,'launch_pending':True}
        state['phase']='installed';save(journal,state)
        manager.update('done','모드 적용 완료',100)
        return {'ok':True}
    except Exception as exc:
        rollback=''
        if wrote_journal and journal and journal.exists():
            try:
                restore(manager,str(appid))
                rollback=' 원본으로 복구했습니다.'
            except Exception as recover:
                rollback=' 복구가 필요합니다: '+str(recover)
        manager.update('error',str(exc)+rollback)
        return {'ok':False,'error':str(exc)+rollback}
    finally:
        if work is not None and work.exists() and not work.is_symlink() and work.resolve().is_relative_to(manager.runtime.resolve()):
            try:
                shutil.rmtree(work)
            except OSError:
                pass  # A later installation retries cleanup; recovery data is stored separately.


def restore(manager,appid):
    manager.update('restore_check','복구 파일 검사 중',0,str(appid))
    journal=manager.journal(appid)
    if not journal.exists():
        raise ValueError('복구할 백업이 없습니다.')
    state=json.loads(journal.read_text(encoding='utf8'))
    game=manager.game(appid)
    if not game or Path(game['path']).resolve()!=Path(state['root']).resolve():
        raise ValueError('게임 설치 위치가 변경되었습니다. 백업을 보존했습니다.')
    roots={k:Path(v) for k,v in state.get('roots',{'game':state['root']}).items()}
    if 'prefix' in roots and prefix_root(manager,game)!=roots['prefix']:
        raise ValueError('Proton 프리픽스 위치가 변경되었습니다. 백업을 보존했습니다.')
    manager.stopped(appid,roots['game'])
    for entry in state['entries']:
        target=target_path(roots[entry.get('scope','game')],entry['path'],entry.get('scope','game'))
        if target.is_symlink():
            if os.readlink(target)!=entry.get('original_link'):
                raise ValueError('다른 프로그램이 변경한 심볼릭 링크입니다: '+entry['path'])
        elif target.exists() and digest(target) not in (entry['installed'],entry['original']):
            raise ValueError('게임 업데이트 또는 다른 모드가 변경한 파일입니다: '+entry['path'])
        if entry['existed'] and not entry.get('original_link') and digest(backup_path(journal,entry,state))!=entry['original']:
            raise ValueError('백업 파일 검증 실패: '+entry['path'])
    manager.update('restore','원본 복구 중',15)
    state['phase']='restoring';save(journal,state)
    total=sum(backup_path(journal,e,state).stat().st_size for e in state['entries']
              if e['existed'] and not e.get('original_link'));copied=0
    for entry in reversed(state['entries']):
        scope=entry.get('scope','game');target=target_path(roots[scope],entry['path'],scope)
        if entry.get('original_link'):
            tmp=inside(roots[scope],entry['path']+'.decky-eclipse-restore')
            tmp.unlink(missing_ok=True);os.symlink(entry['original_link'],tmp);os.replace(tmp,target)
        elif entry['existed']:
            target.parent.mkdir(parents=True,exist_ok=True)
            tmp=inside(roots[scope],entry['path']+'.decky-eclipse-restore')
            tmp.unlink(missing_ok=True)
            copied=manager.copy_progress(backup_path(journal,entry,state),tmp,'restore',
                                         '원본 복사 중 · '+target.name,15,98,copied,total)
            os.replace(tmp,target)
        else:
            target.unlink(missing_ok=True)
    for directory in state.get('created_dirs',[]):
        scope=directory.get('scope','game') if isinstance(directory,dict) else 'game'
        rel=directory['path'] if isinstance(directory,dict) else directory
        folder=inside(roots[scope],rel)
        if folder.is_dir() and not any(folder.iterdir()):
            folder.rmdir()
    if state.get('launch_before')!=state.get('launch_after'):
        state['phase']='restore_launch_pending';save(journal,state)
        manager.update('launch','Steam 시작 옵션 원상 복구 중',99)
        return {'ok':True,'launch_pending':True}
    journal.unlink();manager.update('done','원상 복구 완료',100)
    return {'ok':True}


def pending_launch(manager, appid=None):
    paths=[manager.journal(appid)] if appid is not None else sorted((manager.settings/'backups').glob('*/journal.json'))
    for path in paths:
        if not path.exists():
            continue
        state=json.loads(path.read_text(encoding='utf8'))
        phase=state.get('phase')
        if phase in ('install_launch_pending','restore_launch_pending'):
            return dict(appid=state['appid'],options=state['launch_after'] if phase=='install_launch_pending' else state['launch_before'],
                        allowed=[state['launch_before'],state['launch_after']],phase=phase)
    return None


def finish_launch(manager,appid):
    path=manager.journal(appid);state=json.loads(path.read_text(encoding='utf8'))
    if state['phase']=='install_launch_pending':
        state['phase']='installed';save(path,state);message='모드 및 시작 옵션 적용 완료'
    elif state['phase']=='restore_launch_pending':
        path.unlink();message='파일 및 시작 옵션 원상 복구 완료'
    else:
        raise ValueError('진행 중인 시작 옵션 작업이 없습니다.')
    manager.update('done',message,100,str(appid))
    return {'ok':True}
