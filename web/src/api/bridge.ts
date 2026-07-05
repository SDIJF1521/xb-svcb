// pywebview JS 桥接：在桌面环境调用 window.pywebview.api，
// 在浏览器（npm run dev）环境回退到 mock 实现，保证前端可独立调试。

interface PywebviewWindow extends Window {
  pywebview?: {
    api?: Record<string, (...args: unknown[]) => Promise<unknown>>
  }
}

export function isDesktop(): boolean {
  if (typeof window === 'undefined') return false
  const w = window as PywebviewWindow
  return !!w.pywebview?.api
}

export function hasDesktopApiMethod(method: string): boolean {
  if (!isDesktop()) return false
  const w = window as PywebviewWindow
  return typeof w.pywebview?.api?.[method] === 'function'
}

let readyPromise: Promise<boolean> | null = null

/** 等待 pywebview 注入完成；浏览器环境在超时后以 mock 模式继续。 */
export function whenReady(timeout = 1500): Promise<boolean> {
  if (readyPromise) return readyPromise
  readyPromise = new Promise((resolve) => {
    if (isDesktop()) {
      resolve(true)
      return
    }
    let settled = false
    const done = (v: boolean) => {
      if (!settled) {
        settled = true
        resolve(v)
      }
    }
    window.addEventListener('pywebviewready', () => done(true), { once: true })
    setTimeout(() => done(isDesktop()), timeout)
  })
  return readyPromise
}

/**
 * 调用后端方法；桌面环境走 pywebview，否则执行 mock。
 */
export async function invoke<T>(
  method: string,
  args: unknown[],
  mockFn: () => T | Promise<T>,
): Promise<T> {
  await whenReady()
  if (isDesktop()) {
    const w = window as PywebviewWindow
    const fn = w.pywebview?.api?.[method]
    if (typeof fn === 'function') {
      return (await fn(...args)) as T
    }
    throw new Error(`桌面后端缺少 API：${method}`)
  }
  return await mockFn()
}
