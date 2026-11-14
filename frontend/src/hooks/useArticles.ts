/**
 * Fetching, paging and refetching the article list.
 *
 * Holds the three states a list can be in - loading, failed, loaded - as one value rather
 * than three booleans, because the combinations that cannot happen (loading and failed at
 * once) should not be representable.
 *
 * A request started before the filters changed must never overwrite the list: that is the
 * bug where typing in the search box makes results flicker between queries. Each request
 * carries a sequence number and a stale one is discarded on arrival.
 */

import { useCallback, useEffect, useRef, useState } from 'react'

import { api } from '../services/api'
import { ApiError } from '../services/apiError'
import type { Article, ArticleFilters } from '../types/api'

export type LoadState =
  | { kind: 'loading' }
  | { kind: 'ready' }
  | { kind: 'error'; reason: 'offline' | 'timeout' | 'other'; message: string }

const PAGE_SIZE = 25

function classify(error: unknown): Extract<LoadState, { kind: 'error' }> {
  if (error instanceof ApiError) {
    if (error.message === 'offline') return { kind: 'error', reason: 'offline', message: '' }
    if (error.message === 'timeout') return { kind: 'error', reason: 'timeout', message: '' }
    return { kind: 'error', reason: 'other', message: error.message }
  }
  return { kind: 'error', reason: 'other', message: String(error) }
}

export function useArticles(filters: ArticleFilters) {
  const [articles, setArticles] = useState<Article[]>([])
  const [cursor, setCursor] = useState<string | null>(null)
  const [hasMore, setHasMore] = useState(false)
  const [state, setState] = useState<LoadState>({ kind: 'loading' })
  const [loadingMore, setLoadingMore] = useState(false)

  const sequence = useRef(0)
  // Serialised so the effect re-runs on a real change rather than on every render, which is
  // what a plain object dependency would do.
  const key = JSON.stringify(filters)

  const load = useCallback(async () => {
    const mine = ++sequence.current
    setState({ kind: 'loading' })
    try {
      const page = await api.articles({ ...filters, limit: PAGE_SIZE })
      if (mine !== sequence.current) return // a newer request is in flight
      setArticles(page.articles)
      setCursor(page.next_cursor)
      setHasMore(page.has_more)
      setState({ kind: 'ready' })
    } catch (error) {
      if (mine !== sequence.current) return
      setState(classify(error))
    }
    // `filters` is covered by `key`; depending on the object itself would loop.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key])

  useEffect(() => {
    void load()
  }, [load])

  const loadMore = useCallback(async () => {
    if (!cursor || loadingMore) return
    const mine = sequence.current
    setLoadingMore(true)
    try {
      const page = await api.articles({ ...filters, limit: PAGE_SIZE, cursor })
      if (mine !== sequence.current) return
      // Guard against a duplicate id slipping in: the cursor is stable, but a collection
      // run between two pages can shift what the second page contains.
      setArticles((current) => {
        const seen = new Set(current.map((a) => a.id))
        return [...current, ...page.articles.filter((a) => !seen.has(a.id))]
      })
      setCursor(page.next_cursor)
      setHasMore(page.has_more)
    } catch {
      // A failed "load more" leaves what is already on screen alone. Replacing a readable
      // list with an error because page three failed would be the wrong trade.
      setHasMore(false)
    } finally {
      setLoadingMore(false)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cursor, loadingMore, key])

  return { articles, state, hasMore, loadingMore, loadMore, reload: load }
}
