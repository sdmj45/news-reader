/**
 * The shapes the backend sends. Mirrors `backend/app/api/schemas.py`.
 *
 * `translation` is a separate object rather than fields on the article for the same reason
 * it is separate on the server: a reader must always be able to tell a publisher's words
 * from a machine's, and that distinction is easiest to keep when the types make merging the
 * two awkward.
 */

export interface TranslationInfo {
  /** Translated headline, keyed by target language. Empty when none exists. */
  title: Record<string, string>
  /** Translated publisher description, keyed by target language. */
  summary: Record<string, string>
  /** Model and version that produced these, e.g. `mymemory@2026-11-14`. */
  provider: string | null
  generated_at: string | null
}

export interface Article {
  id: string
  /** The publisher's headline, verbatim. Never machine output. */
  title: string
  url: string
  publisher: string
  domain: string
  language: string
  country: string | null
  category: string
  secondary_categories: string[]
  published_at: string
  author: string | null
  image_url: string | null
  /** The publisher's own description, or null when the licence withholds it. */
  description: string | null
  /** Why `description` is null although the feed supplied one. */
  description_withheld_reason: string | null
  translation: TranslationInfo
  license: string
  attribution: string
  event_id: string | null
}

export interface ArticlePage {
  articles: Article[]
  next_cursor: string | null
  has_more: boolean
}

export interface Source {
  source_id: string
  name: string
  domain: string
  country: string
  language: string
  category: string | null
  license: string
  attribution: string
  translation_permitted: boolean
}

export interface CategoryCount {
  category: string
  count: number
}

export interface Health {
  status: string
  articles: number
  sources_enabled: number
  last_collection: string | null
  personal_use_mode: boolean
  translator: string
}

export interface ArticleFilters {
  category?: string[]
  language?: string[]
  publisher?: string[]
  q?: string
  limit?: number
  cursor?: string | null
}
