# 유지보수 안내

## 일반 빌드

런타임 Python 코드는 표준 라이브러리만 사용합니다. Node.js 24와 Python 3.11 이상에서 README의 검사·빌드 명령을 실행하세요. 필요한 Linux x86-64용 `bin/7zzs`와 라이선스는 저장소에 포함되어 있습니다.

설치 ZIP은 플러그인 실행에 필요한 파일만 포함합니다. `research`, `node_modules`, 테스트 임시 파일, 개발용 스크립트, 원본 모드 압축 파일은 포함하지 않습니다.

## 배포 자료 갱신

아래 개발 스크립트는 Windows와 Bandizip 콘솔 도구(`C:/Program Files/Bandizip/bz.exe`)를 사용하는 별도 감사 작업입니다. 일반 빌드와 GitHub Actions에는 필요하지 않습니다. 원본 모드와 추가 텍스처를 다운로드하므로 충분한 공간이 필요합니다.

1. `python scripts/audit_all.py`: 사이트 설명과 58개 압축 파일의 목록·해시 수집
2. `python scripts/audit_texture.py`: Starfield 필수 텍스처 추가 파일 검사
3. `python scripts/resolve_steam.py`: 공식 Steam 검색에서 AppID 확인 자료 수집
4. 실제 압축 파일의 Readme와 경로를 검토하고 `scripts/build_recipes.py`의 프리셋·설치 조건을 갱신
5. `python scripts/build_recipes.py`: 검토한 자료로 `catalog.json`, `recipes.json` 생성
6. `scripts/verify_archives.py`: 실제 7-Zip으로 테스트 폴더 설치·복구 검사. 스크립트가 안내한 Windows용 공식 7-Zip 검사 도구와 로컬 감사 파일이 필요합니다.
7. `docs/SUPPORTED_GAMES.md`, `docs/archive-validation.json`, 변경 내역 갱신

생성기만 실행해 설치 지원을 선언하지 마세요. 실제 압축 구조, 정품/기기별 프리셋, 지원 버전, 추가 파일과 시작 옵션을 확인해야 합니다. 감사용 파일은 `.gitignore`의 `research/`에 보관합니다.

## 릴리스

1. `package.json`과 `package-lock.json`의 버전을 함께 변경합니다.
2. `CHANGELOG.md`와 지원 목록을 갱신합니다.
3. 검사 후 커밋하고 `v0.2.4` 형태의 태그를 푸시합니다.
4. Release workflow가 검사·빌드 후 ZIP과 SHA-256을 게시합니다. Actions와 Release 결과를 확인하세요.

라이선스가 적용되는 외부 실행 파일과 CA 묶음을 바꾸면 출처·라이선스도 함께 갱신해야 합니다. ECLIPSE 모드 자체는 Git 저장소와 릴리스 ZIP에 포함하지 않습니다.
