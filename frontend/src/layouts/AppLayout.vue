<script setup lang="ts">
import { ref } from 'vue'
import { RouterView } from 'vue-router'
import { X } from 'lucide-vue-next'
import { Sheet } from '@/components/ui/sheet'
import Sidebar from '@/components/layout/Sidebar.vue'
import MobileNav from '@/components/layout/MobileNav.vue'
import Header from '@/components/layout/Header.vue'
import OnboardingTour from '@/components/onboarding/OnboardingTour.vue'

// Desktop sidebar collapsed state
const sidebarCollapsed = ref(false)

// Mobile drawer open state
const mobileDrawerOpen = ref(false)

function toggleSidebar() {
  sidebarCollapsed.value = !sidebarCollapsed.value
}

function openMobileDrawer() {
  mobileDrawerOpen.value = true
}

function closeMobileDrawer() {
  mobileDrawerOpen.value = false
}
</script>

<template>
  <div class="flex h-screen overflow-hidden bg-[hsl(var(--background))]">
    <!-- Desktop sidebar -->
    <div class="hidden md:flex">
      <Sidebar :collapsed="sidebarCollapsed" :on-toggle="toggleSidebar" />
    </div>

    <!-- Mobile drawer (sheet) -->
    <Sheet :open="mobileDrawerOpen" :on-close="closeMobileDrawer">
      <div class="flex h-full flex-col">
        <!-- Close button -->
        <div class="flex h-14 items-center justify-between px-4">
          <span class="text-sm font-semibold text-[hsl(var(--foreground))]">CAS-X</span>
          <button
            class="rounded p-1 text-[hsl(var(--muted-foreground))] transition hover:text-[hsl(var(--foreground))]"
            @click="closeMobileDrawer"
          >
            <X :size="20" />
          </button>
        </div>
        <!-- Sidebar content in drawer -->
        <Sidebar :collapsed="false" :on-toggle="closeMobileDrawer" :hide-header="true" :on-navigate="closeMobileDrawer" />
      </div>
    </Sheet>

    <!-- Main content area -->
    <div class="flex flex-1 flex-col overflow-hidden">
      <Header :on-menu-click="openMobileDrawer" />

      <!-- Page content -->
      <main class="flex-1 overflow-auto pb-14 md:pb-0">
        <RouterView />
      </main>
    </div>

    <!-- Mobile bottom nav -->
    <MobileNav />

    <!-- First-visit product tour (auto-shows once, replayable from sidebar) -->
    <OnboardingTour />
  </div>
</template>
