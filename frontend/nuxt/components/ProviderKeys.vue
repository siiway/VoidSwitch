<script setup lang="ts">
import type { ApiKey } from '../types'
const props = defineProps<{ providerId: number }>()
const api = useApi()
const { text } = useUiLocale()
const toast = useToast()
const { data, status, error, refresh } = await useAsyncData(`provider-keys-${props.providerId}`, () => api.get<ApiKey[]>(`/api/admin/providers/${props.providerId}/keys`))
const bulk = ref('')
const pool = ref('')
const adding = ref(false)
const pending = ref<ApiKey | null>(null)
async function add() {
  const keys = bulk.value.split('\n').map(key => key.trim()).filter(Boolean)
  if (!keys.length || adding.value) return
  adding.value = true
  try {
    await api.post(`/api/admin/providers/${props.providerId}/keys`, { keys, pool: pool.value.trim() })
    bulk.value = ''; pool.value = ''
    await refresh()
    toast.add({ title: text('密钥已添加', 'Keys added'), color: 'success' })
  } catch (cause) { toast.add({ title: String(cause), color: 'error' }) } finally { adding.value = false }
}
async function toggle(key: ApiKey) {
  try { await api.patch(`/api/admin/providers/${props.providerId}/keys/${key.id}`, { enabled: key.status !== 'active' }); await refresh() }
  catch (cause) { toast.add({ title: String(cause), color: 'error' }) }
}
async function remove() {
  if (!pending.value) return
  try { await api.del(`/api/admin/providers/${props.providerId}/keys/${pending.value.id}`); pending.value = null; await refresh() }
  catch (cause) { toast.add({ title: String(cause), color: 'error' }) }
}
function closePending(open: boolean) { if (!open) pending.value = null }
</script>
<template>
  <div class="space-y-4">
    <div class="flex items-center justify-between"><h3 class="font-semibold">{{ text('提供商密钥', 'Provider keys') }}</h3><UButton variant="ghost" icon="i-lucide-refresh-cw" :aria-label="text('刷新', 'Refresh')" @click="refresh()" /></div>
    <UAlert v-if="error" color="error" :title="error.message" />
    <div v-else-if="status === 'pending'">{{ text('加载中…', 'Loading…') }}</div>
    <div v-else v-for="key in data" :key="key.id" class="flex items-center gap-2 border-b border-default py-2 text-sm"><span class="min-w-0 flex-1 truncate">{{ key.key_preview }} <span class="text-muted">{{ key.pool }} · {{ key.note }}</span></span><UBadge :color="key.status === 'active' ? 'success' : 'neutral'">{{ key.status }}</UBadge><UButton variant="ghost" icon="i-lucide-power" :aria-label="text('切换状态', 'Toggle state')" @click="toggle(key)" /><UButton variant="ghost" color="error" icon="i-lucide-trash" :aria-label="text('删除', 'Delete')" @click="pending = key" /></div>
    <form class="space-y-2 border-t border-default pt-4" @submit.prevent="add"><UTextarea v-model="bulk" :placeholder="text('每行一个密钥', 'One key per line')" class="w-full" /><UInput v-model="pool" :placeholder="text('密钥池（可选）', 'Key pool (optional)')" class="w-full" /><UButton type="submit" :loading="adding" :label="text('添加密钥', 'Add keys')" /></form>
    <UModal :open="!!pending" :title="text('删除密钥？', 'Delete key?')" @update:open="closePending"><template #body><div class="flex justify-end gap-2"><UButton variant="outline" :label="text('取消', 'Cancel')" @click="pending = null" /><UButton color="error" :label="text('删除', 'Delete')" @click="remove" /></div></template></UModal>
  </div>
</template>
