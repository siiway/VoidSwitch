<script setup lang="ts">
import type { ModelHealth, NodeHealth } from '../types'
type Tab = 'models' | 'nodes'
const api = useApi()
const { isStaff } = useSession()
const { text } = useUiLocale()
const tab = ref<Tab>('models')
const windowKey = ref('1d')
const live = ref(true)
const state = ref('connecting')
const models = ref<ModelHealth[]>([])
const nodes = ref<NodeHealth[]>([])
const windows = ['30m', '1h', '3h', '12h', '1d', '3d', '7d']
watch([tab, windowKey, live], (_, __, onCleanup) => {
  if (!import.meta.client) return
  if (!live.value) { state.value = 'paused'; return }
  const controller = new AbortController()
  onCleanup(() => controller.abort())
  state.value = 'connecting'
  void (async () => {
    try {
      const params = new URLSearchParams({ tab: tab.value, window: windowKey.value })
      const response = await fetch(`${api.base}/api/health/stream?${params}`, {
        headers: { Authorization: `Bearer ${localStorage.getItem('voidswitch.token') || ''}` },
        signal: controller.signal,
        cache: 'no-store'
      })
      if (!response.ok || !response.body) throw new Error(`HTTP ${response.status}`)
      state.value = 'connected'
      const reader = response.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''
      while (true) {
        const { value, done } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, '\n')
        let boundary = buffer.indexOf('\n\n')
        while (boundary >= 0) {
          const frame = buffer.slice(0, boundary)
          buffer = buffer.slice(boundary + 2)
          const raw = frame.split('\n').filter(line => line.startsWith('data:')).map(line => line.slice(5).trim()).join('\n')
          if (raw) {
            const payload = JSON.parse(raw) as { models?: ModelHealth[], nodes?: NodeHealth[] }
            if (payload.models) models.value = payload.models
            if (payload.nodes) nodes.value = payload.nodes
          }
          boundary = buffer.indexOf('\n\n')
        }
      }
      if (!controller.signal.aborted) state.value = 'error'
    } catch { if (!controller.signal.aborted) state.value = 'error' }
  })()
}, { immediate: true })
</script>
<template>
  <div class="space-y-5">
    <div class="flex flex-wrap items-center justify-between gap-2">
      <h1 class="text-2xl font-bold">{{ text('健康', 'Health') }}</h1>
      <div class="flex flex-wrap items-center gap-2">
        <UButton v-if="isStaff" :variant="tab === 'models' ? 'solid' : 'outline'" :label="text('模型', 'Models')" @click="tab = 'models'" />
        <UButton v-if="isStaff" :variant="tab === 'nodes' ? 'solid' : 'outline'" :label="text('节点', 'Nodes')" @click="tab = 'nodes'" />
        <USelect v-if="tab === 'nodes'" v-model="windowKey" :items="windows" />
        <UButton :variant="live ? 'solid' : 'outline'" :label="live ? text('实时', 'Live') : text('已暂停', 'Paused')" @click="live = !live" />
      </div>
    </div>
    <p class="text-sm text-muted">{{ state }}</p>
    <div v-if="tab === 'models'" class="grid gap-4 md:grid-cols-2">
      <UCard v-for="model in models" :key="model.model_id">
        <div class="flex justify-between gap-2"><strong>{{ model.model_id }}</strong><UBadge :color="model.status === 'healthy' ? 'success' : 'warning'">{{ model.status }}</UBadge></div>
        <div class="mt-3 text-sm text-muted">{{ text('近期成功率', 'Recent success') }}: {{ model.recent_success_rate == null ? '—' : `${(model.recent_success_rate * 100).toFixed(1)}%` }} · TTFT: {{ model.recent_avg_ttft_ms == null ? '—' : `${Math.round(model.recent_avg_ttft_ms)} ms` }}</div>
        <div v-if="isStaff" v-for="upstream in model.upstreams" :key="upstream.upstream_id" class="mt-2 border-t border-default pt-2 text-xs">{{ upstream.provider_name }} / {{ upstream.upstream_model }} · {{ upstream.samples ? `${((upstream.success_rate || 0) * 100).toFixed(1)}%` : '—' }}</div>
      </UCard>
    </div>
    <div v-else class="grid gap-4 md:grid-cols-2">
      <UCard v-for="node in nodes" :key="node.id"><strong>{{ node.url }}</strong><div class="mt-2 text-sm text-muted">{{ node.status }} · {{ node.latency_ms == null ? '—' : `${node.latency_ms} ms` }}</div></UCard>
    </div>
  </div>
</template>
