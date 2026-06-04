<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { execApi } from '@/api'

const records = ref<any[]>([])
const loading = ref(false)
const detail = ref<any>(null)
const drawer = ref(false)

async function load() {
  loading.value = true
  try {
    records.value = await execApi.records()
  } finally {
    loading.value = false
  }
}

async function showDetail(id: string) {
  detail.value = await execApi.record(id)
  drawer.value = true
}

const statusType: Record<string, string> = {
  success: 'success',
  failed: 'danger',
  running: 'warning',
  timeout: 'danger',
}

onMounted(load)
</script>

<template>
  <div class="page">
    <header class="page-head">
      <h2>执行历史</h2>
      <el-button :icon="'Refresh'" @click="load">刷新</el-button>
    </header>

    <el-table v-loading="loading" :data="records" class="pf-table" @row-click="(r:any) => showDetail(r.id)">
      <el-table-column prop="id" label="执行 ID" width="300" />
      <el-table-column prop="block_id" label="块 ID" />
      <el-table-column label="状态" width="120">
        <template #default="{ row }">
          <el-tag :type="statusType[row.status] || 'info'" effect="dark">{{ row.status }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="duration_ms" label="耗时(ms)" width="120" />
      <el-table-column prop="created_at" label="时间" />
    </el-table>

    <el-drawer v-model="drawer" title="执行详情" size="46%">
      <div v-if="detail" class="detail">
        <h4>输入</h4>
        <pre>{{ JSON.stringify(detail.inputs, null, 2) }}</pre>
        <h4>返回值</h4>
        <pre>{{ JSON.stringify(detail.output, null, 2) }}</pre>
        <h4>stdout</h4>
        <pre class="log">{{ detail.stdout || '(空)' }}</pre>
        <h4 v-if="detail.stderr">stderr</h4>
        <pre v-if="detail.stderr" class="err">{{ detail.stderr }}</pre>
      </div>
    </el-drawer>
  </div>
</template>

<style scoped>
.page-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 20px;
}
.page-head h2 {
  margin: 0;
}
.pf-table {
  background: transparent;
  cursor: pointer;
}
.detail pre {
  background: var(--pf-panel-2);
  border: 1px solid var(--pf-border);
  border-radius: 8px;
  padding: 10px;
  font-size: 12px;
  white-space: pre-wrap;
  color: var(--pf-text);
}
.detail .err {
  color: #dc2626;
}
.detail .log {
  color: var(--pf-accent-2);
}
</style>
