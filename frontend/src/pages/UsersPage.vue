<script setup lang="ts">
import { ref, computed } from 'vue'
import { useQuery, useMutation, useQueryClient } from '@tanstack/vue-query'
import { UserPlus, Users, Shield, ShieldCheck, Search, UserCircle, CheckSquare } from 'lucide-vue-next'

import {
  fetchUsers,
  createUser,
  setUserStatus,
  setUserRoles,
  fetchRoles,
  batchSetUserStatus,
  batchSetUserRoles,
} from '@/api/users'
import type { UserItem, RoleItem } from '@/types/user'
import { Card, CardContent, CardHeader } from '@/components/ui/card'
import Button from '@/components/ui/button/Button.vue'
import Badge from '@/components/ui/badge/Badge.vue'
import Input from '@/components/ui/input/Input.vue'
import { useAuthStore } from '@/stores/auth'
import { useToast } from '@/composables/useToast'
import { USER_WRITE } from '@/constants/permissions'

const { toast } = useToast()
const authStore = useAuthStore()
const queryClient = useQueryClient()

const canWrite = computed(() => authStore.permissions.includes(USER_WRITE))

const page = ref(1)
const pageSize = ref(20)
const searchQuery = ref('')
const showCreateDialog = ref(false)

// Multi-select
const selectedIds = ref<Set<number>>(new Set())
const selectedCount = computed(() => selectedIds.value.size)
const allSelected = computed(() => users.value.length > 0 && users.value.every(u => selectedIds.value.has(u.id)))

function toggleSelectAll() {
  if (allSelected.value) {
    selectedIds.value = new Set()
  } else {
    selectedIds.value = new Set(users.value.map(u => u.id))
  }
}

function toggleSelect(userId: number) {
  const next = new Set(selectedIds.value)
  if (next.has(userId)) {
    next.delete(userId)
  } else {
    next.add(userId)
  }
  selectedIds.value = next
}

// Create user form
const newUsername = ref('')
const newEmail = ref('')
const newPassword = ref('')
const createError = ref('')
const createLoading = ref(false)

// Role assignment dialog
const roleDialogVisible = ref(false)
const roleDialogTitle = ref('分配角色')
const roleDialogUserId = ref<number | null>(null)
const roleDialogSelectedIds = ref<Set<number>>(new Set())
const roleDialogLoading = ref(false)

// Queries
const { data: usersData, isLoading } = useQuery({
  queryKey: computed(() => ['users', page.value, pageSize.value, searchQuery.value]),
  queryFn: () => fetchUsers({ page: page.value, page_size: pageSize.value, q: searchQuery.value || undefined }),
})

const { data: rolesData } = useQuery({
  queryKey: ['roles'],
  queryFn: () => fetchRoles(),
})

const users = computed(() => usersData.value?.items ?? [])
const total = computed(() => usersData.value?.total ?? 0)
const activeUserCount = computed(() => users.value.filter((u) => u.is_active).length)
const roles = computed<RoleItem[]>(() =>
  (rolesData.value ?? []).map(r => ({ id: r.id, name: r.name, description: r.description }))
)

// Mutations
const toggleStatusMutation = useMutation({
  mutationFn: ({ userId, isActive }: { userId: number; isActive: boolean }) =>
    setUserStatus(userId, isActive),
  onSuccess: () => {
    queryClient.invalidateQueries({ queryKey: ['users'] })
    toast.success('状态已更新')
  },
  onError: (err: any) => {
    toast.error(err?.response?.data?.detail || err?.message || '操作失败')
  },
})

const batchStatusMutation = useMutation({
  mutationFn: ({ userIds, isActive }: { userIds: number[]; isActive: boolean }) =>
    batchSetUserStatus(userIds, isActive),
  onSuccess: () => {
    queryClient.invalidateQueries({ queryKey: ['users'] })
    selectedIds.value = new Set()
    toast.success('批量状态已更新')
  },
  onError: (err: any) => {
    toast.error(err?.response?.data?.detail || err?.message || '批量操作失败')
  },
})

const setRolesMutation = useMutation({
  mutationFn: ({ userId, roleIds }: { userId: number; roleIds: number[] }) =>
    setUserRoles(userId, roleIds),
  onSuccess: () => {
    queryClient.invalidateQueries({ queryKey: ['users'] })
    roleDialogVisible.value = false
    toast.success('角色分配成功')
  },
  onError: (err: any) => {
    toast.error(err?.response?.data?.detail || err?.message || '角色分配失败')
  },
})

const batchRolesMutation = useMutation({
  mutationFn: ({ userIds, roleIds }: { userIds: number[]; roleIds: number[] }) =>
    batchSetUserRoles(userIds, roleIds),
  onSuccess: () => {
    queryClient.invalidateQueries({ queryKey: ['users'] })
    selectedIds.value = new Set()
    roleDialogVisible.value = false
    toast.success('批量角色分配成功')
  },
  onError: (err: any) => {
    toast.error(err?.response?.data?.detail || err?.message || '批量角色分配失败')
  },
})

function toggleUserStatus(user: UserItem) {
  toggleStatusMutation.mutate({ userId: user.id, isActive: !user.is_active })
}

function handleBatchStatus(isActive: boolean) {
  const ids = Array.from(selectedIds.value)
  if (!ids.length) return
  batchStatusMutation.mutate({ userIds: ids, isActive })
}

function openRoleDialog(user?: UserItem) {
  if (user) {
    roleDialogUserId.value = user.id
    roleDialogTitle.value = `为 ${user.username} 分配角色`
    roleDialogSelectedIds.value = new Set(user.roles.map(r => r.id))
  } else {
    roleDialogUserId.value = null
    roleDialogTitle.value = '批量分配角色'
    roleDialogSelectedIds.value = new Set()
  }
  roleDialogVisible.value = true
}

function toggleRoleSelection(roleId: number) {
  const next = new Set(roleDialogSelectedIds.value)
  if (next.has(roleId)) {
    next.delete(roleId)
  } else {
    next.add(roleId)
  }
  roleDialogSelectedIds.value = next
}

async function submitRoleDialog() {
  const roleIds = Array.from(roleDialogSelectedIds.value)
  roleDialogLoading.value = true
  try {
    if (roleDialogUserId.value) {
      await setRolesMutation.mutateAsync({ userId: roleDialogUserId.value, roleIds })
    } else {
      const userIds = Array.from(selectedIds.value)
      await batchRolesMutation.mutateAsync({ userIds, roleIds })
    }
  } finally {
    roleDialogLoading.value = false
  }
}

function closeRoleDialog() {
  roleDialogVisible.value = false
}

async function handleCreateUser() {
  createError.value = ''
  if (!newUsername.value.trim()) {
    createError.value = '请输入用户名'
    return
  }
  if (!newPassword.value || newPassword.value.length < 6) {
    createError.value = '密码至少 6 位'
    return
  }

  createLoading.value = true
  try {
    await createUser({
      username: newUsername.value.trim(),
      email: newEmail.value.trim() || `${newUsername.value.trim()}@local`,
      password: newPassword.value,
    })
    showCreateDialog.value = false
    newUsername.value = ''
    newEmail.value = ''
    newPassword.value = ''
    queryClient.invalidateQueries({ queryKey: ['users'] })
    toast.success('用户创建成功')
  } catch (e: any) {
    createError.value = e?.response?.data?.detail || e?.message || '创建用户失败'
  } finally {
    createLoading.value = false
  }
}

function closeCreateDialog() {
  showCreateDialog.value = false
  createError.value = ''
  newUsername.value = ''
  newEmail.value = ''
  newPassword.value = ''
}

function getUserInitial(name: string) {
  return name.charAt(0).toUpperCase()
}
</script>

<template>
  <div class="space-y-6 p-6">
    <!-- Header -->
    <div class="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
      <div>
        <h1 class="text-2xl font-bold" style="color: hsl(var(--foreground))">👥 用户管理</h1>
        <p class="mt-1 text-sm" style="color: hsl(var(--muted-foreground))">
          管理系统用户及其权限
        </p>
      </div>
      <Button v-if="canWrite" @click="showCreateDialog = true">
        <UserPlus class="mr-2 h-4 w-4" />
        添加用户
      </Button>
    </div>

    <!-- Stat tiles -->
    <div class="grid grid-cols-3 gap-3">
      <div class="glass-tile">
        <div class="glass-tile__top">
          <span class="glass-tile__emoji">👤</span>
          <span class="glass-tile__label">用户总数</span>
        </div>
        <div class="glass-tile__value">{{ total }}</div>
      </div>
      <div class="glass-tile">
        <div class="glass-tile__top">
          <span class="glass-tile__emoji">✅</span>
          <span class="glass-tile__label">已启用</span>
        </div>
        <div class="glass-tile__value">{{ activeUserCount }}</div>
      </div>
      <div class="glass-tile">
        <div class="glass-tile__top">
          <span class="glass-tile__emoji">🛡️</span>
          <span class="glass-tile__label">角色数</span>
        </div>
        <div class="glass-tile__value">{{ roles.length }}</div>
      </div>
    </div>

    <!-- Search -->
    <div class="relative max-w-sm">
      <Search
        class="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2"
        style="color: hsl(var(--muted-foreground))"
      />
      <Input
        v-model="searchQuery"
        placeholder="搜索用户..."
        class="pl-9"
      />
    </div>

    <!-- Batch Action Bar -->
    <div
      v-if="canWrite && selectedCount > 0"
      class="flex items-center gap-3 rounded-lg border px-4 py-3"
      style="border-color: hsl(var(--primary) / 0.3); background: hsl(var(--primary) / 0.05)"
    >
      <CheckSquare class="h-4 w-4" style="color: hsl(var(--primary))" />
      <span class="text-sm font-medium" style="color: hsl(var(--foreground))">
        已选择 {{ selectedCount }} 个用户
      </span>
      <div class="ml-auto flex items-center gap-2">
        <Button variant="outline" size="sm" @click="handleBatchStatus(true)">
          批量启用
        </Button>
        <Button variant="outline" size="sm" @click="handleBatchStatus(false)">
          批量禁用
        </Button>
        <Button variant="outline" size="sm" @click="openRoleDialog()">
          批量分配角色
        </Button>
      </div>
    </div>

    <!-- Loading -->
    <div v-if="isLoading" class="flex items-center justify-center py-20">
      <svg class="h-8 w-8 animate-spin" style="color: hsl(var(--primary))" viewBox="0 0 24 24" fill="none">
        <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4" />
        <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
      </svg>
    </div>

    <!-- Empty State -->
    <div
      v-else-if="users.length === 0"
      class="flex flex-col items-center justify-center rounded-lg border py-16"
      style="border-color: hsl(var(--border)); border-style: dashed"
    >
      <Users class="mb-4 h-12 w-12" style="color: hsl(var(--muted-foreground))" />
      <p class="text-sm font-medium" style="color: hsl(var(--muted-foreground))">
        {{ searchQuery ? '未找到匹配的用户' : '暂无用户' }}
      </p>
      <Button v-if="!searchQuery && canWrite" variant="outline" class="mt-4" @click="showCreateDialog = true">
        <UserPlus class="mr-2 h-4 w-4" />
        添加第一个用户
      </Button>
    </div>

    <!-- User Table -->
    <div v-else class="overflow-hidden rounded-lg border" style="border-color: hsl(var(--border))">
      <table class="w-full text-sm">
        <thead>
          <tr style="background: hsl(var(--muted) / 0.5); border-bottom: 1px solid hsl(var(--border))">
            <th v-if="canWrite" class="w-12 px-4 py-3 text-left">
              <input
                type="checkbox"
                class="h-4 w-4 rounded border-[hsl(var(--border))]"
                :checked="allSelected"
                @change="toggleSelectAll"
              />
            </th>
            <th class="px-4 py-3 text-left font-medium" style="color: hsl(var(--muted-foreground))">用户</th>
            <th class="px-4 py-3 text-left font-medium" style="color: hsl(var(--muted-foreground))">邮箱</th>
            <th class="px-4 py-3 text-left font-medium" style="color: hsl(var(--muted-foreground))">角色</th>
            <th class="px-4 py-3 text-left font-medium" style="color: hsl(var(--muted-foreground))">状态</th>
            <th v-if="canWrite" class="px-4 py-3 text-right font-medium" style="color: hsl(var(--muted-foreground))">操作</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="user in users"
            :key="user.id"
            class="border-t transition-colors hover:bg-[hsl(var(--muted)/0.3)]"
            style="border-color: hsl(var(--border))"
          >
            <!-- Checkbox -->
            <td v-if="canWrite" class="px-4 py-3">
              <input
                type="checkbox"
                class="h-4 w-4 rounded border-[hsl(var(--border))]"
                :checked="selectedIds.has(user.id)"
                @change="toggleSelect(user.id)"
              />
            </td>

            <!-- User Info -->
            <td class="px-4 py-3">
              <div class="flex items-center gap-3">
                <div
                  class="flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-xs font-semibold"
                  :style="{
                    background: user.is_active ? 'hsl(var(--primary) / 0.1)' : 'hsl(var(--muted))',
                    color: user.is_active ? 'hsl(var(--primary))' : 'hsl(var(--muted-foreground))',
                  }"
                >
                  {{ getUserInitial(user.username) }}
                </div>
                <span class="font-medium" style="color: hsl(var(--foreground))">{{ user.username }}</span>
              </div>
            </td>

            <!-- Email -->
            <td class="px-4 py-3" style="color: hsl(var(--muted-foreground))">
              {{ user.email }}
            </td>

            <!-- Roles -->
            <td class="px-4 py-3">
              <div class="flex flex-wrap gap-1">
                <Badge
                  v-for="role in user.roles"
                  :key="role.id"
                  :variant="role.name === 'admin' ? 'default' : 'secondary'"
                  class="text-xs"
                >
                  <ShieldCheck v-if="role.name === 'admin'" class="mr-1 h-3 w-3" />
                  <Shield v-else class="mr-1 h-3 w-3" />
                  {{ role.name }}
                </Badge>
                <span
                  v-if="!user.roles.length"
                  class="text-xs"
                  style="color: hsl(var(--muted-foreground))"
                >
                  无角色
                </span>
              </div>
            </td>

            <!-- Status -->
            <td class="px-4 py-3">
              <Badge :variant="user.is_active ? 'default' : 'destructive'" class="text-xs">
                {{ user.is_active ? '启用' : '已禁用' }}
              </Badge>
            </td>

            <!-- Actions -->
            <td v-if="canWrite" class="px-4 py-3 text-right">
              <div class="flex items-center justify-end gap-2">
                <Button
                  variant="outline"
                  size="sm"
                  @click="openRoleDialog(user)"
                >
                  分配角色
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  @click="toggleUserStatus(user)"
                >
                  {{ user.is_active ? '禁用' : '启用' }}
                </Button>
              </div>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- Pagination -->
    <div
      v-if="total > pageSize"
      class="flex items-center justify-between pt-2 text-sm"
      style="color: hsl(var(--muted-foreground))"
    >
      <span>共 {{ total }} 个用户</span>
      <div class="flex gap-2">
        <Button variant="outline" size="sm" :disabled="page <= 1" @click="page--">上一页</Button>
        <Button variant="outline" size="sm" :disabled="page * pageSize >= total" @click="page++">下一页</Button>
      </div>
    </div>

    <!-- Create User Dialog -->
    <Teleport to="body">
      <div
        v-if="showCreateDialog"
        class="fixed inset-0 z-50 flex items-center justify-center p-4"
        @click.self="closeCreateDialog"
      >
        <div
          class="absolute inset-0 bg-black/50"
          @click="closeCreateDialog"
        />
        <Card class="relative z-10 w-full max-w-md">
          <CardHeader>
            <div class="flex items-center gap-2">
              <UserCircle class="h-5 w-5" style="color: hsl(var(--primary))" />
              <h2 class="text-lg font-semibold" style="color: hsl(var(--foreground))">添加用户</h2>
            </div>
          </CardHeader>
          <CardContent class="space-y-4">
            <div
              v-if="createError"
              class="rounded-md px-3 py-2 text-sm"
              style="background: hsl(var(--destructive) / 0.1); color: hsl(var(--destructive))"
            >
              {{ createError }}
            </div>
            <div class="space-y-2">
              <label class="text-sm font-medium" style="color: hsl(var(--foreground))">用户名</label>
              <Input v-model="newUsername" placeholder="请输入用户名" :disabled="createLoading" />
            </div>
            <div class="space-y-2">
              <label class="text-sm font-medium" style="color: hsl(var(--foreground))">邮箱（可选）</label>
              <Input v-model="newEmail" placeholder="user@example.com" :disabled="createLoading" />
            </div>
            <div class="space-y-2">
              <label class="text-sm font-medium" style="color: hsl(var(--foreground))">密码</label>
              <Input v-model="newPassword" type="password" placeholder="至少 6 位" :disabled="createLoading" />
            </div>
            <div class="flex justify-end gap-3 pt-2">
              <Button variant="outline" :disabled="createLoading" @click="closeCreateDialog">取消</Button>
              <Button :disabled="createLoading" @click="handleCreateUser">
                <template v-if="createLoading">
                  <svg class="mr-2 h-4 w-4 animate-spin" viewBox="0 0 24 24" fill="none">
                    <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4" />
                    <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                  </svg>
                  创建中...
                </template>
                <template v-else>确认创建</template>
              </Button>
            </div>
          </CardContent>
        </Card>
      </div>
    </Teleport>

    <!-- Role Assignment Dialog -->
    <Teleport to="body">
      <div
        v-if="roleDialogVisible"
        class="fixed inset-0 z-50 flex items-center justify-center p-4"
        @click.self="closeRoleDialog"
      >
        <div
          class="absolute inset-0 bg-black/50"
          @click="closeRoleDialog"
        />
        <Card class="relative z-10 w-full max-w-md">
          <CardHeader>
            <div class="flex items-center gap-2">
              <Shield class="h-5 w-5" style="color: hsl(var(--primary))" />
              <h2 class="text-lg font-semibold" style="color: hsl(var(--foreground))">{{ roleDialogTitle }}</h2>
            </div>
          </CardHeader>
          <CardContent class="space-y-4">
            <p class="text-sm" style="color: hsl(var(--muted-foreground))">
              选择要分配的角色：
            </p>

            <div v-if="roles.length === 0" class="py-4 text-center text-sm" style="color: hsl(var(--muted-foreground))">
              暂无可用角色
            </div>

            <div v-else class="space-y-2">
              <label
                v-for="role in roles"
                :key="role.id"
                class="flex cursor-pointer items-center gap-3 rounded-md border px-3 py-2.5 transition-colors"
                :style="{
                  borderColor: roleDialogSelectedIds.has(role.id) ? 'hsl(var(--primary))' : 'hsl(var(--border))',
                  background: roleDialogSelectedIds.has(role.id) ? 'hsl(var(--primary) / 0.05)' : 'transparent',
                }"
              >
                <input
                  type="checkbox"
                  class="h-4 w-4 rounded border-[hsl(var(--border))]"
                  :checked="roleDialogSelectedIds.has(role.id)"
                  @change="toggleRoleSelection(role.id)"
                />
                <div class="flex-1">
                  <div class="flex items-center gap-2">
                    <ShieldCheck v-if="role.name === 'admin'" class="h-4 w-4" style="color: hsl(var(--primary))" />
                    <Shield v-else class="h-4 w-4" style="color: hsl(var(--muted-foreground))" />
                    <span class="text-sm font-medium" style="color: hsl(var(--foreground))">{{ role.name }}</span>
                  </div>
                  <p v-if="role.description" class="mt-0.5 text-xs" style="color: hsl(var(--muted-foreground))">
                    {{ role.description }}
                  </p>
                </div>
              </label>
            </div>

            <div class="flex justify-end gap-3 pt-2">
              <Button variant="outline" :disabled="roleDialogLoading" @click="closeRoleDialog">取消</Button>
              <Button :disabled="roleDialogLoading" @click="submitRoleDialog">
                <template v-if="roleDialogLoading">
                  <svg class="mr-2 h-4 w-4 animate-spin" viewBox="0 0 24 24" fill="none">
                    <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4" />
                    <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                  </svg>
                  保存中...
                </template>
                <template v-else>确认分配</template>
              </Button>
            </div>
          </CardContent>
        </Card>
      </div>
    </Teleport>
  </div>
</template>
