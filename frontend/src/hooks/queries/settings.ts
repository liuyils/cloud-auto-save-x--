import { useQuery } from '@tanstack/vue-query'
import { fetchDL302Config } from '@/api/dl302'
import { fetchMagicRegexRules } from '@/api/magicRegex'
import { fetchProxyImageCacheStats } from '@/api/proxyImageCache'
import { fetchTMDBCacheList } from '@/api/tmdbCache'
import { fetchSharePreviewBatchCacheList } from '@/api/shareLinkCache'
import { fetchTMDBConfig } from '@/api/tmdb'
import { fetchResourceSearchSources } from '@/api/resourceSearch'
import { fetchOpenListConfig } from '@/api/openlist'
import { fetchSaveRuleConfig } from '@/api/systemSettings'

export function useDl302ConfigQuery() {
  return useQuery({
    queryKey: ['dl302', 'config'],
    queryFn: () => fetchDL302Config(),
  })
}

export function useSaveRuleConfigQuery() {
  return useQuery({
    queryKey: ['system-settings', 'save-rules'],
    queryFn: () => fetchSaveRuleConfig(),
  })
}

export function useMagicRegexRulesQuery() {
  return useQuery({
    queryKey: ['magic-regex', 'rules'],
    queryFn: () => fetchMagicRegexRules(),
  })
}

export function useCacheStatsQuery() {
  return useQuery({
    queryKey: ['cache', 'proxy-image-stats'],
    queryFn: () => fetchProxyImageCacheStats(),
  })
}

export function useTMDBCacheStatsQuery() {
  return useQuery({
    queryKey: ['cache', 'tmdb-stats'],
    queryFn: () => fetchTMDBCacheList({ page: 1, page_size: 1 }),
  })
}

export function useShareLinkCacheStatsQuery() {
  return useQuery({
    queryKey: ['cache', 'share-link-stats'],
    queryFn: () => fetchSharePreviewBatchCacheList({ page: 1, page_size: 1 }),
  })
}

export function useTMDBConfigQuery() {
  return useQuery({
    queryKey: ['tmdb', 'config'],
    queryFn: () => fetchTMDBConfig(),
  })
}

export function useResourceSearchSourcesQuery() {
  return useQuery({
    queryKey: ['resource-search', 'sources'],
    queryFn: () => fetchResourceSearchSources(),
  })
}

export function useOpenListConfigQuery() {
  return useQuery({
    queryKey: ['openlist', 'config'],
    queryFn: () => fetchOpenListConfig(),
  })
}
