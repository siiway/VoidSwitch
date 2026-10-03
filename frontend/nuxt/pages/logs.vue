<script setup lang="ts">
import type { Page, RequestLog, RequestLogDetail } from '../types'
const api = useApi()
const route = useRoute()
const router = useRouter()
const { text } = useUiLocale()
const toast = useToast()
const available = computed(() => [
  { key: 'model', label: text('模型', 'Model') }, { key: 'user_sub', label: text('用户', 'User') },
  { key: 'token_id', label: text('令牌', 'Token') }, { key: 'provider', label: text('提供商', 'Provider') },
  { key: 'client_ip', label: 'IP' }, { key: 'status_code', label: text('状态码', 'Status code') },
  { key: 'req_status', label: text('请求状态', 'Request status') }, { key: 'start', label: text('开始时间', 'Start time') },
  { key: 'end', label: text('结束时间', 'End time') }
])
const keys = ['model', 'user_sub', 'token_id', 'provider', 'client_ip', 'status_code', 'req_status', 'start', 'end']
const filters = ref<Record<string, string>>({})
const pageSize = ref(50)
const offset = ref(0)
const live = ref(false)
const liveRows = ref<RequestLog[]>([])
watch(filters, () => { liveRows.value = [] }, { deep: true })
const streamStatus = ref<'idle' | 'connecting' | 'connected' | 'error'>('idle')
const detail = ref<RequestLogDetail | null>(null)
const detailBusy = ref(false)
const detailError = ref('')
let stream: AbortController | null = null
let debounce: ReturnType<typeof setTimeout> | null = null
const query = computed(() => ({ limit: pageSize.value, offset: offset.value, ...Object.fromEntries(Object.entries(filters.value).filter(([, value]) => value.trim())) }))
const { data, status, error, refresh } = await useAsyncData('preview-request-logs', () => api.get<Page<RequestLog>>('/api/admin/logs/requests', query.value), { watch: [query] })
const rows = computed(() => offset.value === 0 && live.value ? [...liveRows.value, ...(data.value?.items || []).filter(row => !liveRows.value.some(item => item.id === row.id))] : data.value?.items || [])
watch(() => route.query, query => {
  const next = Object.fromEntries(keys.filter(key => typeof query[key] === 'string').map(key => [key, String(query[key])]))
  if (JSON.stringify(filters.value) !== JSON.stringify(next)) filters.value = next
  offset.value = Math.max(0, Number(query.offset) || 0)
}, { immediate: true })
watch(filters, value => {
  if (debounce) clearTimeout(debounce)
  debounce = setTimeout(() => {
    offset.value = 0
    const next = { ...route.query, ...Object.fromEntries(keys.map(key => [key, value[key] || undefined])), offset: undefined }
    if (keys.some(key => (route.query[key] || '') !== (value[key] || '')) || route.query.offset) void router.replace({ query: next })
  }, 350)
}, { deep: true })
watch([live, filters], (_, __, onCleanup) => {
  if (!import.meta.client) return
  if (!live.value) { streamStatus.value = 'idle'; return }
  streamStatus.value = 'connecting'
  stream = new AbortController()
  const controller = stream
  onCleanup(() => { controller.abort(); if (stream === controller) stream = null })
  void (async () => {
    try {
      const params = new URLSearchParams(Object.entries(filters.value).filter(([, value]) => value.trim()))
      params.set('after_id', String(Math.max(0, ...(data.value?.items || []).map(row => row.id))))
      const response = await fetch(`${api.base}/api/admin/logs/requests/stream?${params}`, {
        headers: { Authorization: `Bearer ${localStorage.getItem('voidswitch.token') || ''}` }, signal: controller.signal, cache: 'no-store'
      })
      if (!response.ok || !response.body) throw new Error(`HTTP ${response.status}`)
      streamStatus.value = 'connected'
      const reader = response.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''
      while (!controller.signal.aborted) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, '\n')
        let boundary = buffer.indexOf('\n\n')
        while (boundary >= 0) {
          const frame = buffer.slice(0, boundary)
          buffer = buffer.slice(boundary + 2)
          const raw = frame.split('\n').filter(line => line.startsWith('data:')).map(line => line.slice(5).trim()).join('\n')
          if (raw) {
            try {
              const row = JSON.parse(raw) as RequestLog
              if (typeof row.id === 'number' && typeof row.success === 'boolean') {
                liveRows.value = [row, ...liveRows.value.filter(item => item.id !== row.id)].slice(0, 300)
              }
            } catch { /* ignore keep-alive frames */ }
          }
          boundary = buffer.indexOf('\n\n')
        }
      }
      if (!controller.signal.aborted) streamStatus.value = 'error'
    } catch (cause) { if (!controller.signal.aborted) { streamStatus.value = 'error'; toast.add({ title: String(cause), color: 'error' }) } }
  })()
})
watch(() => route.query.log, id => {
  if (typeof id === 'string') void showDetail(Number(id))
  else detail.value = null
}, { immediate: true })
async function showDetail(id: number) {
  if (!Number.isFinite(id)) return
  detailBusy.value = true
  detailError.value = ''
  try { detail.value = await api.get<RequestLogDetail>(`/api/admin/logs/requests/${id}`) }
  catch (cause) { detailError.value = String(cause) }
  finally { detailBusy.value = false }
}
function selectLog(id: number) { void router.replace({ query: { ...route.query, log: String(id) } }) }
function closeDetail(open: boolean) { if (!open) void router.replace({ query: { ...route.query, log: undefined } }) }
function changePage(next: number) { offset.value = Math.max(0, next); void router.replace({ query: { ...route.query, offset: offset.value || undefined } }) }
onUnmounted(() => { stream?.abort(); if (debounce) clearTimeout(debounce) })
</script>
<template>
  <div class="space-y-5">
    <div class="flex flex-wrap items-center justify-between gap-2"><h1 class="text-2xl font-bold">{{ text('请求日志', 'Request logs') }}</h1><div class="flex gap-2"><UButton :variant="live ? 'solid' : 'outline'" :label="live ? text('实时', 'Live') : text('实时已关闭', 'Live off')" @click="live = !live; liveRows = []" /><UButton icon="i-lucide-refresh-cw" variant="outline" :label="text('刷新', 'Refresh')" @click="refresh()" /></div></div>
    <ConditionFilter v-model="filters" :fields="available" />
    <p v-if="live" class="text-xs text-muted">{{ streamStatus }}</p>
    <UAlert v-if="error" color="error" :title="error.message" />
    <div v-else-if="status === 'pending'">{{ text('加载中…', 'Loading…') }}</div>
    <UCard v-else><button v-for="row in rows" :key="row.id" class="flex w-full flex-wrap items-center gap-2 border-b border-default py-3 text-left text-sm last:border-0 hover:bg-elevated" @click="selectLog(row.id)">
      <span class="w-32 shrink-0 text-muted">{{ row.ts }}</span><span class="min-w-0 flex-1 truncate">{{ row.model || '—' }} · {{ row.provider_name || '—' }}</span><UBadge :color="row.success ? 'success' : 'error'">{{ row.status_code || row.req_status || '—' }}</UBadge><span class="text-muted">{{ row.total_tokens }} tokens</span>
    </button></UCard>
    <div class="flex items-center justify-between text-sm"><span>{{ offset + 1 }}–{{ offset + (data?.items.length || 0) }} / {{ data?.total || 0 }}</span><div class="flex gap-2"><UButton variant="outline" :disabled="offset === 0" :label="text('上一页', 'Previous')" @click="changePage(offset - pageSize)" /><UButton variant="outline" :disabled="offset + pageSize >= (data?.total || 0)" :label="text('下一页', 'Next')" @click="changePage(offset + pageSize)" /></div></div>
    <USlideover :open="!!route.query.log" :title="text('请求详情', 'Request detail')" @update:open="closeDetail"><template #body><div v-if="detailBusy">{{ text('加载中…', 'Loading…') }}</div><UAlert v-else-if="detailError" color="error" :title="detailError" /><div v-else-if="detail" class="space-y-3 text-sm"><div>{{ detail.model }} · {{ detail.provider_name }} · {{ detail.status_code }}</div><pre class="overflow-auto rounded bg-elevated p-3 text-xs">{{ JSON.stringify(detail, null, 2) }}</pre></div></template></USlideover>
  </div>
</template>
