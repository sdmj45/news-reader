/**
 * Everything the "get the mobile app" button needs to know about the browser it runs in.
 *
 * The mobile app *is* this site, installed as a PWA: there is no app store build. What
 * differs between devices is only how a reader gets it onto their home screen:
 *
 *   Chrome / Edge / Samsung Internet  fire `beforeinstallprompt`; one tap installs.
 *   iOS (Safari and every other iOS browser)  no prompt API at all; Share → Add to Home Screen.
 *   WeChat / QQ in-app browsers  cannot install anything; the page must be opened in a real
 *     browser first. Worth handling: a Chinese-speaking reader is most likely to receive the
 *     link in WeChat.
 *   A desktop browser  is the wrong device; show a QR code that opens the site on the phone.
 *
 * `beforeinstallprompt` fires once, early, and is gone if nobody is listening - often before
 * React has mounted. So the listener is attached when this module is first imported (from
 * main.tsx) and the event is kept here for whichever component asks for it later.
 */

/** Not in lib.dom.d.ts: Chromium-only, and still a draft. */
export interface BeforeInstallPromptEvent extends Event {
  prompt(): Promise<void>
  readonly userChoice: Promise<{ outcome: 'accepted' | 'dismissed'; platform: string }>
}

export type Platform = 'ios' | 'android' | 'in-app' | 'desktop'

let deferred: BeforeInstallPromptEvent | null = null
let installed = false
const listeners = new Set<() => void>()
const notify = () => listeners.forEach((listener) => listener())

if (typeof window !== 'undefined') {
  window.addEventListener('beforeinstallprompt', (event) => {
    // Without preventDefault some Chromium versions show their own mini-infobar, which
    // would compete with the button for the same decision.
    event.preventDefault()
    deferred = event as BeforeInstallPromptEvent
    notify()
  })
  window.addEventListener('appinstalled', () => {
    deferred = null
    installed = true
    notify()
  })
}

/** Subscribe to changes in `canPrompt()` / `isInstalled()`. Returns the unsubscribe. */
export function onInstallStateChange(listener: () => void): () => void {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

/** True when the browser has offered a one-tap install that has not been used yet. */
export function canPrompt(): boolean {
  return deferred !== null
}

/**
 * Show the browser's own install dialog. Resolves to whether the reader accepted.
 * The event can be used once only, so it is dropped whatever the outcome.
 */
export async function promptInstall(): Promise<boolean> {
  const event = deferred
  if (!event) return false
  deferred = null
  notify()
  await event.prompt()
  const choice = await event.userChoice
  return choice.outcome === 'accepted'
}

/** Already running as the installed app, or installed during this visit. */
export function isInstalled(): boolean {
  if (installed) return true
  if (typeof window === 'undefined') return false
  const standalone =
    window.matchMedia?.('(display-mode: standalone)').matches ||
    window.matchMedia?.('(display-mode: fullscreen)').matches ||
    // iOS Safari's own flag, from before it supported the media query.
    (navigator as Navigator & { standalone?: boolean }).standalone === true
  return Boolean(standalone)
}

export function detectPlatform(userAgent = navigator.userAgent): Platform {
  if (/MicroMessenger|QQ\/|Weibo|DingTalk|AlipayClient/i.test(userAgent)) return 'in-app'
  // iPadOS 13+ reports itself as a Mac; the touch points give it away.
  const iPadOS = /Macintosh/.test(userAgent) && navigator.maxTouchPoints > 1
  if (/iPhone|iPad|iPod/.test(userAgent) || iPadOS) return 'ios'
  if (/Android|Mobi/i.test(userAgent)) return 'android'
  return 'desktop'
}

/** The address the QR code points at: the site root, whatever base path it is served from. */
export function appUrl(): string {
  return new URL(import.meta.env.BASE_URL, window.location.origin).href
}
