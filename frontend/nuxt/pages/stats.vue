<script setup lang="ts">
import type { UsageAnalytics, UsageGroupRow } from '../types'
const api = useApi()
const { text } = useUiLocale()
const { user, isStaff, isObserver } = useSession()
const route = useRoute()
const router = useRouter()
const filters = ref<Record<string, string>>({})
const allowedGroupIds = computed(() => user.value?.managed_group_ids || [])
const fields = computed(() => [
  { key: 'start', label: text('开始时间（ISO）', 'Start (ISO)') },
  { key: 'end', label: text('结束时间（ISO）', 'End (ISO)') }
])
const chosenGroup = computed({
  get: () => filters.value.group_ids || '',
  set: value => { filters.value = { ...filters.value, group_ids: value } }
})
watch(() => route.query, query => {
  const next = Object.fromEntries(['start', 'end', 'group_ids'].filter(key => typeof query[key] === 'string').map(key => [key, String(query[key])]))
  if (next.group_ids && !allowedGroupIds.value.includes(Number(next.group_ids))) delete next.group_ids
  if (JSON.stringify(filters.value) !== JSON.stringify(next)) filters.value = next
}, { immediate: true })
let debounce: ReturnType<typeof setTimeout> | null = null
watch(filters, value => {
  if (debounce) clearTimeout(debounce)
  debounce = setTimeout(() => {
    if (['start', 'end', 'group_ids'].some(key => (route.query[key] || '') !== (value[key] || ''))) void router.replace({ query: { ...route.query, start: value.start || undefined, end: value.end || undefined, group_ids: value.group_ids || undefined } })
  }, 350)
}, { deep: true })
onUnmounted(() => { if (debounce) clearTimeout(debounce) })
const query = computed(() => ({ start: filters.value.start, end: filters.value.end, ...(!isStaff.value && isObserver.value && filters.value.group_ids && allowedGroupIds.value.includes(Number(filters.value.group_ids)) ? { group_ids: filters.value.group_ids } : {}) }))
const { data, status, error, refresh } = await useAsyncData('usage-statistics', () => api.get<UsageAnalytics>('/api/usage', query.value), { watch: [query] })
const tab = ref<'daily' | 'weekly' | 'monthly' | 'yearly'>('daily')
const groupBy = ref<'by_user' | 'by_token' | 'by_model' | 'by_provider'>('by_model')
const maxTokens = computed(() => Math.max(1, ...(data.value?.[tab.value] || []).map(bucket => bucket.total_tokens)))
const maxRows = computed(() => Math.max(1, ...(data.value?.[groupBy.value] || []).map(row => row.total_tokens)))
function label(row: UsageGroupRow) { return row.label || row.key }
</script>
<template>
  <div class="space-y-5">
    <div class="flex items-center justify-between"><h1 class="text-2xl font-bold">{{ text('统计', 'Statistics') }}</h1><UButton icon="i-lucide-refresh-cw" variant="outline" :label="text('刷新', 'Refresh')" @click="refresh()" /></div>
    <ConditionFilter v-model="filters" :fields="fields" />
    <USelect v-if="isObserver && !isStaff && allowedGroupIds.length > 1" v-model="chosenGroup" value-key="value" :items="[{ label: text('全部管理的身份组', 'All managed groups'), value: '' }, ...allowedGroupIds.map(id => ({ label: String(id), value: String(id) }))]" class="w-60" />
    <UAlert v-if="error" color="error" :title="error.message" />
    <div v-else-if="status === 'pending'">{{ text('加载中…', 'Loading…') }}</div>
    <template v-else-if="data">
      <div class="grid gap-3 sm:grid-cols-2 xl:grid-cols-4"><UCard v-for="key in ['requests', 'total_tokens', 'success', 'failures'] as const" :key="key"><div class="text-sm text-muted">{{ key }}</div><div class="mt-2 text-2xl font-semibold">{{ data.totals[key] }}</div></UCard></div>
      <UCard class="space-y-4"><div class="flex flex-wrap gap-2"><UButton v-for="option in ['daily', 'weekly', 'monthly', 'yearly'] as const" :key="option" :variant="tab === option ? 'solid' : 'outline'" :label="option" @click="tab = option" /></div><div class="max-h-96 space-y-3 overflow-y-auto"><div v-for="bucket in data[tab]" :key="bucket.period" class="flex items-center gap-2 text-sm"><span class="w-24 shrink-0">{{ bucket.period }}</span><div class="h-3 flex-1 rounded bg-elevated"><div class="h-full rounded bg-primary" :style="{ width: `${100 * bucket.total_tokens / maxTokens}%` }" /></div><span class="w-20 text-right">{{ bucket.total_tokens }}</span></div></div></UCard>
      <UCard class="space-y-4"><USelect v-model="groupBy" :items="['by_user', 'by_token', 'by_model', 'by_provider']" class="w-48" /><div v-for="row in data[groupBy]" :key="row.key" class="space-y-1 text-sm"><div class="flex justify-between"><span class="truncate">{{ label(row) }}</span><span>{{ row.total_tokens }}</span></div><div class="h-2 rounded bg-elevated"><div class="h-full rounded bg-primary" :style="{ width: `${100 * row.total_tokens / maxRows}%` }" /></div></div></UCard>
    </template>
  </div>
</template>
