<script setup lang="ts">
import type { AuditLog, Page } from '../types'
const api = useApi()
const route = useRoute()
const router = useRouter()
const { text } = useUiLocale()
const { isOwner } = useSession()
const toast = useToast()
const keys = ['scope', 'action', 'target_type', 'actor_sub', 'ip', 'user_agent', 'start', 'end']
const fields = computed(() => keys.map(key => ({ key, label: key.replaceAll('_', ' ') })))
const filters = ref<Record<string, string>>({})
const offset = ref(0)
const limit = 50
watch(() => route.query, query => {
  const next = Object.fromEntries(keys.filter(key => typeof query[key] === 'string').map(key => [key, String(query[key])]))
  if (JSON.stringify(next) !== JSON.stringify(filters.value)) filters.value = next
  offset.value = Math.max(0, Number(query.offset) || 0)
}, { immediate: true })
let debounce: ReturnType<typeof setTimeout> | null = null
watch(filters, value => {
  if (debounce) clearTimeout(debounce)
  debounce = setTimeout(() => {
    if (keys.some(key => (route.query[key] || '') !== (value[key] || ''))) void router.replace({ query: { ...route.query, ...Object.fromEntries(keys.map(key => [key, value[key] || undefined])), offset: undefined } })
  }, 350)
}, { deep: true })
onUnmounted(() => { if (debounce) clearTimeout(debounce) })
const query = computed(() => ({ limit, offset: offset.value, ...Object.fromEntries(Object.entries(filters.value).filter(([, value]) => value.trim())) }))
const { data, status, error, refresh } = await useAsyncData('audit-logs', () => api.get<Page<AuditLog>>('/api/admin/logs/audit', query.value), { watch: [query] })
const selected = ref<AuditLog | null>(null)
const sensitive = ref<unknown>(null)
const revealing = ref(false)
const revealConfirm = ref(false)
async function reveal() {
  if (!selected.value || !isOwner.value || revealing.value) return
  revealing.value = true
  try {
    const result = await api.post<{ action: string, sensitive: unknown }>(`/api/admin/logs/audit/${selected.value.id}/reveal`)
    sensitive.value = result.sensitive
    revealConfirm.value = false
  } catch (cause) { toast.add({ title: String(cause), color: 'error' }) } finally { revealing.value = false }
}
function closeDetail(open: boolean) { if (!open) { selected.value = null; sensitive.value = null } }
function closeConfirm(open: boolean) { if (!open) revealConfirm.value = false }
function changePage(next: number) { offset.value = Math.max(0, next); void router.replace({ query: { ...route.query, offset: offset.value || undefined } }) }
</script>
<template>
  <div class="space-y-5">
    <div class="flex items-center justify-between"><h1 class="text-2xl font-bold">{{ text('审计日志', 'Audit log') }}</h1><UButton icon="i-lucide-refresh-cw" variant="outline" :label="text('刷新', 'Refresh')" @click="refresh()" /></div>
    <ConditionFilter v-model="filters" :fields="fields" />
    <UAlert v-if="error" color="error" :title="error.message" />
    <div v-else-if="status === 'pending'">{{ text('加载中…', 'Loading…') }}</div>
    <UCard v-else><button v-for="row in data?.items" :key="row.id" class="flex w-full flex-wrap items-center gap-2 border-b border-default py-3 text-left text-sm last:border-0 hover:bg-elevated" @click="selected = row; sensitive = null"><span class="w-32 shrink-0 text-muted">{{ row.ts }}</span><span class="min-w-0 flex-1 truncate">{{ row.actor_name || row.actor_sub || '—' }} · {{ row.action }}</span><UBadge>{{ row.scope }}</UBadge></button></UCard>
    <div class="flex items-center justify-between text-sm"><span>{{ offset + 1 }}–{{ offset + (data?.items.length || 0) }} / {{ data?.total || 0 }}</span><div class="flex gap-2"><UButton variant="outline" :disabled="offset === 0" :label="text('上一页', 'Previous')" @click="changePage(offset - limit)" /><UButton variant="outline" :disabled="offset + limit >= (data?.total || 0)" :label="text('下一页', 'Next')" @click="changePage(offset + limit)" /></div></div>
    <USlideover :open="!!selected" :title="selected?.action" @update:open="closeDetail"><template #body><div v-if="selected" class="space-y-3 text-sm"><p>{{ selected.actor_name || selected.actor_sub }} · {{ selected.ts }}</p><pre class="overflow-auto rounded bg-elevated p-3 text-xs">{{ JSON.stringify(selected.detail, null, 2) }}</pre><UButton v-if="isOwner && selected.has_sensitive" :loading="revealing" variant="outline" :label="text('显示机密信息', 'Reveal secret')" @click="revealConfirm = true" /><pre v-if="sensitive !== null" class="overflow-auto rounded bg-elevated p-3 text-xs">{{ JSON.stringify(sensitive, null, 2) }}</pre></div></template></USlideover>
    <UModal :open="revealConfirm" :title="text('确认显示机密信息？', 'Reveal sensitive information?')" @update:open="closeConfirm"><template #body><div class="flex justify-end gap-2"><UButton variant="outline" :label="text('取消', 'Cancel')" @click="revealConfirm = false" /><UButton color="error" :loading="revealing" :label="text('确认', 'Confirm')" @click="reveal" /></div></template></UModal>
  </div>
</template>
