<script setup lang="ts">
import { ref } from 'vue'
import { useRoute } from 'vue-router'

const route = useRoute()
const collapsed = ref(false)

const menus = [
  { path: '/blocks', label: '调用块', icon: 'Grid' },
  { path: '/flows', label: '流程编排', icon: 'Share' },
  { path: '/deployments', label: '部署中心', icon: 'Promotion' },
  { path: '/executions', label: '执行历史', icon: 'Histogram' },
]
</script>

<template>
  <div class="layout">
    <aside class="sidebar" :class="{ collapsed }">
      <div class="brand">
        <span class="logo">⚡</span>
        <transition name="fade">
          <span v-if="!collapsed" class="brand-name">PyFlowHub</span>
        </transition>
      </div>
      <nav class="nav">
        <router-link
          v-for="m in menus"
          :key="m.path"
          :to="m.path"
          class="nav-item"
          :class="{ active: route.path.startsWith(m.path) }"
        >
          <el-icon><component :is="m.icon" /></el-icon>
          <transition name="fade">
            <span v-if="!collapsed" class="nav-label">{{ m.label }}</span>
          </transition>
        </router-link>
      </nav>
      <div class="collapse-btn" @click="collapsed = !collapsed">
        <el-icon><component :is="collapsed ? 'Expand' : 'Fold'" /></el-icon>
      </div>
    </aside>
    <main class="content">
      <router-view v-slot="{ Component }">
        <transition name="fade" mode="out-in">
          <component :is="Component" />
        </transition>
      </router-view>
    </main>
  </div>
</template>

<style scoped>
.layout {
  display: flex;
  height: 100%;
}
.sidebar {
  width: 220px;
  background: var(--pf-panel);
  border-right: 1px solid var(--pf-border);
  box-shadow: var(--pf-shadow-sm);
  display: flex;
  flex-direction: column;
  transition: width 0.28s cubic-bezier(0.4, 0, 0.2, 1);
}
.sidebar.collapsed {
  width: 68px;
}
.brand {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 20px 18px;
  font-size: 20px;
  font-weight: 700;
}
.logo {
  font-size: 24px;
}
.brand-name {
  color: var(--pf-text);
  letter-spacing: 0.2px;
}
.nav {
  flex: 1;
  padding: 8px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.nav-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 14px;
  border-radius: 10px;
  color: var(--pf-text-dim);
  text-decoration: none;
  transition: background 0.2s ease, color 0.2s ease, transform 0.15s ease;
}
.nav-item:hover {
  background: var(--pf-panel-2);
  color: var(--pf-text);
  transform: translateX(3px);
}
.nav-item.active {
  background: var(--pf-accent-soft);
  color: var(--pf-accent);
  box-shadow: inset 3px 0 0 var(--pf-accent);
}
.collapse-btn {
  padding: 14px;
  cursor: pointer;
  color: var(--pf-text-dim);
  border-top: 1px solid var(--pf-border);
  transition: color 0.2s ease;
}
.collapse-btn:hover {
  color: var(--pf-accent);
}
.content {
  flex: 1;
  overflow: auto;
  padding: 24px;
}
</style>
