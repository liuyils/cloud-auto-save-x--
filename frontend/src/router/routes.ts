import type { RouteRecordRaw } from 'vue-router'
import { TASK_READ, SYNC_READ, USER_READ, DRIVE_ACCOUNT_READ } from '@/constants/permissions'

export const appRoutes: RouteRecordRaw[] = [
  {
    path: '/',
    component: () => import('@/layouts/AppLayout.vue'),
    children: [
      {
        path: '',
        name: 'home',
        component: () => import('@/pages/HomePage.vue'),
        meta: { title: '追剧首页' },
      },
      {
        path: 'discover',
        name: 'discover',
        component: () => import('@/pages/DiscoverPage.vue'),
        meta: { title: '影视发现', permission: TASK_READ },
      },
      {
        path: 'tasks',
        name: 'tasks',
        component: () => import('@/pages/TasksPage.vue'),
        meta: { title: '追剧任务', permission: TASK_READ },
      },
      {
        path: 'drama',
        redirect: '/',
      },
      {
        path: 'sync',
        name: 'sync',
        component: () => import('@/pages/SyncPage.vue'),
        meta: { title: '同步', permission: SYNC_READ },
      },
      {
        path: 'drives',
        name: 'drives',
        component: () => import('@/pages/DrivesPage.vue'),
        meta: { title: '网盘账号', permission: DRIVE_ACCOUNT_READ },
      },
      {
        path: 'dl302',
        name: 'dl302',
        component: () => import('@/pages/Dl302Page.vue'),
        meta: { title: '302 代理' },
      },
      {
        path: 'settings',
        name: 'settings',
        component: () => import('@/pages/SettingsPage.vue'),
        meta: { title: '设置' },
      },
      {
        path: 'users',
        name: 'users',
        component: () => import('@/pages/UsersPage.vue'),
        meta: { title: '用户', permission: USER_READ },
      },
    ],
  },
]

export const publicRoutes: RouteRecordRaw[] = [
  {
    path: '/login',
    name: 'login',
    component: () => import('@/pages/LoginPage.vue'),
    meta: { title: '登录' },
  },
  {
    path: '/setup',
    name: 'setup',
    component: () => import('@/pages/SetupPage.vue'),
    meta: { title: '初始化' },
  },
  {
    path: '/403',
    name: 'forbidden',
    component: () => import('@/pages/ForbiddenPage.vue'),
    meta: { title: '无权限' },
  },
]
