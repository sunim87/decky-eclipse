import { callable } from '@decky/api';
import { ButtonItem, ConfirmModal, PanelSection, PanelSectionRow, showModal, TextField } from '@decky/ui';
import { useEffect, useRef, useState } from 'react';
import { currentLaunchOptions, syncLaunch } from './launch';

type Game = {
  appid: string; name: string; build: string; path: string; installed: boolean;
  mod_available: boolean; mod_slug: string | null; mod_title: string | null;
  mod_version: string | null; can_install: boolean; support_reason: string;
  build_mismatch: boolean;
  launch_required?: boolean; launch_pending?: boolean; notes?: string[]; download_size?: number; source?: string;
};
type Progress = { phase: string; message: string; percent: number; appid: string | null };
type Result = { ok: boolean; error?: string };
const catalog = callable<[refresh: boolean], { error?: string }>('catalog');
const games = callable<[], Game[]>('games');
const status = callable<[], Progress>('status');
const apply = callable<[slug: string, appid: string, launch_before: string | null, allow_build_mismatch: boolean], Result>('apply');
const restore = callable<[appid: string], Result>('restore');
const active = (p: Progress) => !['idle', 'done', 'error'].includes(p.phase);
const GREEN = '#72e6a0';
const RED = '#ff8888';
const ORANGE = '#ffb454';

export function SupportBadge({ supported, buildMismatch }: { supported: boolean; buildMismatch: boolean }) {
  const mismatch = supported && buildMismatch;
  return <span style={{ color: mismatch ? ORANGE : supported ? GREEN : RED, fontWeight: 700, whiteSpace: 'nowrap', fontSize: 13 }}>
    {mismatch ? '● 빌드 다름' : supported ? '● 지원' : '● 지원안함'}
  </span>;
}

export function WorkProgress({ progress }: { progress: Progress }) {
  const percent = Math.max(0, Math.min(100, Math.floor(progress.percent)));
  return <div style={{ width: '100%', fontSize: 13, lineHeight: 1.6 }}>
    <div style={{ display: 'flex', justifyContent: 'space-between', gap: 10 }}>
      <span>전체 진행률</span><strong>{percent}%</strong>
    </div>
    <div role="progressbar" aria-label="전체 작업 진행률" aria-valuemin={0} aria-valuemax={100}
      aria-valuenow={percent} style={{ height: 10, margin: '8px 0 10px', background: '#303b49', borderRadius: 5, overflow: 'hidden' }}>
      <div style={{ height: '100%', width: `${percent}%`, background: progress.phase === 'error' ? RED : '#67c1f5',
        transition: 'width .25s ease' }} />
    </div>
    <div role="status" aria-live="polite" style={{ overflowWrap: 'anywhere', color: progress.phase === 'error' ? RED : undefined }}>
      {progress.message}
    </div>
  </div>;
}

export function Content() {
  const [local, setLocal] = useState<Game[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [search, setSearch] = useState('');
  const [working, setWorking] = useState(false);
  const [backendBusy, setBackendBusy] = useState(false);
  const [message, setMessage] = useState('설치된 게임을 불러오는 중…');
  const [progress, setProgress] = useState<Progress | null>(null);
  const [ready, setReady] = useState(false);
  const hadActiveWork = useRef(false);
  const busy = working || backendBusy;
  const selected = local.find(g => g.appid === selectedId);
  const displayed = local.filter(g => g.name.toLocaleLowerCase().includes(search.toLocaleLowerCase()));

  useEffect(() => {
    let live = true;
    let polling = false;
    Promise.all([games(), status()]).then(async ([g, p]) => {
      if (!live) return;
      setLocal(g); setProgress(p); setBackendBusy(active(p));
      hadActiveWork.current = active(p);
      setReady(true); setMessage('게임을 선택하면 설치·복구 설정이 열립니다.');
      const pending = g.find(game => game.launch_pending);
      if (pending) {
        try {
          await syncLaunch(pending.appid);
          if (live) { setLocal(await games()); setProgress(await status()); setBackendBusy(false); }
        } catch (e) { if (live) setMessage(String(e)); }
      }
    }).catch(e => { if (live) setMessage(String(e)); });
    const timer = setInterval(async () => {
      if (polling) return;
      polling = true;
      try {
        let p = await status();
        if (p.phase === 'launch' && p.appid) {
          await syncLaunch(p.appid);
          p = await status();
        }
        if (!live) return;
        setProgress(p); setBackendBusy(active(p));
        if (hadActiveWork.current && !active(p)) {
          const g = await games();
          if (live) setLocal(g);
        }
        hadActiveWork.current = active(p);
      } catch { /* Keep the last known work state while RPC reconnects. */ }
      finally { polling = false; }
    }, 500);
    return () => { live = false; clearInterval(timer); };
  }, []);

  const refresh = async () => {
    setWorking(true); setMessage('게임 및 배포 목록을 새로고침하는 중…');
    try {
      const c = await catalog(true);
      setLocal(await games()); setReady(true);
      setMessage(c.error ? `저장된 배포 목록을 사용합니다. ${c.error}` : '게임 및 배포 목록을 갱신했습니다.');
    } catch (e) { setMessage(String(e)); }
    finally { setWorking(false); }
  };

  const run = async (game: Game, action: () => Promise<Result>) => {
    setWorking(true); setMessage('작업을 시작합니다…');
    setProgress({ phase: 'prepare', message: '작업 준비 중', percent: 0, appid: game.appid });
    try {
      const r = await action();
      await syncLaunch(game.appid);
      setMessage(r.ok ? '작업이 완료되었습니다.' : r.error || '작업에 실패했습니다.');
      const p = await status(); setProgress(p); setBackendBusy(active(p));
      setLocal(await games());
    } catch (e) {
      setMessage(String(e));
      // The backend may still be working after a transport timeout; polling keeps tracking it.
    } finally { setWorking(false); }
  };

  const showProgress = progress && progress.phase !== 'idle' &&
    (!selected || progress.appid === selected.appid);
  const requestInstall = (game: Game) => {
    if (busy || !game.can_install || game.installed || !game.mod_slug) return;
    const install = (confirmed: boolean) => run(game, async () => {
      const before = game.launch_required ? await currentLaunchOptions(game.appid) : null;
      return apply(game.mod_slug!, game.appid, before, confirmed);
    });
    if (!game.build_mismatch) { void install(false); return; }
    let decided = false;
    const modal = showModal(<ConfirmModal
      strTitle="빌드 다름"
      strDescription={<div>
        <div>설치된 게임 버전과 모드 지원 버전이 다릅니다. 설치하시겠습니까?</div>
        <div style={{ marginTop: 12, fontSize: 14 }}>설치된 Steam 빌드: {game.build}<br />모드 지원 버전: {game.mod_version}</div>
      </div>}
      strOKButtonText="예" strCancelButtonText="아니오"
      onOK={() => { if (decided) return; decided = true; modal.Close(); void install(true); }}
      onCancel={() => { decided = true; modal.Close(); }}
    />);
  };
  return <>
    {selected ? <PanelSection title="게임 설정">
      <ButtonItem layout="below" onClick={() => setSelectedId(null)}>← 설치된 게임 목록</ButtonItem>
      <PanelSectionRow><div style={{ width: '100%', lineHeight: 1.7, fontSize: 13 }}>
        <div style={{ fontSize: 18, fontWeight: 700, marginBottom: 8, overflowWrap: 'anywhere' }}>{selected.name}</div>
        <SupportBadge supported={selected.mod_available} buildMismatch={selected.build_mismatch} />
        <div style={{ marginTop: 8 }}>{selected.support_reason}</div>
        <div>{selected.source === 'shortcut' ? '비 Steam 바로가기' : `Steam 빌드: ${selected.build}`}</div>
        {selected.mod_version && <div>모드 지원 버전: {selected.mod_version}</div>}
        {!!selected.download_size && <div>다운로드: {(selected.download_size / 1024**3).toFixed(2)} GB</div>}
        {selected.notes?.map((note, index) => <div key={index} style={{ marginTop: 8, color: '#d6dce5' }}>{note}</div>)}
        <div style={{ color: selected.installed ? GREEN : '#b8c3d1', marginTop: 8 }}>
          {selected.launch_pending ? '시작 옵션 설정 미완료 · 다시 시도 가능' : selected.installed ? '적용 기록 있음 · 원상 복구 가능' : '모드 적용 기록 없음'}
        </div>
        <div style={{ marginTop: 8, color: '#b8c3d1' }}>설치·복구 전 게임을 완전히 종료하세요.</div>
      </div></PanelSectionRow>
      <ButtonItem layout="below" disabled={busy || !selected.can_install || selected.installed}
        onClick={() => requestInstall(selected)}>
        {selected.installed ? '설치됨' : '모드 다운로드 및 설치'}
      </ButtonItem>
      <ButtonItem layout="below" disabled={busy || !selected.installed}
        onClick={() => run(selected, () => restore(selected.appid))}>원상 복구</ButtonItem>
      {selected.launch_pending && <ButtonItem layout="below" disabled={working}
        onClick={() => run(selected, async () => { await syncLaunch(selected.appid); return {ok:true}; })}>
        시작 옵션 설정 다시 시도
      </ButtonItem>}
    </PanelSection> : <PanelSection title="설치된 게임">
      <PanelSectionRow><div style={{ fontSize: 13, lineHeight: 1.6 }}>
        {local.length}개 게임 · 지원 {local.filter(g => g.mod_available && !g.build_mismatch).length}개
        {' · '}빌드 다름 {local.filter(g => g.mod_available && g.build_mismatch).length}개<br />
        <span style={{ color: '#b8c3d1' }}>지원 게임은 설치 버튼으로 다운로드·압축 해제·적용합니다. 게임별 지원 버전을 확인하세요.</span>
      </div></PanelSectionRow>
      <ButtonItem disabled={busy} layout="below" onClick={refresh}>게임 및 배포 목록 새로고침</ButtonItem>
      <PanelSectionRow><TextField label="설치된 게임 검색" value={search} onChange={e => setSearch(e.target.value)} /></PanelSectionRow>
      {displayed.map(game => <ButtonItem key={game.appid} layout="below"
        description={game.installed ? '적용 기록 있음 · 복구 가능' : game.mod_available
          ? (game.build_mismatch ? '설치된 게임 빌드와 모드 지원 빌드가 다릅니다.' : game.can_install ? '자동 설치 가능' : '자동 설치 조건 확인 필요') : undefined}
        onClick={() => setSelectedId(game.appid)}>
        <div style={{ display: 'flex', width: '100%', alignItems: 'center', justifyContent: 'space-between', gap: 12 }}>
          <span style={{ whiteSpace: 'normal', overflowWrap: 'anywhere', textAlign: 'left' }}>{game.name}</span>
          <SupportBadge supported={game.mod_available} buildMismatch={game.build_mismatch} />
        </div>
      </ButtonItem>)}
      {ready && !displayed.length && <PanelSectionRow><div style={{ fontSize: 13 }}>
        {local.length ? '검색 결과가 없습니다.' : '설치된 Steam 게임을 찾지 못했습니다.'}
      </div></PanelSectionRow>}
    </PanelSection>}
    {showProgress && <PanelSection title="작업 진행 상황">
      {!selected && <PanelSectionRow><div style={{ fontSize: 13 }}>
        {local.find(g => g.appid === progress.appid)?.name || '게임 작업'}
      </div></PanelSectionRow>}
      <PanelSectionRow><WorkProgress progress={progress} /></PanelSectionRow>
    </PanelSection>}
    {(!showProgress || !backendBusy) && <PanelSection title="안내">
      <PanelSectionRow><div role="status" style={{ fontSize: 13, lineHeight: 1.6, overflowWrap: 'anywhere' }}>{message}</div></PanelSectionRow>
    </PanelSection>}
  </>;
}
