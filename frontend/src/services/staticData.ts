/**
 * The same API, served from two static JSON files instead of a server.
 *
 * This is what makes a free deployment possible. The backend is read-only and the data
 * changes a few times an hour, so a server would be answering questions a file can answer -
 * and it is the only component that would need a cloud account with a payment method.
 *
 * The snapshot is fetched once and filtered in the browser. On the measured payload (400
 * articles, 353 kB, 121 kB gzipped) that is *faster* than the API it replaces, because
 * every filter and search after the first costs no round trip at all.
 *
 * Search deliberately matches the Chinese translation as well as the French headline: a
 * reader typing 法国 is searching the text they can read.
 */

import type {
  Article,
  ArticleFilters,
  ArticlePage,
  CategoryCount,
  Health,
  Source,
} from '../types/api'
import { ApiError } from './apiError'

interface Meta {
  generated_at: string
  articles: number
  translated: Record<string, number>
  languages: Record<string, number>
  categories: CategoryCount[]
  publishers: string[]
  oldest: string
  newest: string
}

const BASE = import.meta.env.BASE_URL.replace(/\/$/, '')
const PAGE_SIZE = 25

/** Fetched once per page load and shared by every call; the snapshot does not change. */
let snapshot: Promise<{ articles: Article[]; meta: Meta }> | null = null

function load() {
  snapshot ??= (async () => {
    let articlesResponse: Response
    let metaResponse: Response
    try {
      // `no-cache` means "revalidate before using", not "do not cache": the browser still
      // sends If-None-Match and a 304 costs nothing when the snapshot has not changed.
      // Without it the HTTP cache serves the previous snapshot for GitHub Pages'
      // max-age=600, and any intermediate proxy may hold it far longer - which on a phone
      // is the difference between this morning's news and last night's.
      const options: RequestInit = { cache: 'no-cache' }
      ;[articlesResponse, metaResponse] = await Promise.all([
        fetch(`${BASE}/data/articles.json`, options),
        fetch(`${BASE}/data/meta.json`, options),
      ])
    } catch {
      // Reset so a retry re-fetches rather than resolving the same rejection forever, and
      // report it the way the live client does so the UI's offline panel is identical.
      snapshot = null
      throw new ApiError('offline', null)
    }
    if (!articlesResponse.ok || !metaResponse.ok) {
      snapshot = null
      throw new ApiError('offline', articlesResponse.status)
    }
    const raw = (await articlesResponse.json()) as Partial<Article>[]
    const meta = (await metaResponse.json()) as Meta
    // The exporter omits null and empty fields to keep the payload small, so they are
    // restored here rather than making every component handle `undefined`.
    const articles: Article[] = raw.map((a) => ({
      country: null,
      author: null,
      image_url: null,
      description: null,
      description_withheld_reason: null,
      secondary_categories: [],
      event_id: null,
      ...a,
      translation: {
        title: {},
        summary: {},
        provider: null,
        generated_at: null,
        ...(a.translation ?? {}),
      },
    })) as Article[]
    return { articles, meta }
  })()
  return snapshot
}

function matches(article: Article, filters: ArticleFilters): boolean {
  if (filters.category?.length) {
    // Primary or secondary, matching the backend. Clicking "China" should find a French
    // political story tagged China, not only the China desk's own articles.
    const tags = [article.category, ...article.secondary_categories]
    if (!filters.category.some((wanted) => tags.includes(wanted))) return false
  }
  if (filters.language?.length && !filters.language.includes(article.language)) return false
  if (filters.publisher?.length && !filters.publisher.includes(article.publisher)) return false
  if (filters.q) {
    const needle = filters.q.trim().toLowerCase()
    if (needle) {
      const haystack = [
        article.title,
        article.publisher,
        ...Object.values(article.translation.title),
      ]
        .join(' ')
        .toLowerCase()
      if (!haystack.includes(needle)) return false
    }
  }
  return true
}

export const staticApi = {
  async articles(filters: ArticleFilters = {}): Promise<ArticlePage> {
    const { articles } = await load()
    const matching = articles.filter((a) => matches(a, filters))
    // The cursor is just an offset here. It stays opaque to the caller so the two API
    // implementations remain interchangeable.
    const start = filters.cursor ? Number.parseInt(atob(filters.cursor), 10) || 0 : 0
    const limit = filters.limit ?? PAGE_SIZE
    const slice = matching.slice(start, start + limit)
    const end = start + slice.length
    return {
      articles: slice,
      next_cursor: end < matching.length ? btoa(String(end)) : null,
      has_more: end < matching.length,
    }
  },

  async article(id: string): Promise<Article> {
    const { articles } = await load()
    const found = articles.find((a) => a.id === id)
    if (!found) throw new ApiError('No such article.', 404)
    return found
  },

  async categories(language?: string): Promise<CategoryCount[]> {
    const { articles, meta } = await load()
    if (!language) return meta.categories
    const counts = new Map<string, number>()
    for (const article of articles) {
      if (article.language !== language) continue
      // Secondary tags counted too, so the number matches what the chip will show.
      for (const tag of new Set([article.category, ...article.secondary_categories])) {
        counts.set(tag, (counts.get(tag) ?? 0) + 1)
      }
    }
    return [...counts.entries()]
      .map(([category, count]) => ({ category, count }))
      .sort((a, b) => b.count - a.count)
  },

  async sources(): Promise<Source[]> {
    const { articles } = await load()
    // Derived from the snapshot rather than shipped separately: the interface only uses
    // this to list publishers, and a second file for that is a second thing to keep in step.
    const seen = new Map<string, Source>()
    for (const article of articles) {
      if (seen.has(article.publisher)) continue
      seen.set(article.publisher, {
        source_id: article.domain,
        name: article.publisher,
        domain: article.domain,
        country: article.country ?? '',
        language: article.language,
        category: null,
        license: article.license,
        attribution: article.attribution,
        translation_permitted: Object.keys(article.translation.title).length > 0,
      })
    }
    return [...seen.values()].sort((a, b) => a.name.localeCompare(b.name))
  },

  async health(): Promise<Health> {
    const { meta } = await load()
    return {
      status: 'ok',
      articles: meta.articles,
      sources_enabled: meta.publishers.length,
      last_collection: meta.generated_at,
      personal_use_mode: true,
      translator: 'static snapshot',
    }
  },
}
