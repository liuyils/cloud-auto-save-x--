<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { Search, Plus, Pencil, Film, Loader2 } from 'lucide-vue-next'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import { useMediaDiscoverQuery, useDoubanListQuery, useTmdbSearchQuery } from '@/hooks/queries/media'
import type { DoubanCategory, DoubanListItem, TMDBBrief } from '@/types/media'

const emit = defineEmits<{
  'add-task': [payload: { tmdb_id: number; tmdb_media_type: 'movie' | 'tv'; taskname: string }]
}>()

const props = defineProps<{ initialQuery?: string; trackedKeys?: Set<string> }>()

const TMDB_IMAGE_BASE = 'https://image.tmdb.org/t/p/w342'

// View mode: douban browse or tmdb search
const viewMode = ref<'douban' | 'tmdb'>('douban')

// Douban state
const mainCategory = ref('')
const subCategory = ref('')
const doubanStart = ref(0)
const PAGE_LIMIT = 20

// TMDB search state
const searchInput = ref('')
const searchQuery = ref('')
const searchType = ref('multi')
const searchPage = ref(1)

// Queries
const { data: categoriesData, isLoading: categoriesLoading } = useMediaDiscoverQuery()
const { data: doubanData, isLoading: doubanLoading, isFetching: doubanFetching } = useDoubanListQuery(
  mainCategory,
  subCategory,
  doubanStart,
  PAGE_LIMIT,
)
const { data: tmdbData, isLoading: tmdbLoading, isFetching: tmdbFetching } = useTmdbSearchQuery(
  searchQuery,
  searchType,
  searchPage,
)

const categories = computed<DoubanCategory[]>(() => categoriesData.value?.categories || [])
const currentCategory = computed(() => categories.value.find((c) => c.key === mainCategory.value) || null)
const subOptions = computed(() => currentCategory.value?.subs || [])

const doubanItems = computed<DoubanListItem[]>(() => doubanData.value?.items || [])
const doubanTotal = computed(() => doubanData.value?.total || 0)

const tmdbItems = computed<TMDBBrief[]>(() => tmdbData.value?.items || [])
const tmdbTotalPages = computed(() => tmdbData.value?.total_pages || 0)

// Auto-select first category
watch(categories, (cats) => {
  if (cats.length > 0 && !mainCategory.value) {
    mainCategory.value = cats[0].key
  }
}, { immediate: true })

// Prefill search from an external initial query (e.g. handed off from home page)
watch(() => props.initialQuery, (q) => {
  const value = String(q || '').trim()
  if (!value) return
  searchInput.value = value
  searchQuery.value = value
  searchPage.value = 1
  viewMode.value = 'tmdb'
}, { immediate: true })

function selectMainCategory(key: string) {
  mainCategory.value = key
  subCategory.value = ''
  doubanStart.value = 0
}

function selectSubCategory(key: string) {
  subCategory.value = key
  doubanStart.value = 0
}

function doubanNextPage() {
  doubanStart.value += PAGE_LIMIT
}

function doubanPrevPage() {
  doubanStart.value = Math.max(0, doubanStart.value - PAGE_LIMIT)
}

function doSearch() {
  const q = searchInput.value.trim()
  if (!q) return
  searchQuery.value = q
  searchPage.value = 1
  viewMode.value = 'tmdb'
}

function tmdbNextPage() {
  if (searchPage.value < tmdbTotalPages.value) {
    searchPage.value++
  }
}

function tmdbPrevPage() {
  if (searchPage.value > 1) {
    searchPage.value--
  }
}

function switchToDouban() {
  viewMode.value = 'douban'
}

function switchToTmdb() {
  viewMode.value = 'tmdb'
}

// Poster helpers
function bestDoubanPoster(item: DoubanListItem) {
  const url = String(item.pic?.normal || '').trim()
  if (!url) return ''
  if (!/^https?:\/\//i.test(url)) return url
  return `/api/media/proxy-image?url=${encodeURIComponent(url)}`
}

function tmdbPoster(path?: string | null) {
  if (!path) return ''
  return `${TMDB_IMAGE_BASE}${path}`
}

function bestTmdbTitle(item: TMDBBrief) {
  return item.media_type === 'movie'
    ? (item.title || item.original_title || '')
    : (item.name || item.original_name || '')
}

function tmdbYear(item: TMDBBrief) {
  const date = item.media_type === 'movie' ? item.release_date : item.first_air_date
  return String(date || '').substring(0, 4)
}

// One-click add task
function handleAddFromDouban(item: DoubanListItem) {
  // If the item has tmdb data attached
  if (item.tmdb?.id) {
    const mt = String(item.tmdb.media_type || 'tv').toLowerCase()
    emit('add-task', {
      tmdb_id: Number(item.tmdb.id),
      tmdb_media_type: (mt === 'movie' ? 'movie' : 'tv') as 'movie' | 'tv',
      taskname: item.title || '',
    })
    return
  }
  // Otherwise try to use the category media_type
  const mt = String(currentCategory.value?.media_type || 'tv').toLowerCase()
  emit('add-task', {
    tmdb_id: 0,
    tmdb_media_type: (mt === 'movie' ? 'movie' : 'tv') as 'movie' | 'tv',
    taskname: item.title || '',
  })
}

function handleAddFromTmdb(item: TMDBBrief) {
  const mt = String(item.media_type || '').toLowerCase()
  if (mt !== 'movie' && mt !== 'tv') return
  emit('add-task', {
    tmdb_id: Number(item.id) || 0,
    tmdb_media_type: mt as 'movie' | 'tv',
    taskname: bestTmdbTitle(item),
  })
}

// Whether an item already has a drama task (for edit vs add button state)
function doubanTracked(item: DoubanListItem): boolean {
  const id = Number(item.tmdb?.id) || 0
  if (!id) return false
  const mt = String(item.tmdb?.media_type || 'tv').toLowerCase()
  return props.trackedKeys?.has(`${mt}:${id}`) ?? false
}

function tmdbTracked(item: TMDBBrief): boolean {
  const id = Number(item.id) || 0
  if (!id) return false
  const mt = String(item.media_type || '').toLowerCase()
  if (mt !== 'movie' && mt !== 'tv') return false
  return props.trackedKeys?.has(`${mt}:${id}`) ?? false
}
</script>

<template>
  <div class="space-y-4">
    <!-- Search bar -->
    <div class="flex items-center gap-3">
      <div class="relative flex-1 max-w-md">
        <Search class="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-[hsl(var(--muted-foreground))]" />
        <Input
          v-model="searchInput"
          placeholder="搜索影视（TMDB）..."
          class="pl-9"
          @keydown.enter="doSearch"
        />
      </div>
      <Button size="sm" @click="doSearch" :disabled="!searchInput.trim()">
        搜索
      </Button>
    </div>

    <!-- View toggle -->
    <div class="flex items-center gap-2">
      <Button
        size="sm"
        :variant="viewMode === 'douban' ? 'default' : 'outline'"
        @click="switchToDouban"
      >
        豆瓣分类
      </Button>
      <Button
        size="sm"
        :variant="viewMode === 'tmdb' ? 'default' : 'outline'"
        @click="switchToTmdb"
        :disabled="!searchQuery"
      >
        TMDB 搜索
      </Button>
    </div>

    <!-- Douban browse mode -->
    <div v-if="viewMode === 'douban'">
      <!-- Category tabs -->
      <div v-if="categoriesLoading" class="flex gap-1 border-b border-[hsl(var(--border))]">
        <div v-for="i in 5" :key="i" class="h-9 w-16 animate-pulse rounded-t bg-[hsl(var(--muted))]" />
      </div>
      <div v-else class="flex gap-1 border-b border-[hsl(var(--border))]">
        <button
          v-for="cat in categories"
          :key="cat.key"
          @click="selectMainCategory(cat.key)"
          :class="[
            'relative px-4 py-2 text-sm transition-colors whitespace-nowrap',
            mainCategory === cat.key
              ? 'text-[hsl(var(--primary))] font-medium after:absolute after:bottom-0 after:left-0 after:right-0 after:h-0.5 after:bg-[hsl(var(--primary))] after:rounded-t'
              : 'text-[hsl(var(--muted-foreground))] hover:text-[hsl(var(--foreground))]'
          ]"
        >
          {{ cat.label }}
        </button>
      </div>

      <!-- Sub categories -->
      <div v-if="subOptions.length > 0" class="flex flex-wrap gap-1.5 mb-4 mt-3">
        <Badge
          v-for="sub in subOptions"
          :key="sub.key"
          class="cursor-pointer select-none transition-colors"
          :variant="subCategory === sub.key ? 'default' : 'outline'"
          :class="subCategory === sub.key
            ? 'bg-[hsl(var(--primary))] text-[hsl(var(--primary-foreground))] hover:bg-[hsl(var(--primary)/.9)]'
            : 'hover:bg-[hsl(var(--accent))]'"
          @click="selectSubCategory(sub.key === subCategory ? '' : sub.key)"
        >
          {{ sub.label }}
        </Badge>
      </div>

      <!-- Loading indicator -->
      <div v-if="doubanLoading && !doubanItems.length" class="grid grid-cols-2 gap-4 md:grid-cols-4 lg:grid-cols-6">
        <div v-for="i in 12" :key="i" class="space-y-2">
          <div class="aspect-[2/3] animate-pulse rounded-lg bg-[hsl(var(--muted))]" />
          <div class="h-4 w-3/4 animate-pulse rounded bg-[hsl(var(--muted))]" />
        </div>
      </div>

      <!-- Douban item grid -->
      <div v-else class="grid grid-cols-2 gap-4 md:grid-cols-4 lg:grid-cols-6">
        <div
          v-for="item in doubanItems"
          :key="item.id"
          class="group relative flex flex-col overflow-hidden rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))] transition-shadow hover:shadow-md"
        >
          <!-- Poster -->
          <div class="relative aspect-[2/3] overflow-hidden bg-[hsl(var(--muted))]">
            <img
              v-if="bestDoubanPoster(item)"
              :src="bestDoubanPoster(item)"
              :alt="item.title"
              class="h-full w-full object-cover"
              loading="lazy"
            />
            <div v-else class="flex h-full items-center justify-center">
              <Film class="h-8 w-8 text-[hsl(var(--muted-foreground)/.4)]" />
            </div>
            <!-- Overlay with add button -->
            <div class="absolute inset-0 flex items-end justify-center pb-4 bg-gradient-to-t from-black/60 via-black/20 to-transparent opacity-0 transition-opacity group-hover:opacity-100 [@media(hover:none)]:opacity-100">
              <Button 
                size="sm" 
                class="gap-1 bg-white text-black shadow-lg hover:bg-white/90 border-0"
                @click.stop="handleAddFromDouban(item)"
              >
                <component :is="doubanTracked(item) ? Pencil : Plus" class="h-3.5 w-3.5" />
                {{ doubanTracked(item) ? '编辑' : '追剧' }}
              </Button>
            </div>
          </div>
          <!-- Info -->
          <div class="flex flex-col gap-0.5 p-2">
            <p class="truncate text-sm font-medium text-[hsl(var(--foreground))]">{{ item.title }}</p>
            <div class="flex items-center gap-1.5 text-xs text-[hsl(var(--muted-foreground))]">
              <span v-if="item.rating?.value" class="text-amber-500 font-medium">
                {{ item.rating.value }}
              </span>
              <span v-if="item.year">{{ item.year }}</span>
            </div>
          </div>
        </div>
      </div>

      <!-- Fetching overlay -->
      <div v-if="doubanFetching && doubanItems.length" class="mt-2 flex items-center gap-2 text-xs text-[hsl(var(--muted-foreground))]">
        <Loader2 class="h-3 w-3 animate-spin" />
        加载中...
      </div>

      <!-- Pagination -->
      <div v-if="doubanItems.length" class="mt-4 flex items-center justify-between">
        <Button size="sm" variant="outline" :disabled="doubanStart === 0" @click="doubanPrevPage">
          上一页
        </Button>
        <span class="text-xs text-[hsl(var(--muted-foreground))]">
          {{ doubanStart + 1 }}-{{ Math.min(doubanStart + PAGE_LIMIT, doubanTotal) }} / {{ doubanTotal }}
        </span>
        <Button size="sm" variant="outline" :disabled="doubanStart + PAGE_LIMIT >= doubanTotal" @click="doubanNextPage">
          下一页
        </Button>
      </div>
    </div>

    <!-- TMDB search mode -->
    <div v-if="viewMode === 'tmdb'">
      <!-- Loading -->
      <div v-if="tmdbLoading && !tmdbItems.length" class="grid grid-cols-2 gap-4 md:grid-cols-4 lg:grid-cols-6">
        <div v-for="i in 12" :key="i" class="space-y-2">
          <div class="aspect-[2/3] animate-pulse rounded-lg bg-[hsl(var(--muted))]" />
          <div class="h-4 w-3/4 animate-pulse rounded bg-[hsl(var(--muted))]" />
        </div>
      </div>

      <!-- Empty -->
      <div v-else-if="!tmdbItems.length && searchQuery" class="flex flex-col items-center justify-center py-12">
        <Film class="mb-3 h-10 w-10 text-[hsl(var(--muted-foreground))]" />
        <p class="text-sm text-[hsl(var(--muted-foreground))]">未找到「{{ searchQuery }}」的结果</p>
      </div>

      <!-- TMDB grid -->
      <div v-else class="grid grid-cols-2 gap-4 md:grid-cols-4 lg:grid-cols-6">
        <div
          v-for="item in tmdbItems"
          :key="item.id ?? bestTmdbTitle(item)"
          class="group relative flex flex-col overflow-hidden rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))] transition-shadow hover:shadow-md"
        >
          <!-- Poster -->
          <div class="relative aspect-[2/3] overflow-hidden bg-[hsl(var(--muted))]">
            <img
              v-if="tmdbPoster(item.poster_path)"
              :src="tmdbPoster(item.poster_path)"
              :alt="bestTmdbTitle(item)"
              class="h-full w-full object-cover"
              loading="lazy"
            />
            <div v-else class="flex h-full items-center justify-center">
              <Film class="h-8 w-8 text-[hsl(var(--muted-foreground)/.4)]" />
            </div>
            <!-- Overlay -->
            <div class="absolute inset-0 flex items-end justify-center pb-4 bg-gradient-to-t from-black/60 via-black/20 to-transparent opacity-0 transition-opacity group-hover:opacity-100 [@media(hover:none)]:opacity-100">
              <Button
                size="sm"
                class="gap-1 bg-white text-black shadow-lg hover:bg-white/90 border-0"
                :disabled="item.media_type !== 'movie' && item.media_type !== 'tv'"
                @click.stop="handleAddFromTmdb(item)"
              >
                <component :is="tmdbTracked(item) ? Pencil : Plus" class="h-3.5 w-3.5" />
                {{ tmdbTracked(item) ? '编辑' : '追剧' }}
              </Button>
            </div>
            <!-- Media type badge -->
            <Badge
              v-if="item.media_type"
              class="absolute top-1.5 left-1.5 text-[10px]"
              variant="secondary"
            >
              {{ item.media_type === 'movie' ? '电影' : 'TV' }}
            </Badge>
          </div>
          <!-- Info -->
          <div class="flex flex-col gap-0.5 p-2">
            <p class="truncate text-sm font-medium text-[hsl(var(--foreground))]">
              {{ bestTmdbTitle(item) }}
            </p>
            <div class="flex items-center gap-1.5 text-xs text-[hsl(var(--muted-foreground))]">
              <span v-if="item.vote_average" class="text-amber-500 font-medium">
                {{ Number(item.vote_average).toFixed(1) }}
              </span>
              <span v-if="tmdbYear(item)">{{ tmdbYear(item) }}</span>
            </div>
            <p v-if="item.overview" class="mt-1 line-clamp-2 text-[11px] leading-tight text-[hsl(var(--muted-foreground))]">
              {{ item.overview }}
            </p>
          </div>
        </div>
      </div>

      <!-- Fetching overlay -->
      <div v-if="tmdbFetching && tmdbItems.length" class="mt-2 flex items-center gap-2 text-xs text-[hsl(var(--muted-foreground))]">
        <Loader2 class="h-3 w-3 animate-spin" />
        加载中...
      </div>

      <!-- Pagination -->
      <div v-if="tmdbItems.length && tmdbTotalPages > 1" class="mt-4 flex items-center justify-between">
        <Button size="sm" variant="outline" :disabled="searchPage <= 1" @click="tmdbPrevPage">
          上一页
        </Button>
        <span class="text-xs text-[hsl(var(--muted-foreground))]">
          第 {{ searchPage }} / {{ tmdbTotalPages }} 页
        </span>
        <Button size="sm" variant="outline" :disabled="searchPage >= tmdbTotalPages" @click="tmdbNextPage">
          下一页
        </Button>
      </div>
    </div>
  </div>
</template>
