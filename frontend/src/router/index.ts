import { createRouter, createWebHistory } from 'vue-router'

const routes = [
  { path: '/', redirect: '/dashboard' },
  {
    path: '/login',
    name: 'login',
    component: () => import('@/views/login/Login.vue'),
    meta: { public: true },
  },
  {
    path: '/dashboard',
    name: 'dashboard',
    component: () => import('@/views/dashboard/Dashboard.vue'),
  },
  {
    path: '/blocks',
    name: 'block-library',
    component: () => import('@/views/block-library/BlockLibrary.vue'),
  },
  {
    path: '/blocks/:id',
    name: 'block-editor',
    component: () => import('@/views/block-editor/BlockEditor.vue'),
  },
  {
    path: '/flows',
    name: 'flow-list',
    component: () => import('@/views/flow-editor/FlowList.vue'),
  },
  {
    path: '/flows/:id',
    name: 'flow-editor',
    component: () => import('@/views/flow-editor/FlowEditor.vue'),
  },
  {
    path: '/deployments',
    name: 'deployment-center',
    component: () => import('@/views/deployment-center/DeploymentCenter.vue'),
  },
  {
    path: '/executions',
    name: 'execution-history',
    component: () => import('@/views/execution-history/ExecutionHistory.vue'),
  },
  {
    path: '/mq-monitor',
    name: 'mq-monitor',
    component: () => import('@/views/mq-monitor/MQMonitor.vue'),
  },
  {
    path: '/api-portal',
    name: 'api-portal',
    component: () => import('@/views/api-portal/ApiPortal.vue'),
  },
  {
    path: '/api-admin',
    name: 'api-admin',
    component: () => import('@/views/api-admin/ApiAdmin.vue'),
  },
  {
    path: '/platform-settings',
    name: 'platform-settings',
    component: () => import('@/views/platform-settings/PlatformSettings.vue'),
  },
  {
    path: '/rbac-admin',
    name: 'rbac-admin',
    component: () => import('@/views/rbac-admin/RbacAdmin.vue'),
    meta: { requireAdmin: true },
  },
]

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes,
})

// 全局路由守卫
router.beforeEach(async (to, _from, next) => {
  // 公开路由直接放行
  if (to.meta.public) return next()

  const token = localStorage.getItem('pyflow_token')

  // 未登录 → 跳到登录页
  if (!token) {
    return next({ path: '/login', query: { redirect: to.fullPath } })
  }

  // 已登录用户访问登录页 → 回到首页
  if (to.path === '/login') {
    return next('/')
  }

  next()
})

export default router
