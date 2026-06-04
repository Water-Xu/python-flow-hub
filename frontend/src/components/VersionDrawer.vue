<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { versionApi } from '../api'
import DiffEditor from './DiffEditor.vue'

const props = defineProps<{
  modelValue: boolean
  resourceType: 'block' | 'flow'
  resourceId: string
  resourceName?: string
}>()
const emit = defineEmits<{ (e: 'update:modelValue', v: boolean): void; (e: 'stable-changed'): void }>()

const visible = computed({
  get: () => props.modelValue,
  set: (v) => emit('update:modelValue', v),
})

const versions = ref<any[]>([])
const loading = ref(false)
const creating = ref(false)
const newTag = ref('')
const newMessage = ref('')

// diff
const fromVersion = ref('')
const toVersion = ref('')
const diffData = ref<{ old: string; new: string } | null>(null)
const diffLoading = ref(false)

async function load() {
  if (!props.resourceId) return
  loading.value = true
  try {
    versions.value =
      props.resourceType === 'block'
        ? await versionApi.listBlockVersions(props.resourceId)
        : await versionApi.listFlowVersions(props.resourceId)
  } finally {
    loading.value = false
  }
}

watch(
  () => [props.modelValue, props.resourceId],
  ([open]) => {
    if (open) load()
  },
)

async function createVersion() {
  if (!newTag.value.trim()) {
    ElMessage.warning('请填写版本标签')
    return
  }
  creating.value = true
  try {
    if (props.resourceType === 'block') {
      await versionApi.createBlockVersion(props.resourceId, {
        version_tag: newTag.value.trim(),
        commit_message: newMessage.value.trim(),
        set_stable: true,
      })
    } else {
      await versionApi.createFlowVersion(props.resourceId, {
        version_tag: newTag.value.trim(),
        commit_message: newMessage.value.trim(),
        set_stable: true,
      })
    }
    ElMessage.success('版本已发布')
    newTag.value = ''
    newMessage.value = ''
    emit('stable-changed')
    await load()
  } finally {
    creating.value = false
  }
}

async function setStable(v: any) {
  await ElMessageBox.confirm(`将版本 ${v.version_tag || v.id.slice(0, 8)} 设为稳定版？`, '确认', {
    type: 'warning',
  })
  await versionApi.setBlockStable(v.id)
  ElMessage.success('已切换稳定版')
  emit('stable-changed')
  await load()
}

async function runDiff() {
  if (props.resourceType !== 'block') {
    ElMessage.info('Flow 版本 diff 暂以快照元数据对比')
    return
  }
  if (!fromVersion.value || !toVersion.value) {
    ElMessage.warning('请选择要对比的两个版本')
    return
  }
  diffLoading.value = true
  try {
    const data = await versionApi.diffBlock(props.resourceId, fromVersion.value, toVersion.value)
    diffData.value = { old: data.old, new: data.new }
  } finally {
    diffLoading.value = false
  }
}
</script>

<template>
  <el-drawer v-model="visible" :title="`版本管理 · ${resourceName || resourceId.slice(0, 8)}`" size="62%">
    <div class="ver-create">
      <el-input v-model="newTag" placeholder="版本标签，如 v1.2.0" style="width: 200px" />
      <el-input v-model="newMessage" placeholder="提交说明（可选）" style="flex: 1" />
      <el-button type="primary" :loading="creating" @click="createVersion">发布版本</el-button>
    </div>

    <el-table v-loading="loading" :data="versions" size="small" class="ver-table">
      <el-table-column prop="version_tag" label="标签" width="140">
        <template #default="{ row }">
          <span>{{ row.version_tag || row.id.slice(0, 8) }}</span>
          <el-tag v-if="row.is_stable" type="success" size="small" effect="dark" class="stable-tag">稳定</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="commit_message" label="说明" show-overflow-tooltip />
      <el-table-column prop="created_by" label="作者" width="120" />
      <el-table-column prop="created_at" label="时间" width="180" />
      <el-table-column label="操作" width="120">
        <template #default="{ row }">
          <el-button
            v-if="resourceType === 'block' && !row.is_stable"
            link
            type="primary"
            size="small"
            @click="setStable(row)"
            >设为稳定</el-button
          >
        </template>
      </el-table-column>
    </el-table>

    <div v-if="resourceType === 'block'" class="ver-diff">
      <div class="ver-diff-bar">
        <span>版本对比：</span>
        <el-select v-model="fromVersion" placeholder="基线版本" size="small" style="width: 160px">
          <el-option v-for="v in versions" :key="v.id" :label="v.version_tag || v.id.slice(0, 8)" :value="v.id" />
        </el-select>
        <span>→</span>
        <el-select v-model="toVersion" placeholder="目标版本" size="small" style="width: 160px">
          <el-option v-for="v in versions" :key="v.id" :label="v.version_tag || v.id.slice(0, 8)" :value="v.id" />
        </el-select>
        <el-button size="small" type="primary" :loading="diffLoading" @click="runDiff">对比</el-button>
      </div>
      <div v-if="diffData" class="ver-diff-view">
        <DiffEditor :original="diffData.old" :modified="diffData.new" language="python" />
      </div>
    </div>
  </el-drawer>
</template>

<style scoped>
.ver-create {
  display: flex;
  gap: 8px;
  margin-bottom: 14px;
}
.ver-table {
  margin-bottom: 16px;
}
.stable-tag {
  margin-left: 6px;
}
.ver-diff-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 10px;
}
.ver-diff-view {
  height: 380px;
  animation: slide-up 0.3s ease;
}
@keyframes slide-up {
  from {
    opacity: 0;
    transform: translateY(8px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}
</style>
