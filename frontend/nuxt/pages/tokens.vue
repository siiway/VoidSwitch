<script setup lang="ts">
import type { VoidToken, VoidTokenWithSecret } from '../types'
const api = useApi()
const toast = useToast()
const { text } = useUiLocale()
const { data, status, error, refresh } = await useAsyncData('admin-tokens', () => api.get<VoidToken[]>('/api/admin/tokens'))
const filters = ref<Record<string, string>>({})
const fields = computed(() => [
  { key: 'name', label: text('名称', 'Name') }, { key: 'username', label: text('用户', 'User') },
  { key: 'token_prefix', label: text('令牌前缀', 'Token prefix') }, { key: 'enabled', label: text('状态', 'Status') }
])
const rows = computed(() => (data.value || []).filter(token => Object.entries(filters.value).every(([key, value]) => !value || String(token[key as keyof VoidToken] ?? '').toLowerCase().includes(value.toLowerCase()))))
const name = ref('default')
const userId = ref('')
const allowed = ref('')
const showCreate = ref(false)
const creating = ref(false)
const secret = ref('')
const pending = ref<VoidToken | null>(null)
function createOpenChange(open: boolean) { showCreate.value = open }
function secretOpenChange(open: boolean) { if (!open) secret.value = '' }
function pendingOpenChange(open: boolean) { if (!open) pending.value = null }
async function create() {
  if (creating.value) return
  creating.value = true
  try {
    const result = await api.post<VoidTokenWithSecret>('/api/admin/tokens', {
      name: name.value.trim() || 'default',
      allowed_models: allowed.value.split(/[\n,]/).map(item => item.trim()).filter(Boolean),
      user_id: userId.value ? Number(userId.value) : undefined
    })
    secret.value = result.token
    showCreate.value = false
    name.value = 'default'; allowed.value = ''; userId.value = ''
    await refresh()
  } catch (cause) { toast.add({ title: String(cause), color: 'error' }) } finally { creating.value = false }
}
async function toggle(token: VoidToken, key: 'enabled' | 'debug_enabled') {
  try { await api.patch(`/api/admin/tokens/${token.id}`, { [key]: !token[key] }); await refresh() }
  catch (cause) { toast.add({ title: String(cause), color: 'error' }) }
}
async function confirm() {
  if (!pending.value) return
  const token = pending.value
  pending.value = null
  try {
    await api.del(`/api/admin/tokens/${token.id}`)
    await refresh()
  } catch (cause) { toast.add({ title: String(cause), color: 'error' }) }
}
</script>
<template>
  <div class="space-y-5">
    <div class="flex flex-wrap items-center justify-between gap-2"><h1 class="text-2xl font-bold">{{ text('全局令牌', 'Global tokens') }}</h1><div class="flex gap-2"><UButton icon="i-lucide-refresh-cw" variant="outline" :label="text('刷新', 'Refresh')" @click="refresh()" /><UButton icon="i-lucide-plus" :label="text('新建令牌', 'Create token')" @click="showCreate = true" /></div></div>
    <ConditionFilter v-model="filters" :fields="fields" />
    <UAlert v-if="error" color="error" :title="error.message" />
    <div v-else-if="status === 'pending'">{{ text('加载中…', 'Loading…') }}</div>
    <UCard v-else><div v-for="token in rows" :key="token.id" class="flex flex-wrap items-center gap-2 border-b border-default py-3 last:border-0"><div class="min-w-32 flex-1"><strong>{{ token.name }}</strong><div class="text-sm text-muted">{{ token.username }} · {{ token.token_prefix }}…</div></div><UBadge :color="token.enabled ? 'success' : 'neutral'">{{ token.enabled ? text('启用', 'Enabled') : text('禁用', 'Disabled') }}</UBadge><UButton icon="i-lucide-power" variant="ghost" :aria-label="text('切换状态', 'Toggle state')" @click="toggle(token, 'enabled')" /><UButton icon="i-lucide-bug" variant="ghost" :aria-label="text('切换调试', 'Toggle debug')" @click="toggle(token, 'debug_enabled')" /><UButton icon="i-lucide-trash" variant="ghost" color="error" :aria-label="text('删除', 'Delete')" @click="pending = token" /></div></UCard>
    <USlideover :open="showCreate" :title="text('新建令牌', 'Create token')" @update:open="createOpenChange"><template #body><form class="space-y-4" @submit.prevent="create"><UFormField :label="text('名称', 'Name')"><UInput v-model="name" class="w-full" /></UFormField><UFormField :label="text('用户 ID（留空为自己）', 'User ID (blank for self)')"><UInput v-model="userId" type="number" class="w-full" /></UFormField><UFormField :label="text('允许的模型，逗号分隔', 'Allowed models, comma-separated')"><UTextarea v-model="allowed" class="w-full" /></UFormField><UButton type="submit" :loading="creating" :label="text('新建', 'Create')" /></form></template></USlideover>
    <USlideover :open="!!secret" :title="text('请立即保存令牌', 'Save the token now')" @update:open="secretOpenChange"><template #body><code class="block break-all rounded bg-elevated p-3">{{ secret }}</code></template></USlideover>
    <UModal :open="!!pending" :title="text('删除令牌？', 'Delete token?')" @update:open="pendingOpenChange"><template #body><div class="flex justify-end gap-2"><UButton variant="outline" :label="text('取消', 'Cancel')" @click="pending = null" /><UButton color="error" :label="text('确认', 'Confirm')" @click="confirm" /></div></template></UModal>
  </div>
</template>
