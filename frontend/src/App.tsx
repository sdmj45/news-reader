/**
 * The application.
 *
 * One screen with two views - the news list and saved articles - and a settings sheet.
 * There is no router: the whole product is a list with filters, and a URL scheme would be
 * more machinery than the thing it navigates.
 *
 * Saved articles are kept in the browser, not on the server. Until there are accounts, a
 * favourites endpoint would be either a list everyone shares or a tracking identifier, and
 * neither belongs in a household reader.
 */

import { useCallback, useEffect, useMemo, useState } from 'react'

import { ArticleCard } from './components/ArticleCard'
import { FilterBar, Header, SettingsSheet, type Theme, type View } from './components/Chrome'
import { useArticles } from './hooks/useArticles'
import { useFavourites, useLocalState } from './hooks/useLocalState'
import { STRINGS, type UiLanguage } from './i18n/strings'
import { api } from './services/api'
import type { Article, CategoryCount, Health } from './types/api'

function detectLanguage(): UiLanguage {
  const preferred = navigator.languages ?? [navigator.language]
  for (const tag of preferred) {
    const primary = tag.toLowerCase().split('-')[0]
    if (primary === 'zh' || primary === 'fr' || primary === 'en') return primary
  }
  return 'fr'
}

export default function App() {
  const [language, setLanguage] = useLocalState<UiLanguage>('newsreader.language', detectLanguage())
  const [theme, setTheme] = useLocalState<Theme>('newsreader.theme', 'auto')
  const [chineseFirst, setChineseFirst] = useLocalState('newsreader.chineseFirst', false)
  const [view, setView] = useState<View>('news')
  const [category, setCategory] = useState<string | null>(null)
  const [query, setQuery] = useState('')
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [categories, setCategories] = useState<CategoryCount[]>([])
  const [health, setHealth] = useState<Health | null>(null)

  const strings = STRINGS[language]
  const favourites = useFavourites()

  // The theme attribute drives the CSS variables; `auto` removes it and lets the media
  // query decide.
  useEffect(() => {
    const root = document.documentElement
    if (theme === 'auto') root.removeAttribute('data-theme')
    else root.setAttribute('data-theme', theme)
  }, [theme])

  useEffect(() => {
    document.documentElement.lang = language
    document.title = `${strings.appName} · ${strings.tagline}`
  }, [language, strings])

  const filters = useMemo(
    () => ({ category: category ? [category] : undefined, q: query || undefined }),
    [category, query],
  )
  const { articles, state, hasMore, loadingMore, loadMore, reload } = useArticles(filters)

  // Category counts and health are chrome, not content: a failure here must leave the news
  // readable, so they are fetched separately and their errors are swallowed deliberately.
  useEffect(() => {
    api.categories().then(setCategories).catch(() => setCategories([]))
    api.health().then(setHealth).catch(() => setHealth(null))
  }, [])

  const [savedArticles, setSavedArticles] = useLocalState<Article[]>('newsreader.saved', [])

  // Saved articles are stored whole, so the list still works when the backend has rotated
  // them out or is unreachable. The stored copy is refreshed whenever a saved article
  // appears in a fetched page.
  useEffect(() => {
    if (!articles.length) return
    setSavedArticles((current) => {
      const byId = new Map(current.map((a) => [a.id, a]))
      let changed = false
      for (const article of articles) {
        if (favourites.ids.includes(article.id)) {
          if (JSON.stringify(byId.get(article.id)) !== JSON.stringify(article)) {
            byId.set(article.id, article)
            changed = true
          }
        }
      }
      for (const id of [...byId.keys()]) {
        if (!favourites.ids.includes(id)) {
          byId.delete(id)
          changed = true
        }
      }
      return changed ? [...byId.values()] : current
    })
  }, [articles, favourites.ids, setSavedArticles])

  const onToggleFavourite = useCallback(
    (id: string) => {
      const article = articles.find((a) => a.id === id)
      favourites.toggle(id)
      if (article) {
        setSavedArticles((current) =>
          current.some((a) => a.id === id)
            ? current.filter((a) => a.id !== id)
            : [article, ...current],
        )
      }
    },
    [articles, favourites, setSavedArticles],
  )

  const shown = view === 'favourites' ? savedArticles : articles

  return (
    <div className="min-h-dvh" style={{ background: 'var(--bg)' }}>
      <Header
        strings={strings}
        view={view}
        onView={setView}
        favouriteCount={favourites.ids.length}
        onOpenSettings={() => setSettingsOpen(true)}
      />

      {view === 'news' && (
        <FilterBar
          strings={strings}
          categories={categories}
          selected={category}
          onSelect={setCategory}
          query={query}
          onQuery={setQuery}
        />
      )}

      <main className="mx-auto max-w-3xl px-4 py-4">
        {view === 'news' && state.kind === 'loading' && <SkeletonList />}

        {view === 'news' && state.kind === 'error' && (
          <ErrorPanel
            message={
              state.reason === 'offline'
                ? strings.errorOffline
                : state.reason === 'timeout'
                  ? strings.errorTimeout
                  : state.message || strings.errorGeneric
            }
            retryLabel={strings.retry}
            onRetry={reload}
          />
        )}

        {(view === 'favourites' || state.kind === 'ready') && (
          <>
            {shown.length === 0 ? (
              <p className="py-16 text-center text-[14px]" style={{ color: 'var(--text-faint)' }}>
                {view === 'favourites' ? strings.noFavourites : strings.noArticles}
              </p>
            ) : (
              <div className="space-y-3">
                {shown.map((article) => (
                  <ArticleCard
                    key={article.id}
                    article={article}
                    strings={strings}
                    chineseFirst={chineseFirst}
                    isFavourite={favourites.has(article.id)}
                    onToggleFavourite={onToggleFavourite}
                  />
                ))}
              </div>
            )}

            {view === 'news' && hasMore && (
              <button
                type="button"
                onClick={loadMore}
                disabled={loadingMore}
                className="mt-5 w-full cursor-pointer rounded-lg border py-3 text-[14px] font-medium transition-colors disabled:opacity-50"
                style={{ borderColor: 'var(--border)', color: 'var(--text-muted)' }}
              >
                {loadingMore ? strings.loading : strings.loadMore}
              </button>
            )}
          </>
        )}
      </main>

      <footer className="mx-auto max-w-3xl px-4 pt-2 pb-10 text-[11px] leading-relaxed"
        style={{ color: 'var(--text-faint)' }}>
        {strings.aboutBody}
      </footer>

      <SettingsSheet
        open={settingsOpen}
        onClose={() => setSettingsOpen(false)}
        strings={strings}
        language={language}
        onLanguage={setLanguage}
        theme={theme}
        onTheme={setTheme}
        chineseFirst={chineseFirst}
        onChineseFirst={setChineseFirst}
        health={health}
      />
    </div>
  )
}

/** Shaped like the cards it replaces, so the layout does not jump when content lands. */
function SkeletonList() {
  return (
    <div className="space-y-3" aria-hidden="true">
      {[0, 1, 2, 3, 4].map((index) => (
        <div
          key={index}
          className="animate-pulse rounded-xl border p-4"
          style={{ background: 'var(--bg-raised)', borderColor: 'var(--border)' }}
        >
          <div className="h-3 w-28 rounded" style={{ background: 'var(--bg-subtle)' }} />
          <div className="mt-3 h-4 w-full rounded" style={{ background: 'var(--bg-subtle)' }} />
          <div className="mt-2 h-4 w-4/5 rounded" style={{ background: 'var(--bg-subtle)' }} />
        </div>
      ))}
    </div>
  )
}

function ErrorPanel({
  message,
  retryLabel,
  onRetry,
}: {
  message: string
  retryLabel: string
  onRetry: () => void
}) {
  return (
    <div className="rounded-xl border p-6 text-center"
      style={{ borderColor: 'var(--border)', background: 'var(--bg-raised)' }}>
      <p className="text-[14px]" style={{ color: 'var(--text-muted)' }}>
        {message}
      </p>
      <button
        type="button"
        onClick={onRetry}
        className="mt-4 cursor-pointer rounded-lg px-4 py-2 text-[14px] font-medium text-white"
        style={{ background: 'var(--accent)' }}
      >
        {retryLabel}
      </button>
    </div>
  )
}
