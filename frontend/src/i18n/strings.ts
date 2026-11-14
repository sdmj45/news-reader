/**
 * Interface strings in the three languages the project serves.
 *
 * The interface language is deliberately independent of the news language: this is built for
 * a household where someone reads French comfortably and someone else reads Chinese, looking
 * at the same French articles. Picking 中文 changes the chrome and surfaces the Chinese
 * headline first; it does not filter the news.
 *
 * Hand-written rather than pulled from an i18n library. There are about forty strings and no
 * pluralisation beyond one case; a framework here would be more configuration than content.
 */

export const UI_LANGUAGES = ['fr', 'zh', 'en'] as const
export type UiLanguage = (typeof UI_LANGUAGES)[number]

export const LANGUAGE_NAMES: Record<UiLanguage, string> = {
  fr: 'Français',
  zh: '中文',
  en: 'English',
}

interface Strings {
  appName: string
  tagline: string
  // Navigation
  home: string
  favourites: string
  search: string
  settings: string
  all: string
  // Categories, keyed by the backend's enum values
  categories: Record<string, string>
  // Article card
  readOriginal: string
  noTranslation: string
  translationUnavailable: string
  machineTranslation: string
  showOriginal: string
  showTranslation: string
  addFavourite: string
  removeFavourite: string
  relatedCoverage: string
  // States
  loading: string
  loadMore: string
  noArticles: string
  noFavourites: string
  errorOffline: string
  errorTimeout: string
  errorGeneric: string
  retry: string
  searchPlaceholder: string
  // Settings
  interfaceLanguage: string
  theme: string
  themeAuto: string
  themeLight: string
  themeDark: string
  showChineseFirst: string
  about: string
  aboutBody: string
  sourceCount: string
  articleCount: string
  lastUpdate: string
  never: string
  // Time
  justNow: string
  minutesAgo: string
  hoursAgo: string
  daysAgo: string
}

const fr: Strings = {
  appName: 'Actualités',
  tagline: 'Les titres français, avec le chinois à côté',
  home: 'À la une',
  favourites: 'Favoris',
  search: 'Rechercher',
  settings: 'Réglages',
  all: 'Tout',
  categories: {
    FRANCE: 'France',
    INTERNATIONAL: 'International',
    EUROPE: 'Europe',
    POLITICS: 'Politique',
    ECONOMY: 'Économie',
    TECHNOLOGY: 'Technologie',
    ARTIFICIAL_INTELLIGENCE: 'IA',
    SCIENCE: 'Sciences',
    HEALTH: 'Santé',
    ENVIRONMENT: 'Environnement',
    BUSINESS: 'Entreprises',
    FINANCE: 'Finance',
    SPORTS: 'Sport',
    CULTURE: 'Culture',
    EDUCATION: 'Éducation',
    OTHER: 'Divers',
  },
  readOriginal: "Lire l'article",
  noTranslation: 'Pas encore traduit',
  translationUnavailable: 'Traduction non autorisée pour cette source',
  machineTranslation: 'Traduction automatique',
  showOriginal: 'Voir le français',
  showTranslation: 'Voir le chinois',
  addFavourite: 'Mettre en favori',
  removeFavourite: 'Retirer des favoris',
  relatedCoverage: 'Aussi couvert par',
  loading: 'Chargement…',
  loadMore: 'Charger la suite',
  noArticles: 'Aucun article pour ce filtre.',
  noFavourites: "Aucun favori. Touchez l'étoile sur un article pour le garder ici.",
  errorOffline: 'Impossible de joindre le serveur.',
  errorTimeout: 'Le serveur met trop de temps à répondre.',
  errorGeneric: 'Une erreur est survenue.',
  retry: 'Réessayer',
  searchPlaceholder: 'Chercher dans les titres…',
  interfaceLanguage: "Langue de l'interface",
  theme: 'Thème',
  themeAuto: 'Automatique',
  themeLight: 'Clair',
  themeDark: 'Sombre',
  showChineseFirst: 'Afficher le chinois en premier',
  about: 'À propos',
  aboutBody:
    "Les titres, les noms de publication et les liens appartiennent à leurs éditeurs. Les traductions sont automatiques et signalées comme telles. Cette application ne reproduit pas les articles : elle renvoie vers l'original.",
  sourceCount: 'sources',
  articleCount: 'articles',
  lastUpdate: 'Dernière collecte',
  never: 'jamais',
  justNow: "à l'instant",
  minutesAgo: 'il y a {n} min',
  hoursAgo: 'il y a {n} h',
  daysAgo: 'il y a {n} j',
}

const zh: Strings = {
  appName: '法国新闻',
  tagline: '法语标题，中文对照',
  home: '头条',
  favourites: '收藏',
  search: '搜索',
  settings: '设置',
  all: '全部',
  categories: {
    FRANCE: '法国',
    INTERNATIONAL: '国际',
    EUROPE: '欧洲',
    POLITICS: '政治',
    ECONOMY: '经济',
    TECHNOLOGY: '科技',
    ARTIFICIAL_INTELLIGENCE: '人工智能',
    SCIENCE: '科学',
    HEALTH: '健康',
    ENVIRONMENT: '环境',
    BUSINESS: '商业',
    FINANCE: '金融',
    SPORTS: '体育',
    CULTURE: '文化',
    EDUCATION: '教育',
    OTHER: '其他',
  },
  readOriginal: '阅读原文',
  noTranslation: '尚未翻译',
  translationUnavailable: '该来源不允许翻译',
  machineTranslation: '机器翻译',
  showOriginal: '显示法语',
  showTranslation: '显示中文',
  addFavourite: '加入收藏',
  removeFavourite: '取消收藏',
  relatedCoverage: '其他媒体报道',
  loading: '加载中…',
  loadMore: '加载更多',
  noArticles: '此筛选条件下没有文章。',
  noFavourites: '暂无收藏。点击文章上的星标即可保存。',
  errorOffline: '无法连接服务器。',
  errorTimeout: '服务器响应超时。',
  errorGeneric: '发生错误。',
  retry: '重试',
  searchPlaceholder: '搜索标题…',
  interfaceLanguage: '界面语言',
  theme: '主题',
  themeAuto: '跟随系统',
  themeLight: '浅色',
  themeDark: '深色',
  showChineseFirst: '中文显示在前',
  about: '关于',
  aboutBody:
    '标题、媒体名称和链接的版权归各出版方所有。译文由机器生成并已标注。本应用不转载文章正文，只提供原文链接。',
  sourceCount: '个来源',
  articleCount: '篇文章',
  lastUpdate: '上次采集',
  never: '从未',
  justNow: '刚刚',
  minutesAgo: '{n} 分钟前',
  hoursAgo: '{n} 小时前',
  daysAgo: '{n} 天前',
}

const en: Strings = {
  appName: 'French News',
  tagline: 'French headlines, with Chinese alongside',
  home: 'Top stories',
  favourites: 'Saved',
  search: 'Search',
  settings: 'Settings',
  all: 'All',
  categories: {
    FRANCE: 'France',
    INTERNATIONAL: 'International',
    EUROPE: 'Europe',
    POLITICS: 'Politics',
    ECONOMY: 'Economy',
    TECHNOLOGY: 'Technology',
    ARTIFICIAL_INTELLIGENCE: 'AI',
    SCIENCE: 'Science',
    HEALTH: 'Health',
    ENVIRONMENT: 'Environment',
    BUSINESS: 'Business',
    FINANCE: 'Finance',
    SPORTS: 'Sport',
    CULTURE: 'Culture',
    EDUCATION: 'Education',
    OTHER: 'Other',
  },
  readOriginal: 'Read the article',
  noTranslation: 'Not translated yet',
  translationUnavailable: 'Translation not permitted for this source',
  machineTranslation: 'Machine translation',
  showOriginal: 'Show French',
  showTranslation: 'Show Chinese',
  addFavourite: 'Save',
  removeFavourite: 'Remove from saved',
  relatedCoverage: 'Also covered by',
  loading: 'Loading…',
  loadMore: 'Load more',
  noArticles: 'No articles match this filter.',
  noFavourites: 'Nothing saved yet. Tap the star on an article to keep it here.',
  errorOffline: 'Could not reach the server.',
  errorTimeout: 'The server took too long to respond.',
  errorGeneric: 'Something went wrong.',
  retry: 'Try again',
  searchPlaceholder: 'Search headlines…',
  interfaceLanguage: 'Interface language',
  theme: 'Theme',
  themeAuto: 'Automatic',
  themeLight: 'Light',
  themeDark: 'Dark',
  showChineseFirst: 'Show Chinese first',
  about: 'About',
  aboutBody:
    'Headlines, publication names and links belong to their publishers. Translations are machine-generated and labelled as such. This application does not reproduce articles; it links to the original.',
  sourceCount: 'sources',
  articleCount: 'articles',
  lastUpdate: 'Last collection',
  never: 'never',
  justNow: 'just now',
  minutesAgo: '{n} min ago',
  hoursAgo: '{n} h ago',
  daysAgo: '{n} d ago',
}

export const STRINGS: Record<UiLanguage, Strings> = { fr, zh, en }

/** A relative time that needs no library and no locale data. */
export function relativeTime(iso: string, strings: Strings): string {
  const then = new Date(iso).getTime()
  if (Number.isNaN(then)) return ''
  const minutes = Math.max(0, Math.round((Date.now() - then) / 60000))
  if (minutes < 2) return strings.justNow
  if (minutes < 60) return strings.minutesAgo.replace('{n}', String(minutes))
  const hours = Math.round(minutes / 60)
  if (hours < 24) return strings.hoursAgo.replace('{n}', String(hours))
  return strings.daysAgo.replace('{n}', String(Math.round(hours / 24)))
}

export type { Strings }
