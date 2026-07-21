import { createRouter, createWebHistory } from 'vue-router'

import { appRoutes, publicRoutes } from './routes'

const PUBLIC_ROUTE_NAMES = new Set(['login', 'setup', 'forbidden'])

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [...appRoutes, ...publicRoutes],
})

router.beforeEach(async (to, _from) => {
  // Set document title
  const title = to.meta?.title as string | undefined
  document.title = title ? `${title} - CAS-X` : 'CAS-X'

  // Lazy-import stores to avoid circular deps at module level
  let setupStore: { initialized: boolean; refreshStatus: (force?: boolean) => Promise<void> } | undefined
  let authStore: { isAuthenticated: boolean; permissions: string[]; initialized: boolean; bootstrap: () => Promise<void> } | undefined

  try {
    const { useSetupStore } = await import('@/stores/setup')
    setupStore = useSetupStore()
  } catch {
    // store not ready yet — skip setup check
  }

  try {
    const { useAuthStore } = await import('@/stores/auth')
    authStore = useAuthStore()
  } catch {
    // store not ready yet — skip auth check
  }

  // 1. Check setup / initialization status
  if (setupStore) {
    try {
      await setupStore.refreshStatus()
    } catch {
      // ignore — treat as initialized to avoid redirect loops
    }
    if (!setupStore.initialized && to.name !== 'setup') {
      return { name: 'setup' }
    }
    // Once initialized, the setup wizard must never be reachable again.
    // This prevents manually re-triggering initialization from the page.
    if (setupStore.initialized && to.name === 'setup') {
      return { name: 'home' }
    }
  }

  // 2. Public routes are always accessible
  if (to.name && PUBLIC_ROUTE_NAMES.has(to.name as string)) {
    return true
  }

  // 3. Bootstrap auth (loads user from refresh token)
  if (authStore) {
    try {
      await authStore.bootstrap()
    } catch {
      // bootstrap failed — fall through to login redirect
    }

    if (!authStore.isAuthenticated) {
      return { name: 'login', query: { redirect: to.fullPath } }
    }

    // 4. Permission check
    const requiredPermission = to.meta?.permission as string | undefined
    if (requiredPermission) {
      const userPermissions = authStore.permissions
      if (!userPermissions.includes(requiredPermission)) {
        return { name: 'forbidden' }
      }
    }
  } else {
    // Auth store unavailable — redirect to login for safety
    return { name: 'login', query: { redirect: to.fullPath } }
  }

  return true
})

export default router
