<script setup lang="ts">
import type { ModelWithRoute, ModelEntry } from '../types'
const props = defineProps<{ id: string }>()
const api = useApi()
const { text } = useUiLocale()
const { isStaff } = useSession()
const { open } = useDrawers()
const { data, status, error } = await useAsyncData(`model-${props.id}`, async () => {
  if (isStaff.value) return api.get<ModelWithRoute>(`/api/models/${encodeURIComponent(props.id)}/route`)
  const rows = await api.get<ModelEntry[]>('/api/models')
  const model = rows.find(row => row.model_id === props.id)
  if (!model) throw new Error(text('模型不存在或无权访问', 'Model not found or access denied'))
  return model as ModelWithRoute
})
</script>
<template>
  <div v-if="status === 'pending'">{{ text('加载中…', 'Loading…') }}</div>
  <UAlert v-else-if="error" color="error" :title="error.message" />
  <div v-else-if="data" class="space-y-4">
    <h3 class="text-xl font-semibold">{{ data.display_name || data.model_id }}</h3>
    <p class="text-sm text-muted">{{ data.description }}</p>
    <UCard>
      <div class="mb-3 font-semibold">{{ text('上游候选', 'Upstream candidates') }}</div>
      <div v-for="upstream in data.route?.upstreams" :key="upstream.id" class="border-t border-default py-3 text-sm">
        {{ upstream.provider_name }} / {{ upstream.upstream_model }} · {{ upstream.weight }}
      </div>
      <p v-if="!data.route?.upstreams?.length" class="text-muted">{{ text('暂无候选', 'No candidates') }}</p>
    </UCard>
    <UButton v-if="isStaff" icon="i-lucide-pencil" :label="text('编辑路由', 'Edit route')" @click="open({ kind: 'route', id })" />
  </div>
</template>
