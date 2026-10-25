export const callable = (name: string) => (...args: unknown[]) => (globalThis as any).backend[name](...args);
export const definePlugin = (factory: unknown) => factory;
