<script setup lang="ts">
import type { ModelWithRoute, Provider, Route, RouteUpstream } from '../types'

const props = defineProps<{ id: string }>()
type Draft = RouteUpstream & { key: number }
const api = useApi()
const toast = useToast()
const { text } = useUiLocale()
const { stack, setDirty, close } = useDrawers()
const { data, error, status, refresh } = await useAsyncData(`route-${props.id}`, () => api.get<ModelWithRoute>(`/api/models/${encodeURIComponent(props.id)}/route`))
const { data: providers } = await useAsyncData('route-providers', () => api.get<Provider[]>('/api/admin/providers'))
const mode = ref<Route['upstream_select_mode']>('')
const algorithm = ref<Route['upstream_rank_algorithm']>('')
const attempts = ref(3)
const cooled = ref<Route['upstream_all_cooled_behavior']>('')
const entries = ref<Draft[]>([])
const original = ref('')
let nextKey = 0
watch(data, value => {
  if (!value?.route || original.value) return
  mode.value = value.route.upstream_select_mode
  algorithm.value = value.route.upstream_rank_algorithm
  attempts.value = value.route.max_upstream_attempts
  cooled.value = value.route.upstream_all_cooled_behavior
  entries.value = value.route.upstreams.map(entry => ({ ...entry, key: ++nextKey }))
  original.value = snapshot()
}, { immediate: true })
function snapshot() { return JSON.stringify({ mode: mode.value, algorithm: algorithm.value, attempts: attempts.value, cooled: cooled.value, entries: entries.value }) }
watch([mode, algorithm, attempts, cooled, entries], () => {
  if (original.value) setDirty(snapshot() !== original.value, 'route', props.id)
}, { deep: true })
const groups = computed(() => [...new Set(entries.value.map(entry => entry.group_position ?? 0))].sort((a, b) => a - b))
function addGroup() {
  const position = groups.value.length ? Math.max(...groups.value) + 1 : 0
  addEntry(position)
}
function addEntry(position: number) {
  const current = entries.value.filter(entry => entry.group_position === position)
  entries.value.push({ key: ++nextKey, provider_id: null, upstream_model: '', weight: 1, enabled: true, key_pool: '', group_position: position, position: current.length ? Math.max(...current.map(entry => entry.position ?? 0)) + 1 : 0 })
}
function removeGroup(position: number) { entries.value = entries.value.filter(entry => entry.group_position !== position) }
function moveGroup(position: number, direction: -1 | 1) {
  const index = groups.value.indexOf(position)
  const other = groups.value[index + direction]
  if (other === undefined) return
  for (const entry of entries.value) {
    if (entry.group_position === position) entry.group_position = other
    else if (entry.group_position === other) entry.group_position = position
  }
}
function moveEntry(entry: Draft, direction: -1 | 1) {
  const inGroup = entries.value.filter(item => item.group_position === entry.group_position).sort((a, b) => (a.position ?? 0) - (b.position ?? 0))
  const index = inGroup.findIndex(item => item.key === entry.key)
  const target = inGroup[index + direction]
  if (!target) return
  const currentPosition = entry.position ?? index
  entry.position = target.position ?? index + direction
  target.position = currentPosition
}
const saving = ref(false)
async function save() {
  if (saving.value) return
  const invalid = entries.value.some(entry => !entry.provider_id || !entry.upstream_model.trim())
  if (invalid) { toast.add({ title: text('请为每个候选指定提供商和上游模型', 'Select a provider and upstream model for each candidate'), color: 'error' }); return }
  saving.value = true
  const sorted = [...entries.value].sort((a, b) => (a.group_position ?? 0) - (b.group_position ?? 0) || (a.position ?? 0) - (b.position ?? 0))
  const positions = [...new Set(sorted.map(entry => entry.group_position ?? 0))]
  const nextPosition = new Map<number, number>()
  const body: Omit<Route, 'id' | 'exposed_model_id'> = {
    upstream_select_mode: mode.value,
    upstream_rank_algorithm: algorithm.value,
    max_upstream_attempts: Math.max(0, Number(attempts.value) || 0),
    upstream_all_cooled_behavior: cooled.value,
    upstreams: sorted.map(entry => {
      const group = positions.indexOf(entry.group_position ?? 0)
      const position = nextPosition.get(group) ?? 0
      nextPosition.set(group, position + 1)
      return {
        provider_id: entry.provider_id!, upstream_model: entry.upstream_model.trim(), enabled: entry.enabled,
        key_pool: entry.key_pool.trim(), weight: Math.max(1, Number(entry.weight) || 1),
        group_position: group, position,
        cooldown_seconds: entry.cooldown_seconds ?? 0,
        cooldown_status_codes: entry.cooldown_status_codes ?? []
      }
    })
  }
  try {
    await api.put(`/api/models/${encodeURIComponent(props.id)}/route`, body)
    original.value = snapshot()
    setDirty(false, 'route', props.id)
    toast.add({ title: text('路由已保存', 'Route saved'), color: 'success' })
    await refresh()
    await refreshNuxtData(`model-${props.id}`)
    if (stack.value.at(-1)?.kind === 'route' && stack.value.at(-1)?.id === props.id) {
      if (history.state?.drawerDepth) history.back()
      else close(true)
    }
  } catch (cause) { toast.add({ title: String(cause), color: 'error' }) }
  finally { saving.value = false }
}
const onSave = (event: Event) => {
  if ((event as CustomEvent<string>).detail === props.id && stack.value.at(-1)?.kind === 'route') void save()
}
onMounted(() => window.addEventListener('vs-save-drawer', onSave))
onUnmounted(() => window.removeEventListener('vs-save-drawer', onSave))
</script>

<template>
  <div v-if="status === 'pending'">{{ text('加载中…', 'Loading…') }}</div>
  <UAlert v-else-if="error" color="error" :title="error.message" />
  <div v-else class="space-y-5">
    <div class="grid gap-3 sm:grid-cols-2">
      <UFormField :label="text('上游选择策略', 'Selection mode')"><USelect v-model="mode" :items="['', 'best', 'balanced', 'pinned_best', 'pinned_balanced']" class="w-full" /></UFormField>
      <UFormField :label="text('排序算法', 'Rank algorithm')"><USelect v-model="algorithm" :items="['', 'weighted', 'tiered']" class="w-full" /></UFormField>
      <UFormField :label="text('最大尝试次数', 'Max attempts')"><UInput v-model.number="attempts" type="number" min="0" class="w-full" /></UFormField>
      <UFormField :label="text('全部冷却时', 'All cooled behavior')"><USelect v-model="cooled" :items="['', 'fail_fast', 'ignore_cooldown']" class="w-full" /></UFormField>
    </div>
    <UCard v-for="(position, index) in groups" :key="position" class="space-y-3">
      <div class="flex items-center gap-2"><strong class="flex-1">{{ text('候选组', 'Candidate group') }} {{ index + 1 }}</strong>
        <UButton icon="i-lucide-arrow-up" variant="ghost" :disabled="index === 0" :aria-label="text('上移', 'Move up')" @click="moveGroup(position, -1)" />
        <UButton icon="i-lucide-arrow-down" variant="ghost" :disabled="index === groups.length - 1" :aria-label="text('下移', 'Move down')" @click="moveGroup(position, 1)" />
        <UButton icon="i-lucide-trash" variant="ghost" color="error" :aria-label="text('删除组', 'Remove group')" @click="removeGroup(position)" />
      </div>
      <div v-for="entry in entries.filter(item => item.group_position === position).sort((a, b) => (a.position ?? 0) - (b.position ?? 0))" :key="entry.key" class="space-y-2 border-t border-default pt-3">
        <div class="grid gap-2 sm:grid-cols-2">
          <UFormField :label="text('提供商', 'Provider')"><USelect :model-value="entry.provider_id ?? undefined" value-key="value" :items="(providers || []).map(provider => ({ label: provider.name, value: provider.id }))" class="w-full" @update:model-value="entry.provider_id = $event ?? null" /></UFormField>
          <UFormField :label="text('上游模型', 'Upstream model')"><UInput v-model="entry.upstream_model" class="w-full" /></UFormField>
          <UFormField :label="text('密钥池', 'Key pool')"><UInput v-model="entry.key_pool" class="w-full" /></UFormField>
          <UFormField :label="text('权重', 'Weight')"><UInput v-model.number="entry.weight" type="number" min="1" class="w-full" /></UFormField>
        </div>
        <div class="flex items-center justify-between"><UCheckbox v-model="entry.enabled" :label="text('启用', 'Enabled')" /><div><UButton icon="i-lucide-arrow-up" variant="ghost" :aria-label="text('上移', 'Move up')" @click="moveEntry(entry, -1)" /><UButton icon="i-lucide-arrow-down" variant="ghost" :aria-label="text('下移', 'Move down')" @click="moveEntry(entry, 1)" /><UButton icon="i-lucide-trash" variant="ghost" color="error" :aria-label="text('删除候选', 'Remove candidate')" @click="entries = entries.filter(item => item.key !== entry.key)" /></div></div>
      </div>
      <UButton icon="i-lucide-plus" variant="outline" :label="text('添加候选', 'Add candidate')" @click="addEntry(position)" />
    </UCard>
    <div class="flex gap-2"><UButton icon="i-lucide-plus" variant="outline" :label="text('添加候选组', 'Add group')" @click="addGroup" /><UButton :loading="saving" :label="text('保存路由', 'Save route')" @click="save" /></div>
  </div>
</template>
