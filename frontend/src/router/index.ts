import { createRouter, createWebHistory } from 'vue-router'

const routes = [
  { path: '/', redirect: '/blocks' },
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
]

export default createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes,
})
