import { searchTMDB } from '@/api/media'
import type { DoubanListItem, TMDBBrief } from '@/types/media'
import type { DramaTmdbMatchResult } from '@/types/dramaLauncher'

function normalizeDoubanTitleForTMDBSearch(title: string) {
  let out = String(title || '').trim()
  if (!out) return ''
  out = out.replace(/第\s*[0-9一二三四五六七八九十百千两零]+季/gi, '')
  out = out.replace(/\bseason\s*\d+\b/gi, '')
  out = out.replace(/\bs\s*\d+\b/gi, '')
  out = out.replace(/[\s·\-_:：]+$/g, '')
  out = out.replace(/\s+/g, ' ').trim()
  return out
}

function getDoubanDateHints(item: DoubanListItem) {
  const rawYear = String(item.year || '').trim()
  const subtitle = String(item.card_subtitle || '').trim()
  const rawDateMatch = rawYear.match(/\b\d{4}-\d{2}-\d{2}\b/)
  const subtitleDateMatch = subtitle.match(/\b\d{4}-\d{2}-\d{2}\b/)
  const rawYearMatch = rawYear.match(/\b\d{4}\b/)
  const subtitleYearMatch = subtitle.match(/\b\d{4}\b/)
  return {
    sourceDate: String(rawDateMatch?.[0] || subtitleDateMatch?.[0] || '').trim(),
    sourceYear: String(rawYearMatch?.[0] || subtitleYearMatch?.[0] || '').trim(),
  }
}

function getTMDBItemDate(item: TMDBBrief, mediaType: 'movie' | 'tv') {
  return String(mediaType === 'movie' ? item.release_date || '' : item.first_air_date || '').trim()
}

function getTMDBItemTitle(item: TMDBBrief, mediaType: 'movie' | 'tv') {
  return String(
    mediaType === 'movie'
      ? item.title || item.original_title || ''
      : item.name || item.original_name || '',
  ).trim()
}

function buildResolvedPreset(item: TMDBBrief, mediaType: 'movie' | 'tv', fallbackTaskname: string) {
  return {
    taskname: getTMDBItemTitle(item, mediaType) || fallbackTaskname,
    tmdb_id: Number(item.id) || null,
    tmdb_media_type: mediaType,
    open_tmdb_search: false,
    tmdb_search_query: '',
    tmdb_search_reason: null,
  } as const
}

function buildManualPreset(
  taskname: string,
  mediaType: 'movie' | 'tv',
  query: string,
  reason: 'not-configured' | 'no-match' | 'ambiguous',
  openTmdbSearch: boolean,
) {
  return {
    taskname,
    tmdb_id: null,
    tmdb_media_type: mediaType,
    open_tmdb_search: openTmdbSearch,
    tmdb_search_query: query,
    tmdb_search_reason: reason,
  } as const
}

function pickExactYearCandidate(
  items: TMDBBrief[],
  mediaType: 'movie' | 'tv',
  year: string,
  sourceDate?: string,
) {
  const exactDate = String(sourceDate || '').trim()
  if (exactDate) {
    const exact = items.find((item) => getTMDBItemDate(item, mediaType) === exactDate) || null
    if (exact) return exact
  }
  const y = String(year || '').trim()
  if (!y) return null
  return items.find((item) => getTMDBItemDate(item, mediaType).startsWith(y)) || null
}

export async function resolveDoubanDramaPreset(params: {
  item: DoubanListItem
  mediaType: 'movie' | 'tv'
}): Promise<DramaTmdbMatchResult> {
  const mediaType = params.mediaType
  const sourceTitle = String(params.item.title || '').trim()
  const query = normalizeDoubanTitleForTMDBSearch(sourceTitle) || sourceTitle

  if (!query) {
    return {
      configured: true,
      reason: 'no-match',
      manualSearch: buildManualPreset(sourceTitle || '未命名任务', mediaType, '', 'no-match', false),
    }
  }

  const { sourceDate, sourceYear } = getDoubanDateHints(params.item)
  const strict = await searchTMDB({
    q: query,
    type: mediaType,
    year: sourceYear || undefined,
    page: 1,
  })

  if (!strict.configured) {
    return {
      configured: false,
      reason: 'not-configured',
      manualSearch: buildManualPreset(sourceTitle || query, mediaType, query, 'not-configured', false),
    }
  }

  const strictItems = strict.items || []
  const exact = pickExactYearCandidate(strictItems, mediaType, sourceYear, sourceDate)
  if (exact?.id) {
    return {
      configured: true,
      resolved: buildResolvedPreset(exact, mediaType, sourceTitle || query),
    }
  }

  if (strictItems.length === 1 && strictItems[0]?.id) {
    return {
      configured: true,
      resolved: buildResolvedPreset(strictItems[0], mediaType, sourceTitle || query),
    }
  }

  const loose = await searchTMDB({ q: query, type: mediaType, page: 1 })
  const looseItems = loose.items || []
  if (looseItems.length === 1 && looseItems[0]?.id) {
    return {
      configured: true,
      resolved: buildResolvedPreset(looseItems[0], mediaType, sourceTitle || query),
    }
  }

  const reason = looseItems.length > 1 || strictItems.length > 1 ? 'ambiguous' : 'no-match'
  return {
    configured: true,
    reason,
    manualSearch: buildManualPreset(sourceTitle || query, mediaType, query, reason, true),
  }
}
