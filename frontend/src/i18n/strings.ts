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

/**
 * The order the section chips appear in, which is an editorial decision rather than a
 * statistical one.
 *
 * Sorting by article count — the obvious default — puts whichever feed was chattiest this
 * morning first, so the navigation reshuffles itself between visits and the sections a
 * reader actually opens drift to the right. This order is fixed: France, then French
 * policy (new rules: visas, tax, pensions, benefits), then technology and AI, then China,
 * then economy, then Europe. Anything not listed follows, by count.
 */
export const CATEGORY_ORDER: readonly string[] = [
  'FRANCE',
  'FRANCE_POLICY',
  'TECHNOLOGY',
  'CHINA',
  'ECONOMY',
  'EUROPE',
]

/** Index for sorting; unlisted categories sort after every listed one. */
export function categoryRank(category: string): number {
  const index = CATEGORY_ORDER.indexOf(category)
  return index === -1 ? CATEGORY_ORDER.length : index
}

/**
 * Categories that exist as tags but get no chip of their own.
 *
 * AI articles are filed under technology, so an "AI" chip would sit at the end of the bar
 * showing the handful of articles whose headline named a model, next to a technology
 * section holding all of them. Two chips for one subject, one of them apparently broken.
 * The tag is still on the articles and still in the exported data.
 */
export const HIDDEN_CATEGORIES = new Set(['ARTIFICIAL_INTELLIGENCE'])

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
  // Mobile app (the PWA)
  installApp: string
  installTitle: string
  installIntro: string
  installScan: string
  installStepsIos: string[]
  installStepsAndroid: string[]
  installStepsInApp: string[]
  installNow: string
  installOnThisComputer: string
  copyLink: string
  linkCopied: string
  close: string
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
    FRANCE_POLICY: 'Politiques publiques',
    CHINA: 'Chine',
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
  installApp: "Télécharger l'app mobile",
  installTitle: "L'app mobile",
  installIntro:
    "Aucune boutique d'applications : l'app s'installe depuis le navigateur, en quelques secondes. Elle s'ouvre en plein écran depuis l'écran d'accueil et se met à jour toute seule.",
  installScan: "Scannez ce code avec l'appareil photo de votre téléphone, puis suivez les instructions qui s'affichent.",
  installStepsIos: [
    'Ouvrez cette page dans Safari.',
    'Touchez le bouton Partager (le carré avec une flèche vers le haut).',
    "Choisissez « Sur l'écran d'accueil », puis « Ajouter ».",
  ],
  installStepsAndroid: [
    'Ouvrez cette page dans Chrome.',
    'Touchez le menu ⋮ en haut à droite.',
    "Choisissez « Installer l'application » ou « Ajouter à l'écran d'accueil ».",
  ],
  installStepsInApp: [
    'Cette application ne peut pas installer de site.',
    'Touchez le menu ··· en haut à droite et choisissez « Ouvrir dans le navigateur », ou copiez le lien ci-dessous.',
    "Dans le navigateur, touchez de nouveau « Télécharger l'app mobile ».",
  ],
  installNow: 'Installer maintenant',
  installOnThisComputer: 'Installer aussi sur cet ordinateur',
  copyLink: 'Copier le lien',
  linkCopied: 'Lien copié',
  close: 'Fermer',
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
    FRANCE_POLICY: '法国政策',
    CHINA: '中国',
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
  installApp: '下载手机版',
  installTitle: '手机版',
  installIntro: '无需应用商店：直接从浏览器安装，几秒即可完成。安装后从主屏幕全屏打开，并会自动更新。',
  installScan: '用手机相机扫描二维码打开本站，然后按页面提示添加到主屏幕。',
  installStepsIos: [
    '用 Safari 打开本页面。',
    '点击底部的「分享」按钮（带向上箭头的方框）。',
    '选择「添加到主屏幕」，再点「添加」。',
  ],
  installStepsAndroid: [
    '用 Chrome 或系统浏览器打开本页面。',
    '点击右上角的菜单 ⋮。',
    '选择「安装应用」或「添加到主屏幕」。',
  ],
  installStepsInApp: [
    '微信等应用内的浏览器无法安装网页应用。',
    '点击右上角的 ···，选择「在浏览器中打开」，或复制下方链接到浏览器打开。',
    '在浏览器中再次点击「下载手机版」。',
  ],
  installNow: '立即安装',
  installOnThisComputer: '也安装到这台电脑',
  copyLink: '复制链接',
  linkCopied: '链接已复制',
  close: '关闭',
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
    FRANCE_POLICY: 'French policy',
    CHINA: 'China',
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
  installApp: 'Get the mobile app',
  installTitle: 'The mobile app',
  installIntro:
    'No app store: the app installs straight from the browser in a few seconds. It opens full-screen from your home screen and updates itself.',
  installScan: "Scan this code with your phone's camera, then follow the steps it shows.",
  installStepsIos: [
    'Open this page in Safari.',
    'Tap the Share button (the square with an arrow pointing up).',
    'Choose "Add to Home Screen", then "Add".',
  ],
  installStepsAndroid: [
    'Open this page in Chrome.',
    'Tap the ⋮ menu at the top right.',
    'Choose "Install app" or "Add to Home screen".',
  ],
  installStepsInApp: [
    "This app's built-in browser cannot install websites.",
    'Tap ··· at the top right and choose "Open in browser", or copy the link below.',
    'In the browser, tap "Get the mobile app" again.',
  ],
  installNow: 'Install now',
  installOnThisComputer: 'Also install on this computer',
  copyLink: 'Copy link',
  linkCopied: 'Link copied',
  close: 'Close',
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
