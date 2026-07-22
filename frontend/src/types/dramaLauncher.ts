export type DramaTaskPreset = {
  taskname: string
  tmdb_id?: number | null
  tmdb_media_type: 'movie' | 'tv'
  open_tmdb_search?: boolean
  tmdb_search_query?: string
  tmdb_search_reason?: 'not-configured' | 'no-match' | 'ambiguous' | null
}

export type DramaTmdbMatchResult = {
  configured: boolean
  resolved?: DramaTaskPreset | null
  manualSearch?: DramaTaskPreset | null
  reason?: 'not-configured' | 'no-match' | 'ambiguous' | null
}
