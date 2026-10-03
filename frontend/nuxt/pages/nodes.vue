<script setup lang="ts">
import type { Node, NodeGroup } from '../types'
const api = useApi()
const { text } = useUiLocale()
const toast = useToast()
const { data: nodes, status, error, refresh } = await useAsyncData('nodes', () => api.get<Node[]>('/api/admin/nodes'))
const { data: groups, refresh: refreshGroups } = await useAsyncData('node-groups', () => api.get<NodeGroup[]>('/api/admin/node-groups'))
const tab = ref<'nodes' | 'groups'>('nodes')
const selected = ref<Node | null>(null)
const selectedGroup = ref<NodeGroup | null>(null)
const form = reactive({ note: '', enabled: true, weight: 1 })
const original = ref('')
const warning = ref(false)
const saving = ref(false)
const pendingDelete = ref<Node | null>(null)
watch(selected, value => {
  Object.assign(form, value ? { note: value.note || '', enabled: value.enabled, weight: value.weight } : { note: '', enabled: true, weight: 1 })
  original.value = JSON.stringify(form)
  warning.value = false
})
function closeEditor(open: boolean) { if (!open && selected.value) { if (JSON.stringify(form) !== original.value) warning.value = true; else selected.value = null } }
async function save() {
  if (!selected.value || saving.value) return
  saving.value = true
  try {
    await api.patch(`/api/admin/nodes/${selected.value.id}`, { note: form.note, enabled: form.enabled, weight: Number(form.weight) || 1 })
    original.value = JSON.stringify(form)
    selected.value = null
    await refresh()
    toast.add({ title: text('已保存', 'Saved'), color: 'success' })
  } catch (cause) { toast.add({ title: String(cause), color: 'error' }) } finally { saving.value = false }
}
async function probe(node: Node) {
  try { await api.post(`/api/admin/nodes/${node.id}/probe`); await refresh(); toast.add({ title: text('已请求探测', 'Probe requested'), color: 'success' }) }
  catch (cause) { toast.add({ title: String(cause), color: 'error' }) }
}
async function remove() {
  if (!pendingDelete.value) return
  try { await api.del(`/api/admin/nodes/${pendingDelete.value.id}`); pendingDelete.value = null; selected.value = null; await refresh() }
  catch (cause) { toast.add({ title: String(cause), color: 'error' }) }
}
function closeGroup(open: boolean) { if (!open) selectedGroup.value = null }
function closeDelete(open: boolean) { if (!open) pendingDelete.value = null }
onBeforeRouteLeave(() => { if (selected.value && JSON.stringify(form) !== original.value) { warning.value = true; return false } })
const beforeUnload = (event: BeforeUnloadEvent) => { if (selected.value && JSON.stringify(form) !== original.value) { event.preventDefault(); event.returnValue = '' } }
onMounted(() => window.addEventListener('beforeunload', beforeUnload))
onUnmounted(() => window.removeEventListener('beforeunload', beforeUnload))
</script>
<template>
  <div class="space-y-5">
    <div class="flex flex-wrap items-center justify-between gap-2"><h1 class="text-2xl font-bold">{{ text('节点与节点组', 'Nodes & node groups') }}</h1><UButton icon="i-lucide-refresh-cw" variant="outline" :label="text('刷新', 'Refresh')" @click="refresh(); refreshGroups()" /></div>
    <div class="flex gap-2"><UButton :variant="tab === 'nodes' ? 'solid' : 'outline'" :label="text('节点', 'Nodes')" @click="tab = 'nodes'" /><UButton :variant="tab === 'groups' ? 'solid' : 'outline'" :label="text('节点组', 'Node groups')" @click="tab = 'groups'" /></div>
    <UAlert v-if="error" color="error" :title="error.message" />
    <div v-else-if="status === 'pending'">{{ text('加载中…', 'Loading…') }}</div>
    <UCard v-else-if="tab === 'nodes'"><div v-for="node in nodes" :key="node.id" class="flex items-center gap-2 border-b border-default py-3 last:border-0"><div class="min-w-0 flex-1"><strong>{{ node.url }}</strong><div class="text-sm text-muted">{{ node.type }} · {{ node.note || node.status }} · {{ node.latency_ms == null ? '—' : `${node.latency_ms} ms` }}</div></div><UBadge :color="node.enabled ? 'success' : 'neutral'">{{ node.status }}</UBadge><UButton variant="ghost" icon="i-lucide-activity" :aria-label="text('探测', 'Probe')" @click="probe(node)" /><UButton variant="ghost" icon="i-lucide-pencil" :aria-label="text('编辑', 'Edit')" @click="selected = node" /></div></UCard>
    <UCard v-else><button v-for="group in groups" :key="group.id" class="flex w-full items-center justify-between border-b border-default py-3 text-left last:border-0 hover:bg-elevated" @click="selectedGroup = group"><span><strong>{{ group.name }}</strong><span class="ml-2 text-sm text-muted">{{ group.description }}</span></span><UBadge>{{ group.member_count }}</UBadge></button></UCard>
    <USlideover :open="!!selected" :title="selected?.url" @update:open="closeEditor"><template #body><form v-if="selected" class="space-y-4" @submit.prevent="save"><UFormField :label="text('备注', 'Note')"><UInput v-model="form.note" class="w-full" /></UFormField><UFormField :label="text('权重', 'Weight')"><UInput v-model.number="form.weight" type="number" min="1" class="w-full" /></UFormField><UCheckbox v-model="form.enabled" :label="text('启用', 'Enabled')" /><div v-if="warning" class="flex flex-wrap items-center gap-2 text-warning">{{ text('有未保存的更改', 'Unsaved changes') }}<UButton size="xs" color="error" variant="outline" :label="text('放弃', 'Discard')" @click="selected = null" /><UButton size="xs" variant="ghost" :label="text('继续编辑', 'Continue')" @click="warning = false" /></div><div class="flex gap-2"><UButton type="submit" :loading="saving" :label="text('保存', 'Save')" /><UButton color="error" variant="outline" :label="text('删除', 'Delete')" @click="pendingDelete = selected" /></div></form></template></USlideover>
    <USlideover :open="!!selectedGroup" :title="selectedGroup?.name" @update:open="closeGroup"><template #body><div v-if="selectedGroup" class="space-y-3"><p>{{ selectedGroup.description }}</p><div v-for="member in selectedGroup.members" :key="String(member.node_id ?? member.node_url)" class="border-b border-default py-2 text-sm">{{ member.node_id ?? member.node_url }} · {{ member.rank }}</div></div></template></USlideover>
    <UModal :open="!!pendingDelete" :title="text('删除节点？', 'Delete node?')" @update:open="closeDelete"><template #body><div class="flex justify-end gap-2"><UButton variant="outline" :label="text('取消', 'Cancel')" @click="pendingDelete = null" /><UButton color="error" :label="text('删除', 'Delete')" @click="remove" /></div></template></UModal>
  </div>
</template>
