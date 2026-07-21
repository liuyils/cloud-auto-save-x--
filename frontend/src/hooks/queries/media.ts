import { useQuery } from '@tanstack/vue-query'
import { computed, type Ref } from 'vue'
import { fetchDoubanCategories, fetchDoubanList, searchTMDB } from '@/api/media'

export function useMediaDiscoverQuery() {
  return useQuery({
    queryKey: ['media', 'douban-categories'],
    queryFn: () => fetchDoubanCategories(),
  })
}

export function useDoubanListQuery(
  mainCategory: Ref<string>,
  subCategory: Ref<string>,
  start: Ref<number>,
  limit?: number,
) {
  return useQuery({
    queryKey: computed(() => ['media', 'douban-list', mainCategory.value, subCategory.value, start.value, limit ?? 20]),
    queryFn: () =>
      fetchDoubanList({
        main_category: mainCategory.value,
        sub_category: subCategory.value || undefined,
        start: start.value,
        limit: limit ?? 20,
      }),
    enabled: computed(() => mainCategory.value.length > 0),
  })
}

export function useTmdbSearchQuery(
  q: Ref<string>,
  type: Ref<string>,
  page: Ref<number>,
) {
  return useQuery({
    queryKey: computed(() => ['media', 'tmdb-search', q.value, type.value, page.value]),
    queryFn: () =>
      searchTMDB({ q: q.value, type: (type.value as any) || 'multi', page: page.value }),
    enabled: computed(() => q.value.trim().length > 0),
  })
}
