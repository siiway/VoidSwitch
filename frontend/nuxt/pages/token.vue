<script setup lang="ts">
import type { VoidToken, VoidTokenWithSecret } from '../types'
const api = useApi()
const toast = useToast()
const { text } = useUiLocale()
const { data, status, error, refresh } = await useAsyncData('my-tokens', () => api.get<VoidToken[]>('/api/me/tokens'))
const name = ref('default')
const createdSecret = ref('')
const busy = ref(false)
const pending = ref<{ action: 'delete' | 'rotate', token: VoidToken } | null>(null)
const showCreate = ref(false)
const createWarning = ref(false)
const editing = ref<VoidToken | null>(null)
const editName = ref('')
const originalName = ref('')
const renameWarning = ref(false)
async function create() {
  if (busy.value) return
  busy.value = true
  try {
    const created = await api.post<VoidTokenWithSecret>('/api/me/tokens', { name: name.value.trim() || 'default' })
    name.value = 'default'
    createWarning.value = false
    showCreate.value = false
    createdSecret.value = created.token
    await refresh()
  } catch (e) { toast.add({ title: String(e), color: 'error' }) } finally { busy.value = false }
}
async function confirmAction() {
  if (busy.value) return
  const current = pending.value
  if (!current) return
  pending.value = null
  busy.value = true
  try {
    if (current.action === 'delete') await api.del(`/api/me/tokens/${current.token.id}`)
    else createdSecret.value = (await api.post<VoidTokenWithSecret>(`/api/me/tokens/${current.token.id}/rotate`)).token
    await refresh()
  } catch (e) { toast.add({ title: String(e), color: 'error' }) } finally { busy.value = false }
}
function rename(token: VoidToken) {
  editing.value = token
  editName.value = token.name
}
watch(editing, token => { originalName.value = token?.name || ''; renameWarning.value = false })
const onBeforeUnload = (event: BeforeUnloadEvent) => {
  if ((editing.value && editName.value !== originalName.value) || (showCreate.value && name.value !== 'default')) { event.preventDefault(); event.returnValue = '' }
}
onMounted(() => window.addEventListener('beforeunload', onBeforeUnload))
onUnmounted(() => window.removeEventListener('beforeunload', onBeforeUnload))
onBeforeRouteLeave(() => {
  if (editing.value && editName.value !== originalName.value) { renameWarning.value = true; return false }
  if (showCreate.value && name.value !== 'default') { createWarning.value = true; return false }
})
async function saveName() {
  if (!editing.value) return
  try { await api.patch(`/api/me/tokens/${editing.value.id}`, { name: editName.value.trim() || 'default' }); editing.value = null; await refresh() }
  catch (e) { toast.add({ title: String(e), color: 'error' }) }
}
async function toggleDebug(token: VoidToken) {
  try { await api.patch(`/api/me/tokens/${token.id}`, { debug_enabled: !token.debug_enabled }); await refresh() }
  catch (e) { toast.add({ title: String(e), color: 'error' }) }
}
async function toggle(token: VoidToken) {
  try { await api.patch(`/api/me/tokens/${token.id}`, { enabled: !token.enabled }); await refresh() }
  catch (e) { toast.add({ title: String(e), color: 'error' }) }
}
async function copy() {
  try { await navigator.clipboard.writeText(createdSecret.value); toast.add({ title: text('已复制', 'Copied'), color: 'success' }) }
  catch (e) { toast.add({ title: String(e), color: 'error' }) }
}
function secretOpenChange(open: boolean) { if (!open) createdSecret.value = '' }
function confirmOpenChange(open: boolean) { if (!open) pending.value = null }
function editOpenChange(open: boolean) {
  if (!open && editing.value) {
    if (editName.value !== originalName.value) { renameWarning.value = true; return }
    editing.value = null
  }
}
function createOpenChange(open: boolean) {
  if (!open && name.value !== 'default') { createWarning.value = true; return }
  showCreate.value = open
}
</script>
<template>
  <div class="space-y-5">
    <div class="flex items-center justify-between"><h1 class="text-2xl font-bold">{{ text('我的 API Key', 'My API keys') }}</h1><UButton icon="i-lucide-refresh-cw" variant="outline" :label="text('刷新', 'Refresh')" @click="refresh()" /></div>
    <UButton icon="i-lucide-plus" :label="text('新建令牌', 'Create token')" @click="showCreate = true" />
    <USlideover :open="showCreate" :title="text('新建令牌', 'Create token')" @update:open="createOpenChange">
      <template #body><form class="space-y-3" @submit.prevent="create"><UInput v-model="name" :placeholder="text('名称', 'Name')" class="w-full" /><div v-if="createWarning" class="flex flex-wrap items-center gap-2 text-sm text-warning">{{ text('有未保存的更改', 'Unsaved changes') }}<UButton size="xs" color="error" variant="outline" :label="text('放弃更改', 'Discard')" @click="name = 'default'; showCreate = false; createWarning = false" /><UButton size="xs" variant="ghost" :label="text('继续编辑', 'Continue')" @click="createWarning = false" /></div><UButton type="submit" :loading="busy" :label="text('新建', 'Create')" /></form></template>
    </USlideover>
    <UAlert v-if="error" color="error" :title="error.message" />
    <div v-else-if="status === 'pending'">{{ text('加载中…', 'Loading…') }}</div>
    <UCard v-else>
      <div v-for="token in data" :key="token.id" class="flex flex-wrap items-center gap-2 border-b border-default py-3 last:border-0">
        <div class="min-w-32 flex-1"><div class="font-medium">{{ token.name }}</div><div class="text-sm text-muted">{{ token.token_prefix }}… · {{ token.total_requests }} {{ text('次请求', 'requests') }}</div></div>
        <UBadge :color="token.enabled ? 'success' : 'neutral'">{{ token.enabled ? text('启用', 'Enabled') : text('禁用', 'Disabled') }}</UBadge>
        <UButton variant="ghost" icon="i-lucide-pencil" :aria-label="text('重命名', 'Rename')" @click="rename(token)" />
        <UButton variant="ghost" icon="i-lucide-bug" :aria-label="token.debug_enabled ? text('关闭调试', 'Disable debug') : text('开启调试', 'Enable debug')" @click="toggleDebug(token)" />
        <UButton variant="ghost" icon="i-lucide-power" :aria-label="token.enabled ? text('禁用', 'Disable') : text('启用', 'Enable')" @click="toggle(token)" />
        <UButton variant="ghost" icon="i-lucide-refresh-cw" :aria-label="text('轮换', 'Rotate')" @click="pending = { action: 'rotate', token }" />
        <UButton variant="ghost" color="error" icon="i-lucide-trash" :aria-label="text('删除', 'Delete')" @click="pending = { action: 'delete', token }" />
      </div>
    </UCard>
    <USlideover :open="!!createdSecret" :title="text('请立即保存令牌；关闭后将无法再次查看', 'Save this token now; it will not be shown again')" @update:open="secretOpenChange">
      <template #body><div class="space-y-3"><code class="block break-all rounded bg-elevated p-3">{{ createdSecret }}</code><UButton icon="i-lucide-copy" :label="text('复制', 'Copy')" @click="copy" /></div></template>
    </USlideover>
    <UModal :open="!!pending" :title="pending?.action === 'delete' ? text('删除令牌？', 'Delete token?') : text('轮换令牌？', 'Rotate token?')" @update:open="confirmOpenChange">
      <template #body><div class="flex justify-end gap-2"><UButton variant="outline" :label="text('取消', 'Cancel')" @click="pending = null" /><UButton color="error" :loading="busy" :label="text('确认', 'Confirm')" @click="confirmAction" /></div></template>
    </UModal>
    <USlideover :open="!!editing" :title="text('重命名令牌', 'Rename token')" @update:open="editOpenChange">
      <template #body>
        <form class="space-y-4" @submit.prevent="saveName">
          <UInput v-model="editName" class="w-full" />
          <div v-if="renameWarning" class="flex flex-wrap items-center gap-2 text-sm text-warning">{{ text('有未保存的更改', 'Unsaved changes') }}<UButton size="xs" color="error" variant="outline" :label="text('放弃更改', 'Discard')" @click="editing = null" /><UButton size="xs" variant="ghost" :label="text('继续编辑', 'Continue')" @click="renameWarning = false" /></div>
          <UButton type="submit" :label="text('保存', 'Save')" />
        </form>
      </template>
    </USlideover>
  </div>
</template>
