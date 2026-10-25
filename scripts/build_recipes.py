"""Generate the reviewed, pinned 58-game installation catalog from audit evidence."""
import json
from pathlib import Path
import re
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from eclipse import game_key

AUDIT=ROOT/'research'
items=json.loads((AUDIT/'items.json').read_text(encoding='utf8'))
steam=json.loads((AUDIT/'steam-search.json').read_text(encoding='utf8'))

# Paths below are selected from the actual archived file inventories, not guessed at runtime.
PAYLOADS={
 'black-myth-wukong':'For Licence/Black Myth Wukong',
 'hogwarts-legacy':'For Steam Licence/Hogwarts Legacy',
 'star-wars-outlaws':'For Licence/Mod/Star Wars Outlaws',
 'the-blood-of-dawnwalker':'For Licence/Mod-Dyn-Res-On-30FPS/The Blood of Dawnwalker',
 'burnout-paradise-remastered':'Burnout Paradise Remastered',
 'wuchang-fallen-feathers':'v1/For License/Wuchang Fallen Feathers',
 'tony-hawk-s-pro-skater-3-4':'For Licence/Tony Hawks Pro Skater 3 Plus 4',
 'the-outer-worlds-2':'For Licence/The Outer Worlds 2',
 'the-callisto-protocol':'For Licence/The Callisto Protocol',
 'stellar-blade':'v1/StellarBlade',
 'starfield':'For Licence v2/Starfield',
 's-t-a-l-k-e-r-2-heart-of-chornobyl':'v2/S.T.A.L.K.E.R. 2 Heart of Chornobyl',
 'robocop-rogue-city-unfinished-business':'For Licence/Robocop Rogue City Unfinished Business',
 'robocop-rogue-city':'For Licence/RoboCop Rogue City',
 'reanimal':'16-10/Reanimal',
 'ninja-gaiden-2-black':'For Linence/NINJA GAIDEN 2 Black',
 'marvel-s-spider-man-2':"For Licence/Marvel's Spider-Man 2",
 'mafia-the-old-country':'For Licence/Steam Deck/Mafia The Old Country',
 'lego-batman-legacy-of-the-dark-knight':'For Licence/LEGO Batman Legacy of the Dark Knight',
 'indiana-jones-and-the-great-circle':'For licence/Indiana Jones and the Great Circle',
 'doom-the-dark-ages':'For Licence/DOOMTheDarkAges',
 'darwins-paradox':'For Licence/Darwins Paradox',
 'cyberpunk-2077':'v2/Cyberpunk 2077',
 'optimizaciya-dlya-007-first-light':'For Cracked/SSGI_Off/007 First Light',
 'indika':'Variant 2/INDIKA',
 'need-for-speed-most-wanted-2012':'Lite Version/Need for Speed Most Wanted',
}
APPIDS={
 'aphelion':'1966410', 'alan-wake-2':None,
 'tony-hawk-s-pro-skater-3-4':'2545710',
 'need-for-speed-most-wanted-2012':'1262560',
 'metal-gear-solid-snake-eater':'2417610',
 'optimizaciya-dlya-007-first-light':'3768760',
}
NOTES={
 'black-myth-wukong':['최초 설치 전 원본 게임의 셰이더 컴파일을 완료하고 게임을 종료하세요.'],
 'star-wars-outlaws':['Steam Deck용 기본 Mod 프리셋을 설치합니다. 제작자는 SDWEAK 사용 및 게임 내 그래픽 프리셋을 Medium→Low로 변경할 것을 안내합니다.',
                      'SteamOS·Proton 버전에 종속되는 사전 생성 셰이더 캐시는 설치하지 않습니다. 게임에서 자체 생성합니다.'],
 'the-blood-of-dawnwalker':['Steam Deck용 동적 해상도 30 FPS 프리셋을 설치합니다.'],
 'wuchang-fallen-feathers':['정품용 v1(67% 렌더 해상도) 프리셋을 설치합니다.'],
 'wreckfest-2':['먼저 원본 게임을 한 번 실행해 자체 파일 검사를 완료하세요.'],
 'reanimal':['Steam Deck 화면에 맞는 16:10 프리셋을 설치합니다.'],
 's-t-a-l-k-e-r-2-heart-of-chornobyl':['성능 우선 v2 프리셋을 설치합니다.'],
 'cyberpunk-2077':['데칼을 끄는 성능 우선 v2를 설치합니다. 게임 설정에서 AMD 동시 멀티스레딩을 끄는 것은 직접 설정해야 합니다.',
                   '사이트 표기는 2.31이지만 실제 압축 파일의 Readme는 2.3을 지정합니다. 해당 버전을 확인하세요.'],
 'starfield':['성능 우선 정품 v2와 제작자가 필수로 지정한 약 8.9 GB 추가 텍스처를 함께 설치합니다. 충분한 다운로드·백업 공간이 필요합니다.'],
 'mafia-the-old-country':['정품 Steam Deck 프리셋입니다. 제작자는 NPC 감소로 일부 진행 문제가 생길 수 있다고 안내합니다. 문제가 생기면 원상 복구하세요.'],
 'need-for-speed-heat':['CryptBase.dll을 Proton 프리픽스에도 설치합니다. 프리픽스가 없으면 게임을 한 번 실행한 뒤 종료하세요.',
                        '제작자는 정품에서 작동하지 않을 수 있다고 안내합니다. 파일 자동 적용과 실제 게임 호환성은 별개입니다.'],
 'need-for-speed-most-wanted-2012':['제작자는 비정품 1.5.0.0 기준으로 안내합니다. 정품 호환성은 확인되지 않았습니다.'],
 'burnout-paradise-remastered':['제작자는 비정품 1.0.0.0 기준으로 안내합니다. 정품 호환성은 확인되지 않았습니다. Legion Go 전용 변형은 제외합니다.'],
 'optimizaciya-dlya-007-first-light':['SSGI Off 프리셋입니다. 제작자는 비정품 1.0.0.0 기준으로 안내하며, 정품 호환성은 확인되지 않았습니다.'],
 'indika':['성능 우선 Variant 2(옷 물리 끔)를 설치합니다. 게임을 다시 켠 뒤 Temporal Upsampling 설정을 한 번 전환해야 합니다.'],
 'alan-wake-2':['Steam에 추가한 비 Steam 게임 바로가기도 인식합니다. 바로가기 이름은 Alan Wake 2, 실행 파일은 실제 AlanWake2.exe로 지정하세요.'],
}


def inventory(folder):
    result={}
    for match in re.finditer(r'^.*? [A-Z_]{4}\s+(\d+)\s+(\d+) (.+)$',(folder/'listing.txt').read_text(encoding='utf8'),re.M):
        line=match.group(0)
        if ' D___ ' in line:
            continue
        path=match.group(3).replace('\\','/')
        result[path]=int(match.group(1))
    return result


def game_files(inventory):
    return [n for n in inventory if not any(s in n.lower() for s in ['screenshots','readme','работает'])]


recipes={};missing=[]
for item in items:
    slug=item['slug'];folder=AUDIT/slug
    if not (folder/'archive.json').exists():
        missing.append(slug);continue
    inv=inventory(folder);files=game_files(inv)
    payload=PAYLOADS.get(slug)
    if payload is None:
        roots=sorted({f.split('/')[0] for f in files})
        assert len(roots)==1,(slug,roots)
        payload=roots[0]
    selected={k[len(payload)+1:]:v for k,v in inv.items() if k.startswith(payload+'/')}
    assert selected,(slug,payload)
    candidates=steam[slug].get('items',[])
    if slug in APPIDS:
        appid=APPIDS[slug]
    else:
        ids=[str(i['id']) for i in candidates if game_key(i['name'])==game_key(item['title'])]
        assert len(ids)==1,(slug,candidates)
        appid=ids[0]
    text=(folder/'readme-decoded.txt').read_text(encoding='utf8') if (folder/'readme-decoded.txt').exists() else (folder/'instructions.txt').read_text(encoding='utf8')
    builds=re.findall(r'(?:buildid|build|билд)(?:\s+игры)?\s*[-:( ]*([0-9]{7,})',text,re.I)
    if slug=='until-dawn':builds=['20076348','16633318']
    if not builds:
        builds=re.findall(r'(?:build|билд)(?:\s+игры)?\s*[-:( ]*([0-9]{7,})',item.get('gameVersionEn') or item.get('gameVersion') or '',re.I)
    if slug=='indika':builds=['15648284']
    # Hogwarts' 1613387 is an internal game version, not Steam's build ID.
    version_lines=[l.strip() for l in text.splitlines() if any(s in l.lower() for s in ['game version','version of the game','версия игры','game build','билд игры'])]
    version=version_lines[0] if version_lines else item.get('gameVersionEn') or item['gameVersion']
    version=re.sub(r'^(?:Version of the game|Game Version|Game Build|Версия игры|Билд игры)\s*[-:]?\s*','',version,flags=re.I)
    version=re.sub(r'Билд','Build',version,flags=re.I)
    archive=json.loads((folder/'archive.json').read_text(encoding='utf8'))
    recipe=dict(appid=appid,builds=sorted(set(builds)),payload=payload,files=sorted(selected),
                anchors=[f for f in selected if f.lower().endswith('.exe')],
                anchor_dirs=sorted({f.split('/Content/Paks/')[0]+'/Content/Paks' for f in selected if '/Content/Paks/' in f}),
                unpacked_size=sum(selected.values()),version=version,notes=NOTES.get(slug,[]),**archive)
    if not builds:
        recipe['notes'].append('Steam 빌드 ID가 명시되지 않은 배포본입니다. 설치 전 위 지원 버전과 게임 버전을 확인하세요.')
    if slug=='hogwarts-legacy':
        recipe['remove']=[{'path':f'Phoenix/Content/Paks/pakchunk{n}optional-WindowsNoEditor.{ext}'} for n in (0,10) for ext in ('pak','ucas','utoc')]
    elif slug=='indiana-jones-and-the-great-circle':
        recipe['remove']=[{'folder':'base','glob':'*hq*'},{'path':'base/hqdb_marker.txt'}]
        # The marker is also covered by the glob. Keep only one removal rule.
        recipe['remove']=[{'folder':'base','glob':'*hq*'}]
    elif slug=='star-wars-jedi-survivor':
        recipe['remove']=[{'folder':'SwGame/Content/Paks','glob':'*optional*'}]
    elif slug=='cyberpunk-2077':
        recipe['remove']=[{'path':s} for s in ['archive/pc/content/basegame_3_nightcity_gi.archive','archive/pc/ep1/ep1_1_nightcity_gi.archive']]
    if slug=='need-for-speed-heat':
        recipe['prefix_copies']=[{'source':'CryptBase.dll','path':'CryptBase.dll'}]
        recipe['launch']={'env':{'WINEDLLOVERRIDES':'CryptBase,version=n,b'}}
    elif slug=='star-wars-outlaws':recipe['launch']={'env':{'WINEDLLOVERRIDES':'version=n,b'}}
    elif slug=='need-for-speed-most-wanted-2012':recipe['launch']={'env':{'WINEDLLOVERRIDES':'dinput8=n,b'}}
    elif slug=='stellar-blade':recipe['launch']={'env':{'SteamDeck':'0'}}
    elif slug in ('death-stranding-2-on-the-beach','doom-the-dark-ages'):
        line=next(l.strip() for l in text.splitlines() if l.startswith('-job_background') or l.startswith('+com_skipIntroVideo'))
        recipe['launch']={'args':line}
    elif slug=='the-talos-principle-reawakened':
        recipe['launch']={'env':{'WINEDLLOVERRIDES':'dxgi=n,b'}}
        recipe['notes'].append('동봉된 dxgi.dll이 Proton에서도 로드되도록 dxgi DLL 오버라이드를 자동 설정합니다.')
    if slug=='starfield':
        extra_folder=AUDIT/'starfield-textures'
        if not (extra_folder/'archive.json').exists():
            missing.append('starfield-textures');continue
        extra_inv=inventory(extra_folder)
        extra_roots=sorted({f.split('/')[0] for f in game_files(extra_inv)})
        assert len(extra_roots)==1,extra_roots
        extra_payload=extra_roots[0]
        extra_files={k[len(extra_payload)+1:]:v for k,v in extra_inv.items() if k.startswith(extra_payload+'/')}
        extra=dict(payload=extra_payload,files=sorted(extra_files),unpacked_size=sum(extra_files.values()),
                   **json.loads((extra_folder/'archive.json').read_text(encoding='utf8')))
        recipe['extras']=[extra]
    recipes[slug]=recipe
    print(slug,appid,len(selected),'files',recipe['builds'],payload)

if missing:
    print('Not ready:',missing)
    sys.exit(1)
assert len(recipes)==58,len(recipes)
(ROOT/'recipes.json').write_text(json.dumps(recipes,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
keys=['slug','title','type','gameVersionEn','modFileUrl','modFileName','modFileSize','updatedAt']
catalog=[{k:i.get(k) for k in keys} for i in items]
for i in catalog:
    if i['slug']=='optimizaciya-dlya-007-first-light':i['title']='007 First Light'
(ROOT/'catalog.json').write_text(json.dumps(catalog,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
print('Wrote all 58 recipes.')
