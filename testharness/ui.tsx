import assert from 'node:assert/strict';
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { Content } from '../src/Content';
import { syncLaunch } from '../src/launch';

const fixture = [
  { appid:'1', name:'Supported Game', build:'100', installed:false, mod_available:true,
    mod_slug:'supported', mod_version:'1.0', can_install:true, support_reason:'자동 설치 가능', launch_required:true, launch_pending:false },
  { appid:'2', name:'Unsupported Game', build:'200', installed:false, mod_available:false,
    mod_slug:null, can_install:false, support_reason:'배포 목록에서 찾지 못했습니다.' },
  { appid:'3', name:'Pending Game', build:'300', installed:false, mod_available:true,
    mod_slug:'pending', can_install:false, support_reason:'자동 설치 규칙 검증 대기 중입니다.' },
  { appid:'4', name:'Mismatch Game', build:'400', installed:false, mod_available:true, build_mismatch:true,
    mod_slug:'mismatch', mod_version:'Build 401', can_install:true, support_reason:'지원 빌드: 401' },
];
let progress = {phase:'idle', message:'대기 중', percent:0, appid:null as string | null};
let finish: (value: unknown) => void = () => {};
const calls: string[] = [];
const originalOptions = 'CUSTOM=1 %command% -user';
let options = originalOptions;
let pendingTask: {appid:string; options:string; allowed:string[]} | null = null;
(globalThis as any).SteamClient = {Apps:{
  GetAppLaunchOptions: async () => options,
  SetAppLaunchOptions: async (_appid: number, value: string) => { options = value; },
}};
(globalThis as any).backend = {
  games: async () => fixture.map(g => ({...g})),
  status: async () => ({...progress}),
  catalog: async () => ({}),
  launch_task: async () => pendingTask,
  finish_launch: async () => {
    pendingTask=null;fixture[0].launch_pending=false;
    progress={phase:'done',message:'시작 옵션 설정 완료',percent:100,appid:'1'};
    return {ok:true};
  },
  fail_launch: async (message: string) => { progress={...progress,phase:'error',message}; return {ok:false}; },
  apply: async (slug: string, appid: string, launchBefore: string, allowMismatch:boolean) => {
    if (appid==='4') {
      assert.equal(allowMismatch,true);
      calls.push('apply:mismatch:4:true');fixture[3].installed=true;
      progress={phase:'done',message:'모드 적용 완료',percent:100,appid:'4'};
      return {ok:true};
    }
    assert.equal(allowMismatch,false);
    assert.equal(launchBefore,originalOptions);
    calls.push(`apply:${slug}:${appid}`);
    progress = {phase:'download', message:'다운로드 중 · 40 MB', percent:42, appid};
    return new Promise(resolve => { finish = resolve; });
  },
  restore: async (appid: string) => {
    calls.push(`restore:${appid}`);
    progress = {phase:'restore', message:'원본 복사 중 · game.exe', percent:67, appid};
    return new Promise(resolve => { finish = resolve; });
  },
};
const host = document.createElement('div');
document.body.append(host);
const root = createRoot(host);
const tick = () => new Promise(resolve => setTimeout(resolve, 0));
const button = (text: string) => {
  const found = [...document.querySelectorAll('button')].find(b => b.textContent?.trim() === text || b.textContent?.includes(text));
  assert.ok(found, `Button missing: ${text}`);
  return found;
};
const click = async (text: string) => { await act(async () => {button(text).click(); await tick();}); };
const poll = async () => { await act(async () => { await new Promise(resolve => setTimeout(resolve, 550)); }); };

await act(async () => { root.render(<Content />); await tick(); });
assert.ok(host.textContent?.includes('4개 게임'));
const green = [...host.querySelectorAll('span')].find(s => s.textContent === '● 지원');
const red = [...host.querySelectorAll('span')].find(s => s.textContent === '● 지원안함');
assert.equal(green?.style.color, 'rgb(114, 230, 160)');
assert.equal(red?.style.color, 'rgb(255, 136, 136)');
const orange = [...host.querySelectorAll('span')].find(s => s.textContent === '● 빌드 다름');
assert.equal(orange?.style.color, 'rgb(255, 180, 84)');
assert.ok(host.textContent?.includes('빌드 다름 1개'));
await click('Supported Game');
assert.ok(host.textContent?.includes('게임 설정'));
assert.equal(button('모드 다운로드 및 설치').disabled, false);
assert.equal(button('원상 복구').disabled, true);
await click('모드 다운로드 및 설치');
assert.equal(document.querySelector('[role=dialog]'),null);
await poll();
assert.equal(host.querySelector('[role=progressbar]')?.getAttribute('aria-valuenow'), '42');
assert.ok(host.textContent?.includes('다운로드 중 · 40 MB'));
assert.equal(button('모드 다운로드 및 설치').disabled, true);
assert.deepEqual(calls, ['apply:supported:1']);
await act(async () => {
  fixture[0].installed = true;
  pendingTask={appid:'1',options:'SteamDeck="0" '+originalOptions,allowed:[originalOptions,'SteamDeck="0" '+originalOptions]};
  progress = {phase:'done', message:'모드 적용 완료', percent:100, appid:'1'};
  finish({ok:true}); await tick();
});
assert.equal(button('원상 복구').disabled, false);
assert.equal(options,'SteamDeck="0" '+originalOptions);
assert.equal(host.querySelector('[role=progressbar]')?.getAttribute('aria-valuenow'), '100');
await click('원상 복구'); await poll();
assert.equal(host.querySelector('[role=progressbar]')?.getAttribute('aria-valuenow'), '67');
assert.ok(host.textContent?.includes('원본 복사 중'));
await act(async () => {
  fixture[0].installed = false;
  pendingTask={appid:'1',options:originalOptions,allowed:[originalOptions,'SteamDeck="0" '+originalOptions]};
  progress = {phase:'done', message:'원상 복구 완료', percent:100, appid:'1'};
  finish({ok:true}); await tick();
});
assert.equal(button('원상 복구').disabled, true);
assert.equal(options,originalOptions);
await click('설치된 게임 목록');
await click('Unsupported Game');
assert.equal(button('모드 다운로드 및 설치').disabled, true);
assert.equal(host.querySelector('[role=progressbar]'), null); // Other games do not inherit stale work.
await click('설치된 게임 목록'); await click('Pending Game');
assert.ok(host.textContent?.includes('검증 대기'));
assert.ok([...host.querySelectorAll('span')].some(s => s.textContent === '● 지원'));
assert.equal(button('모드 다운로드 및 설치').disabled, true);
await click('설치된 게임 목록'); await click('Mismatch Game');
assert.equal([...host.querySelectorAll('span')].find(s => s.textContent === '● 빌드 다름')?.style.color,'rgb(255, 180, 84)');
assert.equal(button('모드 다운로드 및 설치').disabled,false);
const beforeCancel=calls.length;
await click('모드 다운로드 및 설치');
assert.ok(document.querySelector('[role=dialog]')?.textContent?.includes('설치된 게임 버전과 모드 지원 버전이 다릅니다. 설치하시겠습니까?'));
await click('아니오');
assert.equal(document.querySelector('[role=dialog]'),null);
assert.equal(calls.length,beforeCancel);
assert.equal(fixture[3].installed,false);
await click('모드 다운로드 및 설치'); await click('예');
assert.equal(document.querySelector('[role=dialog]'),null);
assert.equal(calls.at(-1),'apply:mismatch:4:true');
assert.equal(button('설치됨').disabled,true);
assert.equal(button('원상 복구').disabled,false);
await act(async () => root.unmount());
// Recovery does not overwrite options that the user changed during a transaction.
pendingTask={appid:'1',options:originalOptions,allowed:[originalOptions,'SteamDeck="0" '+originalOptions]};
options='USER CHANGED THIS';
await assert.rejects(syncLaunch('1'),/변경/);
assert.equal(options,'USER CHANGED THIS');
assert.ok(pendingTask);
console.log('UI PASS: installed list, colors, settings, download/restore gauges, native Steam option apply/restore, user-option conflict guard');
