/**
 * The one place that talks to the backend.
 *
 * Every call can fail, and the UI has to say so rather than showing an empty list: a reader
 * who sees "no articles" when the server is down will conclude there is no news. So errors
 * are a typed result, not a thrown exception that some callers remember to catch.
 */

import type {
  Article,
  ArticleFilters,
  ArticlePage,
  CategoryCount,
  Health,
  Source,
} from '../types/api'

/** Empty in development: Vite proxies `/api` to the local backend, so requests are same-origin. */
const BASE = (import.meta.env.VITE_API_BASE_URL ?? '').replace(/\/$/, '')

/** Long enough for a cold Cloud Run instance, short enough that a hung request is visible. */
const TIMEOUT_MS = 15000

export class ApiError extends Error {
  // Declared and assigned rather than a parameter property: the project's TypeScript config
  // sets `erasableSyntaxOnly`, which forbids syntax that emits runtime code.
  readonly status: number | null

  constructor(message: string, status: number | null) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

async function request<T>(path: string, params?: URLSearchParams): Promise<T> {
  const url = `${BASE}${path}${params && [...params].length ? `?${params}` : ''}`
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), TIMEOUT_MS)

  let response: Response
  try {
    response = await fetch(url, {
      signal: controller.signal,
      headers: { Accept: 'application/json' },
    })
  } catch (cause) {
    // An aborted fetch and an offline browser both land here, and they need different words.
    if (cause instanceof DOMException && cause.name === 'AbortError') {
      throw new ApiError('timeout', null)
    }
    throw new ApiError('offline', null)
  } finally {
    clearTimeout(timer)
  }

  if (!response.ok) {
    let detail = `HTTP ${response.status}`
    try {
      const body = (await response.json()) as { detail?: unknown }
      if (typeof body.detail === 'string') detail = body.detail
    } catch {
      // A non-JSON error body is still an error; the status alone is enough to report.
    }
    throw new ApiError(detail, response.status)
  }

  return (await response.json()) as T
}

function toParams(filters: ArticleFilters): URLSearchParams {
  const params = new URLSearchParams()
  // Repeatable parameters are an OR on the server, which is what the category chips need.
  filters.category?.forEach((c) => params.append('category', c))
  filters.language?.forEach((l) => params.append('language', l))
  filters.publisher?.forEach((p) => params.append('publisher', p))
  if (filters.q?.trim()) params.set('q', filters.q.trim())
  if (filters.limit) params.set('limit', String(filters.limit))
  if (filters.cursor) params.set('cursor', filters.cursor)
  return params
}

export const api = {
  articles: (filters: ArticleFilters = {}) =>
    request<ArticlePage>('/api/v1/articles', toParams(filters)),

  article: (id: string) => request<Article>(`/api/v1/articles/${encodeURIComponent(id)}`),

  categories: (language?: string) =>
    request<CategoryCount[]>(
      '/api/v1/articles/categories',
      new URLSearchParams(language ? { language } : {}),
    ),

  sources: () => request<Source[]>('/api/v1/sources'),

  health: () => request<Health>('/health'),
}
