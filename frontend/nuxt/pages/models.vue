<script setup lang="ts">
import type { ModelEntry } from '../types'
const api = useApi()
const route = useRoute()
const { text } = useUiLocale()
const { open } = useDrawers()
const { prefs } = useWorkbench()
const drawers = useDrawers()
const filters = ref<Record<string, string>>({})
const fields = computed(() => [{ key: 'model_id', label: text('模型 ID', 'Model ID') }, { key: 'display_name', label: text('名称', 'Name') }, { key: 'category_name', label: text('分类', 'Category') }])
const { data, status, error, refresh } = await useAsyncData('models', () => api.get<ModelEntry[]>('/api/models'))
const rows = computed(() => (data.value || []).filter(row => Object.entries(filters.value).every(([key, value]) => !value || String(row[key as keyof ModelEntry] ?? '').toLowerCase().includes(value.toLowerCase()))))
function detail(id: string) {
  if (prefs.value.detailMode === 'page') { void navigateTo(`/models/${encodeURIComponent(id)}`); return }
  if (!drawers.stack.value.some(item => item.kind === 'model' && item.id === id)) {
    open({ kind: 'model', id })
    history.replaceState({ ...history.state, drawerDepth: drawers.stack.value.length, drawerDirect: false }, '', `/models?model=${encodeURIComponent(id)}`)
  }
}
onMounted(() => {
  if (typeof route.query.model === 'string' && prefs.value.detailMode !== 'page') {
    const id = route.query.model
    drawers.stack.value = [...drawers.stack.value, { kind: 'model', id }]
    history.replaceState({ ...history.state, drawerDepth: drawers.stack.value.length, drawerDirect: true }, '', location.href)
  }
})
onBeforeRouteLeave(() => {
  if (drawers.stack.value.some(item => item.dirty)) { drawers.warning.value = true; return false }
})
</script>
<template>
  <div class="space-y-5">
    <div class="flex justify-between"><h1 class="text-2xl font-bold">{{ text('模型', 'Models') }}</h1><UButton icon="i-lucide-refresh-cw" variant="outline" :label="text('刷新', 'Refresh')" @click="refresh()" /></div>
    <ConditionFilter v-model="filters" :fields="fields" />
    <UAlert v-if="error" color="error" :title="error.message" />
    <div v-else-if="status === 'pending'">{{ text('加载中…', 'Loading…') }}</div>
    <UCard v-else>
      <button v-for="row in rows" :key="row.model_id" class="flex w-full items-center gap-3 border-b border-default py-3 text-left last:border-0 hover:bg-elevated" @click="detail(row.model_id)">
        <div class="min-w-0 flex-1"><div class="font-medium">{{ row.display_name || row.model_id }}</div><div class="truncate text-sm text-muted">{{ row.model_id }} · {{ row.category_name }}</div></div>
        <UBadge v-if="row.health" :color="row.health.status === 'healthy' ? 'success' : 'warning'">{{ row.health.status }}</UBadge>
      </button>
    </UCard>
  </div>
</template>
