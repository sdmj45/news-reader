/**
 * The "get the mobile app" button and the sheet it opens.
 *
 * The mobile app is this site installed as a PWA, so "download" means a different thing on
 * each device - see services/install.ts. Where the browser offers a one-tap install the
 * button uses it directly; everywhere else it opens a sheet with the steps for that device,
 * and on a computer a QR code that opens the site on the phone.
 *
 * The button disappears inside the installed app: offering to install an app to someone
 * who is already using it is noise.
 */

import { useEffect, useMemo, useState, useSyncExternalStore } from 'react'
import { createPortal } from 'react-dom'
import { renderSVG } from 'uqr'

import type { Strings } from '../i18n/strings'
import {
  appUrl,
  canPrompt,
  detectPlatform,
  isInstalled,
  onInstallStateChange,
  promptInstall,
  type Platform,
} from '../services/install'

function useInstallState() {
  const prompt = useSyncExternalStore(onInstallStateChange, canPrompt, () => false)
  const installed = useSyncExternalStore(onInstallStateChange, isInstalled, () => false)
  return { prompt, installed }
}

export function InstallButton({ strings }: { strings: Strings }) {
  const { prompt, installed } = useInstallState()
  const platform = useMemo(() => detectPlatform(), [])
  const [open, setOpen] = useState(false)

  if (installed) return null

  const onClick = async () => {
    // On a phone with a one-tap install there is nothing to explain; on a computer the
    // reader asked for the *mobile* app, so the QR code comes first even if this browser
    // could install the desktop version.
    if (prompt && platform === 'android') {
      const accepted = await promptInstall().catch(() => false)
      if (accepted) return
    }
    setOpen(true)
  }

  return (
    <>
      <button
        type="button"
        onClick={() => void onClick()}
        aria-label={strings.installApp}
        title={strings.installApp}
        className="flex cursor-pointer items-center gap-1.5 rounded-lg border px-2 py-1.5 text-[13px] font-medium transition-colors hover:opacity-80"
        style={{ borderColor: 'var(--accent)', color: 'var(--accent)' }}
      >
        <PhoneIcon />
        <span className="hidden sm:inline">{strings.installApp}</span>
      </button>
      {/* Portalled to <body>: the button lives in the sticky header, whose backdrop-filter
          makes it the containing block for `position: fixed`. Rendered in place, the sheet
          was positioned against the header and clipped to the top of the screen. */}
      {open &&
        createPortal(
          <InstallSheet
            strings={strings}
            platform={platform}
            canPrompt={prompt}
            onClose={() => setOpen(false)}
          />,
          document.body,
        )}
    </>
  )
}

function InstallSheet({
  strings,
  platform,
  canPrompt: promptAvailable,
  onClose,
}: {
  strings: Strings
  platform: Platform
  canPrompt: boolean
  onClose: () => void
}) {
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  const url = appUrl()
  const steps =
    platform === 'ios'
      ? strings.installStepsIos
      : platform === 'in-app'
        ? strings.installStepsInApp
        : platform === 'android'
          ? strings.installStepsAndroid
          : null

  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center sm:items-center"
      role="dialog" aria-modal="true" aria-label={strings.installTitle}>
      <button
        type="button"
        aria-label={strings.close}
        onClick={onClose}
        className="absolute inset-0 cursor-default"
        style={{ background: 'rgba(0,0,0,0.45)' }}
      />
      <div
        className="relative max-h-[85vh] w-full max-w-md overflow-y-auto rounded-t-2xl border p-5 sm:rounded-2xl"
        style={{ background: 'var(--bg-raised)', borderColor: 'var(--border)' }}
      >
        <h2 className="text-[16px] font-semibold">{strings.installTitle}</h2>
        <p className="mt-2 text-[13px] leading-relaxed" style={{ color: 'var(--text-muted)' }}>
          {strings.installIntro}
        </p>

        {steps === null ? (
          <div className="mt-5 flex flex-col items-center text-center">
            <QrCode value={url} label={strings.installScan} />
            <p className="mt-3 text-[13px] leading-relaxed" style={{ color: 'var(--text-muted)' }}>
              {strings.installScan}
            </p>
            <a
              href={url}
              className="mt-1 text-[12px] break-all underline"
              style={{ color: 'var(--text-faint)' }}
            >
              {url}
            </a>
          </div>
        ) : (
          <ol className="mt-5 space-y-3">
            {steps.map((step, index) => (
              <li key={step} className="flex gap-3 text-[14px] leading-snug">
                <span
                  className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-[12px] font-semibold text-white"
                  style={{ background: 'var(--accent)' }}
                  aria-hidden="true"
                >
                  {index + 1}
                </span>
                <span>{step}</span>
              </li>
            ))}
          </ol>
        )}

        {platform === 'in-app' && (
          <CopyLink url={url} strings={strings} />
        )}

        {promptAvailable && platform !== 'ios' && platform !== 'in-app' && (
          <button
            type="button"
            onClick={() => void promptInstall().then((ok) => ok && onClose())}
            className="mt-5 w-full cursor-pointer rounded-lg border py-2.5 text-[14px] font-medium"
            style={{ borderColor: 'var(--accent)', color: 'var(--accent)' }}
          >
            {platform === 'desktop' ? strings.installOnThisComputer : strings.installNow}
          </button>
        )}

        <button
          type="button"
          onClick={onClose}
          className="mt-3 w-full cursor-pointer rounded-lg py-2.5 text-[14px] font-medium text-white"
          style={{ background: 'var(--accent)' }}
        >
          {strings.close}
        </button>
      </div>
    </div>
  )
}

function QrCode({ value, label }: { value: string; label: string }) {
  // Always dark on white whatever the theme: phone cameras read inverted codes badly.
  const svg = useMemo(
    () => renderSVG(value, { border: 2, whiteColor: '#ffffff', blackColor: '#000000' }),
    [value],
  )
  return (
    <div
      role="img"
      aria-label={label}
      className="h-48 w-48 overflow-hidden rounded-xl border bg-white [&>svg]:h-full [&>svg]:w-full"
      style={{ borderColor: 'var(--border)' }}
      // Generated locally from our own URL; no user input reaches it.
      dangerouslySetInnerHTML={{ __html: svg }}
    />
  )
}

function CopyLink({ url, strings }: { url: string; strings: Strings }) {
  const [copied, setCopied] = useState(false)
  return (
    <button
      type="button"
      onClick={() =>
        void navigator.clipboard
          ?.writeText(url)
          .then(() => setCopied(true))
          .catch(() => setCopied(false))
      }
      className="mt-5 w-full cursor-pointer rounded-lg border py-2.5 text-[14px] font-medium"
      style={{ borderColor: 'var(--accent)', color: 'var(--accent)' }}
    >
      {copied ? strings.linkCopied : strings.copyLink}
    </button>
  )
}

function PhoneIcon() {
  return (
    <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor"
      strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <rect x="6" y="2" width="12" height="20" rx="2.5" />
      <path d="M12 7v7m-3-3 3 3 3-3" />
    </svg>
  )
}
