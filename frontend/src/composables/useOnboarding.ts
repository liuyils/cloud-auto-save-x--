import { reactive, computed } from 'vue'

// Bump the version suffix whenever the tour content changes materially and you
// want every user to see the refreshed walkthrough again.
const STORAGE_PREFIX = 'casx:onboarding:v1:'

const state = reactive({
  open: false,
  stepIndex: 0,
  userKey: 'anon' as string,
})

function storageKey(userKey: string): string {
  return `${STORAGE_PREFIX}${userKey}`
}

function hasSeen(userKey: string): boolean {
  try {
    return localStorage.getItem(storageKey(userKey)) === '1'
  } catch {
    // Storage unavailable (private mode / SSR) — don't nag the user.
    return true
  }
}

function markSeen(userKey: string): void {
  try {
    localStorage.setItem(storageKey(userKey), '1')
  } catch {
    // ignore
  }
}

/**
 * First-visit product tour state. Persistence is scoped per user id so the
 * walkthrough only auto-shows once per account on a given device, while still
 * allowing a manual replay at any time.
 */
export function useOnboarding() {
  function setUser(userId: number | string | null | undefined): void {
    state.userKey = userId != null && userId !== '' ? String(userId) : 'anon'
  }

  function start(): void {
    state.stepIndex = 0
    state.open = true
  }

  /** Auto-open the tour on first visit for the given user (no-op if already seen). */
  function maybeAutoStart(userId?: number | string | null): void {
    if (userId !== undefined) setUser(userId)
    if (state.open) return
    if (!hasSeen(state.userKey)) start()
  }

  function next(total: number): void {
    if (state.stepIndex < total - 1) state.stepIndex += 1
    else finish()
  }

  function prev(): void {
    if (state.stepIndex > 0) state.stepIndex -= 1
  }

  function goTo(index: number): void {
    state.stepIndex = index
  }

  /** Mark as seen and close (used by "完成" / navigation actions). */
  function finish(): void {
    markSeen(state.userKey)
    state.open = false
  }

  /** Same as finish — skipping also counts as "seen" so it won't reappear. */
  function skip(): void {
    finish()
  }

  return {
    isOpen: computed(() => state.open),
    stepIndex: computed(() => state.stepIndex),
    setUser,
    start,
    maybeAutoStart,
    next,
    prev,
    goTo,
    finish,
    skip,
  }
}
