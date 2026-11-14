/**
 * One article.
 *
 * The layout decision that matters: the French headline and the Chinese one are stacked, not
 * swapped. A household where one reader works in French and another in Chinese looks at the
 * same card, and hiding one behind a toggle makes them take turns. Which line comes first
 * follows the interface language.
 *
 * Absence of a translation is stated, never faked. An article with no Chinese line says why
 * - not translated yet, or not permitted for that source - because a card that silently
 * shows only French is indistinguishable from a broken one.
 */

import { memo } from 'react'

import type { Strings } from '../i18n/strings'
import { relativeTime } from '../i18n/strings'
import type { Article } from '../types/api'

interface Props {
  article: Article
  strings: Strings
  /** Put the Chinese line above the French one. */
  chineseFirst: boolean
  isFavourite: boolean
  onToggleFavourite: (id: string) => void
}

function StarIcon({ filled }: { filled: boolean }) {
  return (
    <svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true"
      fill={filled ? 'currentColor' : 'none'} stroke="currentColor" strokeWidth="1.7"
      strokeLinejoin="round">
      <path d="M12 3.6l2.6 5.27 5.82.85-4.21 4.1.99 5.79L12 16.88l-5.2 2.73.99-5.79-4.21-4.1 5.82-.85z" />
    </svg>
  )
}

function ExternalIcon() {
  return (
    <svg viewBox="0 0 24 24" width="14" height="14" aria-hidden="true" fill="none"
      stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6" />
      <path d="M15 3h6v6M10 14L21 3" />
    </svg>
  )
}

export const ArticleCard = memo(function ArticleCard({
  article,
  strings,
  chineseFirst,
  isFavourite,
  onToggleFavourite,
}: Props) {
  const chinese = article.translation.title.zh
  const chineseSummary = article.translation.summary.zh
  // "Not permitted" and "not done yet" are different facts and the reader deserves the
  // right one: the licence is on the article, so the card can tell them apart.
  const translationBlocked = article.license === 'UNKNOWN' || article.license === 'CC_BY_ND'

  const french = (
    <h2 className="text-[15px] leading-snug font-semibold tracking-[-0.01em]"
      style={{ color: 'var(--text)' }}>
      {article.title}
    </h2>
  )

  const translated = chinese ? (
    <p className="cjk text-[15px] leading-relaxed" style={{ color: 'var(--text)' }} lang="zh">
      {chinese}
    </p>
  ) : (
    <p className="text-[13px] italic" style={{ color: 'var(--text-faint)' }}>
      {translationBlocked ? strings.translationUnavailable : strings.noTranslation}
    </p>
  )

  return (
    <article
      className="rounded-xl border p-4 transition-colors sm:p-5"
      style={{ background: 'var(--bg-raised)', borderColor: 'var(--border)' }}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1 text-[12px]"
          style={{ color: 'var(--text-muted)' }}>
          <span className="truncate font-medium" style={{ color: 'var(--accent)' }}>
            {article.publisher}
          </span>
          <span aria-hidden="true">·</span>
          <time dateTime={article.published_at}>
            {relativeTime(article.published_at, strings)}
          </time>
          {article.category !== 'OTHER' && (
            <>
              <span aria-hidden="true">·</span>
              <span>{strings.categories[article.category] ?? article.category}</span>
            </>
          )}
        </div>

        <button
          type="button"
          onClick={() => onToggleFavourite(article.id)}
          aria-pressed={isFavourite}
          aria-label={isFavourite ? strings.removeFavourite : strings.addFavourite}
          title={isFavourite ? strings.removeFavourite : strings.addFavourite}
          className="-m-2 shrink-0 cursor-pointer p-2 transition-opacity hover:opacity-70"
          style={{ color: isFavourite ? 'var(--accent)' : 'var(--text-faint)' }}
        >
          <StarIcon filled={isFavourite} />
        </button>
      </div>

      <div className="mt-2.5 space-y-1.5">
        {chineseFirst ? (
          <>
            {translated}
            <div style={{ color: 'var(--text-muted)' }} className="text-[14px] leading-snug">
              {article.title}
            </div>
          </>
        ) : (
          <>
            {french}
            {translated}
          </>
        )}
      </div>

      {(article.description || chineseSummary) && (
        <div className="mt-3 space-y-1.5 border-l-2 pl-3 text-[13px] leading-relaxed"
          style={{ borderColor: 'var(--border)', color: 'var(--text-muted)' }}>
          {article.description && <p>{article.description}</p>}
          {chineseSummary && (
            <p className="cjk" lang="zh">
              {chineseSummary}
            </p>
          )}
        </div>
      )}

      <div className="mt-3.5 flex items-center justify-between gap-3">
        <a
          href={article.url}
          target="_blank"
          // noopener is the security half; noreferrer stops the publisher's analytics from
          // being told which page the reader came from.
          rel="noopener noreferrer"
          className="inline-flex items-center gap-1.5 text-[13px] font-medium hover:underline"
          style={{ color: 'var(--accent)' }}
        >
          {strings.readOriginal}
          <ExternalIcon />
        </a>
        {chinese && (
          <span className="text-[11px]" style={{ color: 'var(--text-faint)' }}
            title={article.translation.provider ?? undefined}>
            {strings.machineTranslation}
          </span>
        )}
      </div>
    </article>
  )
})
