<script setup lang="ts">
import type { Provider } from '../types'
const api = useApi()
const route = useRoute()
const { text } = useUiLocale()
const { open } = useDrawers()
const { prefs } = useWorkbench()
const drawers = useDrawers()
const filters = ref<Record<string, string>>({})
const fields = computed(() => [{ key: 'name', label: text('名称', 'Name') }, { key: 'type', label: text('类型', 'Type') }, { key: 'enabled', label: text('状态', 'Status') }])
const { data, status, error, refresh } = await useAsyncData('providers', () => api.get<Provider[]>('/api/admin/providers'))
const rows = computed(() => (data.value || []).filter(row => Object.entries(filters.value).every(([key, value]) => !value || String(row[key as keyof Provider] ?? '').toLowerCase().includes(value.toLowerCase()))))
function detail(id: number) {
  if (prefs.value.detailMode === 'page') { void navigateTo(`/providers/${id}`); return }
  if (!drawers.stack.value.some(item => item.kind === 'provider' && item.id === String(id))) {
    open({ kind: 'provider', id: String(id) })
    history.replaceState({ ...history.state, drawerDepth: drawers.stack.value.length, drawerDirect: false }, '', `/providers?provider=${id}`)
  }
}
onMounted(() => {
  if (typeof route.query.provider === 'string' && prefs.value.detailMode !== 'page') {
    const id = route.query.provider
    drawers.stack.value = [...drawers.stack.value, { kind: 'provider', id }]
    history.replaceState({ ...history.state, drawerDepth: drawers.stack.value.length, drawerDirect: true }, '', location.href)
  }
})
onBeforeRouteLeave(() => {
  if (drawers.stack.value.some(item => item.dirty)) { drawers.warning.value = true; return false }
})
</script>
<template>
  <div class="space-y-5">
    <div class="flex justify-between"><h1 class="text-2xl font-bold">{{ text('提供商', 'Providers') }}</h1><UButton icon="i-lucide-refresh-cw" variant="outline" :label="text('刷新', 'Refresh')" @click="refresh()" /></div>
    <ConditionFilter v-model="filters" :fields="fields" />
    <UAlert v-if="error" color="error" :title="error.message" />
    <div v-else-if="status === 'pending'">{{ text('加载中…', 'Loading…') }}</div>
    <UCard v-else>
      <div v-for="row in rows" :key="row.id" class="flex items-center gap-3 border-b border-default py-3 last:border-0">
        <div class="min-w-0 flex-1"><div class="font-medium">{{ row.name }}</div><div class="truncate text-sm text-muted">{{ row.type }} · {{ row.base_url }}</div></div>
        <UBadge :color="row.enabled ? 'success' : 'neutral'">{{ row.enabled ? text('启用', 'Enabled') : text('禁用', 'Disabled') }}</UBadge>
        <UButton icon="i-lucide-pencil" variant="ghost" :aria-label="text('编辑', 'Edit')" @click="detail(row.id)" />
      </div>
    </UCard>
  </div>
</template>
