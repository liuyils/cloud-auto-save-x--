import { useQuery } from '@tanstack/vue-query'
import { fetchCapacityOverview, fetchDramaOverview } from '@/api/dashboard'

export function useDashboardCapacityQuery() {
  return useQuery({
    queryKey: ['dashboard', 'capacity'],
    queryFn: () => fetchCapacityOverview(),
  })
}

export function useDashboardDramaOverviewQuery(days = 30) {
  return useQuery({
    queryKey: ['dashboard', 'drama-overview', days],
    queryFn: () => fetchDramaOverview(days),
  })
}
