import { callable } from '@decky/api';

type Apps = {
  GetAppLaunchOptions?: (appid: number) => Promise<string>;
  SetAppLaunchOptions?: (appid: number, options: string) => Promise<unknown> | unknown;
};
type Task = { appid: string; options: string; allowed: string[] };
const nativeApps = () => (globalThis as unknown as { SteamClient?: { Apps?: Apps } }).SteamClient?.Apps;
const readDisk = callable<[appid: string], string | null>('read_launch_options');
const task = callable<[appid: string], Task | null>('launch_task');
const finish = callable<[appid: string], { ok: boolean }>('finish_launch');
const fail = callable<[message: string], { ok: boolean }>('fail_launch');
const syncing = new Map<string, Promise<void>>();

export async function currentLaunchOptions(appid: string): Promise<string> {
  const apps = nativeApps();
  if (!apps?.SetAppLaunchOptions) throw new Error('이 Steam 클라이언트에서 시작 옵션 자동 설정 API를 사용할 수 없습니다.');
  try {
    const value = await apps.GetAppLaunchOptions?.(Number(appid));
    if (typeof value === 'string') return value;
  } catch { /* Try the same details store that Steam Properties uses. */ }
  const store = (globalThis as unknown as {
    appDetailsStore?: { GetAppDetails?: (id: number) => { strLaunchOptions?: string } | null }
  }).appDetailsStore;
  const value = store?.GetAppDetails?.(Number(appid))?.strLaunchOptions;
  if (typeof value === 'string') return value;
  const disk = await readDisk(appid);
  if (typeof disk !== 'string') throw new Error('원래 시작 옵션을 확인하지 못했습니다. Steam에서 게임 속성을 연 뒤 다시 시도하세요.');
  return disk;
}

export function syncLaunch(appid: string): Promise<void> {
  const existing = syncing.get(appid);
  if (existing) return existing;
  const work = (async () => {
    try {
      const pending = await task(appid);
      if (!pending) return;
      const current = await currentLaunchOptions(appid);
      if (!pending.allowed.includes(current)) throw new Error('시작 옵션이 작업 중 변경되었습니다. 기존 옵션을 보호하기 위해 중단했습니다.');
      if (current !== pending.options) {
        const result = await nativeApps()!.SetAppLaunchOptions!(Number(appid), pending.options);
        if (result === false) throw new Error('Steam 시작 옵션 설정에 실패했습니다.');
      }
      await finish(appid);
    } catch (e) {
      await fail(String(e));
      throw e;
    }
  })().finally(() => syncing.delete(appid));
  syncing.set(appid, work);
  return work;
}
