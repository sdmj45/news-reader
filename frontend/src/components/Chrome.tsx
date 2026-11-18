/**
 * Header, category bar, search and the settings sheet.
 *
 * Built mobile-first and bottom-heavy: the category chips scroll horizontally and the
 * primary controls sit within thumb reach, because this is read on a phone over breakfast
 * far more often than on a desktop.
 */

import { useEffect, useMemo, useRef, useState } from 'react'

import {
  HIDDEN_CATEGORIES,
  LANGUAGE_NAMES,
  UI_LANGUAGES,
  categoryRank,
  type Strings,
  type UiLanguage,
} from '../i18n/strings'
import type { CategoryCount, Health } from '../types/api'
import { InstallButton } from './InstallApp'

export type Theme = 'auto' | 'light' | 'dark'
export type View = 'news' | 'favourites'

interface HeaderProps {
  strings: Strings
  view: View
  onView: (view: View) => void
  favouriteCount: number
  onOpenSettings: () => void
}

export function Header({ strings, view, onView, favouriteCount, onOpenSettings }: HeaderProps) {
  return (
    <header
      className="sticky top-0 z-20 border-b backdrop-blur-md"
      style={{ background: 'color-mix(in srgb, var(--bg) 88%, transparent)',
        borderColor: 'var(--border)' }}
    >
      <div className="mx-auto flex max-w-3xl items-center gap-3 px-4 py-3">
        <div className="min-w-0 flex-1">
          <h1 className="truncate text-[17px] font-semibold tracking-[-0.02em]">
            {strings.appName}
          </h1>
          {/* Hidden below 420px: at phone width it truncates to "Les titres français, avec
              le c…", which is worse than no subtitle at all. */}
          <p className="hidden truncate text-[12px] min-[420px]:block"
            style={{ color: 'var(--text-faint)' }}>
            {strings.tagline}
          </p>
        </div>

        <nav className="flex items-center gap-1" aria-label={strings.home}>
          <TabButton active={view === 'news'} onClick={() => onView('news')}>
            {strings.home}
          </TabButton>
          <TabButton active={view === 'favourites'} onClick={() => onView('favourites')}>
            {strings.favourites}
            {favouriteCount > 0 && (
              <span className="ml-1 text-[11px] opacity-70">{favouriteCount}</span>
            )}
          </TabButton>
          <InstallButton strings={strings} />
          <button
            type="button"
            onClick={onOpenSettings}
            aria-label={strings.settings}
            title={strings.settings}
            className="cursor-pointer rounded-lg p-2 transition-colors hover:opacity-70"
            style={{ color: 'var(--text-muted)' }}
          >
            <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor"
              strokeWidth="2" aria-hidden="true">
              <circle cx="12" cy="12" r="3" />
              <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.6a1.65 1.65 0 0 0 1-1.51V3a2 2 0 1 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9c.14.37.43.67.79.84H21a2 2 0 1 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" />
            </svg>
          </button>
        </nav>
      </div>
    </header>
  )
}

function TabButton({
  active,
  onClick,
  children,
}: {
  active: boolean
  onClick: () => void
  children: React.ReactNode
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-current={active ? 'page' : undefined}
      className="cursor-pointer rounded-lg px-2.5 py-1.5 text-[13px] font-medium transition-colors"
      style={{
        background: active ? 'var(--accent-soft)' : 'transparent',
        color: active ? 'var(--accent)' : 'var(--text-muted)',
      }}
    >
      {children}
    </button>
  )
}

interface FilterBarProps {
  strings: Strings
  categories: CategoryCount[]
  selected: string | null
  onSelect: (category: string | null) => void
  query: string
  onQuery: (value: string) => void
}

export function FilterBar({
  strings,
  categories,
  selected,
  onSelect,
  query,
  onQuery,
}: FilterBarProps) {
  // The input owns its text; `query` is only the initial value. Mirroring the prop back
  // into state on every change would fight the user's typing.
  const [draft, setDraft] = useState(query)

  // Fixed editorial order first, then whatever is left by size. Sorting purely by count
  // reshuffles the navigation every few hours as one feed or another has a busy morning,
  // which makes the sections a reader opens habitually move around under their thumb.
  const ordered = useMemo(
    () =>
      categories
        .filter((c) => !HIDDEN_CATEGORIES.has(c.category) && c.count > 0)
        .sort(
          (a, b) => categoryRank(a.category) - categoryRank(b.category) || b.count - a.count,
        ),
    [categories],
  )
  const timer = useRef<number | undefined>(undefined)

  // Debounced: every keystroke is a request otherwise, and the backend does a LIKE scan.
  useEffect(() => {
    window.clearTimeout(timer.current)
    timer.current = window.setTimeout(() => onQuery(draft), 280)
    return () => window.clearTimeout(timer.current)
  }, [draft, onQuery])

  return (
    <div className="mx-auto max-w-3xl px-4 pt-4">
      <label className="relative block">
        <span className="sr-only">{strings.search}</span>
        <svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true"
          className="pointer-events-none absolute top-1/2 left-3 -translate-y-1/2"
          fill="none" stroke="currentColor" strokeWidth="2" style={{ color: 'var(--text-faint)' }}>
          <circle cx="11" cy="11" r="7" />
          <path d="M20 20l-3.5-3.5" strokeLinecap="round" />
        </svg>
        <input
          type="search"
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          placeholder={strings.searchPlaceholder}
          className="w-full rounded-lg border py-2 pr-3 pl-9 text-[14px] outline-none"
          style={{ background: 'var(--bg-subtle)', borderColor: 'var(--border)',
            color: 'var(--text)' }}
        />
      </label>

      <div
        className="-mx-4 mt-3 flex gap-2 overflow-x-auto px-4 pb-1"
        // The scrollbar is noise on a chip row that is obviously scrollable.
        style={{ scrollbarWidth: 'none' }}
        role="group"
        aria-label={strings.home}
      >
        <Chip active={selected === null} onClick={() => onSelect(null)}>
          {strings.all}
        </Chip>
        {ordered.map((entry) => (
          <Chip
            key={entry.category}
            active={selected === entry.category}
            onClick={() => onSelect(entry.category)}
          >
            {strings.categories[entry.category] ?? entry.category}
            <span className="ml-1 opacity-55">{entry.count}</span>
          </Chip>
        ))}
      </div>
    </div>
  )
}

function Chip({
  active,
  onClick,
  children,
}: {
  active: boolean
  onClick: () => void
  children: React.ReactNode
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className="shrink-0 cursor-pointer rounded-full border px-3 py-1.5 text-[13px] whitespace-nowrap transition-colors"
      style={{
        background: active ? 'var(--accent)' : 'var(--bg-subtle)',
        borderColor: active ? 'var(--accent)' : 'var(--border)',
        color: active ? '#fff' : 'var(--text-muted)',
      }}
    >
      {children}
    </button>
  )
}

interface SettingsProps {
  open: boolean
  onClose: () => void
  strings: Strings
  language: UiLanguage
  onLanguage: (language: UiLanguage) => void
  theme: Theme
  onTheme: (theme: Theme) => void
  chineseFirst: boolean
  onChineseFirst: (value: boolean) => void
  health: Health | null
}

export function SettingsSheet({
  open,
  onClose,
  strings,
  language,
  onLanguage,
  theme,
  onTheme,
  chineseFirst,
  onChineseFirst,
  health,
}: SettingsProps) {
  // Escape closes it: a sheet with no keyboard exit is a trap for anyone not using a mouse.
  useEffect(() => {
    if (!open) return
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, onClose])

  if (!open) return null

  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center sm:items-center"
      role="dialog" aria-modal="true" aria-label={strings.settings}>
      <button
        type="button"
        aria-label="Close"
        onClick={onClose}
        className="absolute inset-0 cursor-default"
        style={{ background: 'rgba(0,0,0,0.45)' }}
      />
      <div
        className="relative max-h-[85vh] w-full max-w-md overflow-y-auto rounded-t-2xl border p-5 sm:rounded-2xl"
        style={{ background: 'var(--bg-raised)', borderColor: 'var(--border)' }}
      >
        <h2 className="text-[16px] font-semibold">{strings.settings}</h2>

        <Section label={strings.interfaceLanguage}>
          <div className="flex gap-2">
            {UI_LANGUAGES.map((code) => (
              <Chip key={code} active={language === code} onClick={() => onLanguage(code)}>
                {LANGUAGE_NAMES[code]}
              </Chip>
            ))}
          </div>
        </Section>

        <Section label={strings.theme}>
          <div className="flex gap-2">
            {(
              [
                ['auto', strings.themeAuto],
                ['light', strings.themeLight],
                ['dark', strings.themeDark],
              ] as const
            ).map(([value, label]) => (
              <Chip key={value} active={theme === value} onClick={() => onTheme(value)}>
                {label}
              </Chip>
            ))}
          </div>
        </Section>

        <Section label="">
          <label className="flex cursor-pointer items-center justify-between gap-3 text-[14px]">
            <span>{strings.showChineseFirst}</span>
            <input
              type="checkbox"
              checked={chineseFirst}
              onChange={(event) => onChineseFirst(event.target.checked)}
              className="h-5 w-5 cursor-pointer accent-[var(--accent)]"
            />
          </label>
        </Section>

        <Section label={strings.about}>
          <p className="text-[13px] leading-relaxed" style={{ color: 'var(--text-muted)' }}>
            {strings.aboutBody}
          </p>
          {health && (
            <dl className="mt-3 space-y-1 text-[12px]" style={{ color: 'var(--text-faint)' }}>
              <div className="flex justify-between">
                <dt>{strings.articleCount}</dt>
                <dd>{health.articles.toLocaleString()}</dd>
              </div>
              <div className="flex justify-between">
                <dt>{strings.sourceCount}</dt>
                <dd>{health.sources_enabled}</dd>
              </div>
              <div className="flex justify-between">
                <dt>{strings.lastUpdate}</dt>
                <dd>
                  {health.last_collection
                    ? new Date(health.last_collection).toLocaleString()
                    : strings.never}
                </dd>
              </div>
            </dl>
          )}
        </Section>

        <button
          type="button"
          onClick={onClose}
          className="mt-5 w-full cursor-pointer rounded-lg py-2.5 text-[14px] font-medium text-white"
          style={{ background: 'var(--accent)' }}
        >
          OK
        </button>
      </div>
    </div>
  )
}

function Section({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <section className="mt-5">
      {label && (
        <h3 className="mb-2 text-[12px] font-medium tracking-wide uppercase"
          style={{ color: 'var(--text-faint)' }}>
          {label}
        </h3>
      )}
      {children}
    </section>
  )
}
