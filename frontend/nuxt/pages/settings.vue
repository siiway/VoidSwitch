<script setup lang="ts">
import type { LoginTokenStatus, LoginTokenWithSecret } from '../types'
const api = useApi()
const { isOwner } = useSession()
const { text } = useUiLocale()
const toast = useToast()
const { data, error, status, refresh } = await useAsyncData('system-settings', () => api.get<{ values: Record<string, unknown> }>('/api/admin/settings'))
const { data: loginToken, refresh: refreshLoginToken } = await useAsyncData('my-login-token', () => api.get<LoginTokenStatus>('/api/me/login-token'))
const values = ref<Record<string, unknown>>({})
const saving = ref(false)
const warning = ref(false)
const revealed = ref('')
const rotating = ref(false)
const showRotate = ref(false)
const sections = [
  { label: ['代理与节点', 'Proxy & nodes'], keys: ['proxy_switching_enabled', 'static_proxy_url', 'max_proxy_failures', 'proxy_probe_interval_seconds', 'node_default_probe_url', 'node_probe_interval_seconds'] },
  { label: ['密钥', 'Keys'], keys: ['max_key_failures', 'auto_disable_zero_balance', 'balance_probe_enabled', 'balance_probe_interval_seconds'] },
  { label: ['路由', 'Routing'], keys: ['upstream_select_mode', 'upstream_rank_algorithm', 'upstream_rank_alpha', 'upstream_rank_beta', 'upstream_rank_gamma', 'upstream_max_keys_per_attempt'] },
  { label: ['超时与连接', 'Timeouts & connections'], keys: ['connect_timeout_seconds', 'request_timeout_seconds', 'stream_idle_timeout_seconds', 'max_connections'] },
  { label: ['日志', 'Logs'], keys: ['logs_page_size', 'log_cleanup_enabled', 'audit_log_retention_days', 'request_log_retention_days'] }
]
const options: Record<string, string[]> = {
  upstream_select_mode: ['best', 'balanced', 'pinned_best', 'pinned_balanced'],
  upstream_rank_algorithm: ['weighted', 'tiered'],
  upstream_all_cooled_behavior: ['ignore_cooldown', 'fail_fast']
}
const known = new Set(sections.flatMap(section => section.keys))
const hidden = new Set(['proxy_resurrector_enabled', 'proxy_probe_url', 'operation_rate_limit_window_seconds', 'operation_rate_limit_max_requests', 'call_rate_limit_window_seconds', 'call_rate_limit_max_requests'])
const proxyOnly = new Set(['max_proxy_failures', 'proxy_probe_interval_seconds', 'proxy_health_check_enabled'])
const dependencies: Record<string, string> = { balance_probe_interval_seconds: 'balance_probe_enabled', balance_rescan_interval_seconds: 'balance_rescan_enabled', log_cleanup_interval_seconds: 'log_cleanup_enabled' }
function visible(key: string) {
  if (hidden.has(key)) return false
  if (key === 'static_proxy_url') return values.value.proxy_switching_enabled === false
  if (proxyOnly.has(key) && values.value.proxy_switching_enabled === false) return false
  if (dependencies[key] && values.value[dependencies[key]] === false) return false
  return true
}
const otherKeys = computed(() => Object.keys(values.value).filter(key => !known.has(key) && visible(key)))
const originalValues = ref<Record<string, unknown>>({})
const initialized = ref(false)
watch(data, result => {
  if (result && !initialized.value) {
    values.value = { ...result.values }
    originalValues.value = { ...result.values }
    initialized.value = true
  }
}, { immediate: true })
const dirty = computed(() => initialized.value && Object.entries(values.value).some(([key, value]) => JSON.stringify(value) !== JSON.stringify(originalValues.value[key])))
function update(key: string, value: unknown) { values.value = { ...values.value, [key]: value } }
async function save() {
  if (!isOwner.value || saving.value) return
  saving.value = true
  try {
    const changes = Object.fromEntries(Object.entries(values.value).filter(([key, value]) => JSON.stringify(value) !== JSON.stringify(originalValues.value[key])))
    const result = await api.put<{ values: Record<string, unknown> }>('/api/admin/settings', { values: changes })
    originalValues.value = { ...result.values }
    values.value = { ...result.values }
    warning.value = false
    toast.add({ title: text('设置已保存', 'Settings saved'), color: 'success' })
    await refresh()
  } catch (cause) { toast.add({ title: String(cause), color: 'error' }) } finally { saving.value = false }
}
async function rotateToken() {
  if (rotating.value) return
  rotating.value = true
  try {
    const token = await api.post<LoginTokenWithSecret>('/api/me/login-token/rotate')
    revealed.value = token.token
    showRotate.value = false
    await refreshLoginToken()
  } catch (cause) { toast.add({ title: String(cause), color: 'error' }) } finally { rotating.value = false }
}
onBeforeRouteLeave(() => { if (dirty.value) { warning.value = true; return false } })
const beforeUnload = (event: BeforeUnloadEvent) => { if (dirty.value) { event.preventDefault(); event.returnValue = '' } }
onMounted(() => window.addEventListener('beforeunload', beforeUnload))
onUnmounted(() => window.removeEventListener('beforeunload', beforeUnload))
function revealOpenChange(open: boolean) { if (!open) revealed.value = '' }
function confirmOpenChange(open: boolean) { if (!open) showRotate.value = false }
</script>
<template>
  <div class="space-y-5">
    <div class="flex flex-wrap items-center justify-between gap-2"><h1 class="text-2xl font-bold">{{ text('系统设置', 'System settings') }}</h1><UButton icon="i-lucide-refresh-cw" variant="outline" :label="text('刷新', 'Refresh')" @click="refresh()" /></div>
    <UAlert v-if="!isOwner" color="info" :title="text('你可以查看设置；只有所有者可以修改。', 'You can view settings; only owners can edit.')" />
    <UAlert v-if="error" color="error" :title="error.message" />
    <div v-else-if="status === 'pending'">{{ text('加载中…', 'Loading…') }}</div>
    <template v-else>
      <UCard v-for="section in sections" :key="section.label[0]" class="space-y-4">
        <h2 class="font-semibold">{{ text(section.label[0]!, section.label[1]!) }}</h2>
        <div v-for="key in section.keys.filter(key => key in values && visible(key))" :key="key" class="flex flex-wrap items-center justify-between gap-2 border-t border-default py-2"><label class="text-sm">{{ key.replaceAll('_', ' ') }}</label><UCheckbox v-if="typeof values[key] === 'boolean'" :model-value="values[key] as boolean" :disabled="!isOwner" @update:model-value="update(key, $event)" /><USelect v-else-if="options[key]" :model-value="String(values[key] ?? '')" :items="options[key]" :disabled="!isOwner" class="w-48" @update:model-value="update(key, $event)" /><UInput v-else :model-value="String(values[key] ?? '')" :type="typeof values[key] === 'number' ? 'number' : 'text'" :disabled="!isOwner" class="w-48" @update:model-value="update(key, typeof values[key] === 'number' ? Number($event) : $event)" /></div>
      </UCard>
      <UCard v-if="otherKeys.length" class="space-y-3"><h2 class="font-semibold">{{ text('其他', 'Other') }}</h2><div v-for="key in otherKeys" :key="key" class="flex flex-wrap items-center justify-between gap-2 border-t border-default py-2"><label class="text-sm">{{ key.replaceAll('_', ' ') }}</label><UCheckbox v-if="typeof values[key] === 'boolean'" :model-value="values[key] as boolean" :disabled="!isOwner" @update:model-value="update(key, $event)" /><UInput v-else :model-value="String(values[key] ?? '')" :type="typeof values[key] === 'number' ? 'number' : 'text'" :disabled="!isOwner" class="w-48" @update:model-value="update(key, typeof values[key] === 'number' ? Number($event) : $event)" /></div></UCard>
      <div v-if="isOwner" class="sticky bottom-2 flex flex-wrap items-center gap-2 rounded-lg border border-default bg-default p-3 shadow"><UButton :loading="saving" :disabled="!dirty" :label="text('保存更改', 'Save changes')" @click="save" /><span v-if="dirty" class="text-sm text-warning">{{ text('有未保存的更改', 'Unsaved changes') }}</span><UButton v-if="warning" size="sm" color="error" variant="outline" :label="text('放弃更改', 'Discard changes')" @click="values = { ...originalValues }; warning = false" /></div>
    </template>
    <UCard class="space-y-3"><h2 class="font-semibold">{{ text('个人登录令牌', 'Personal login token') }}</h2><p class="text-sm text-muted">{{ loginToken?.enabled ? loginToken.prefix : text('尚未创建', 'Not created') }}</p><UButton variant="outline" :label="text('创建或轮换', 'Create or rotate')" @click="showRotate = true" /></UCard>
    <UModal :open="showRotate" :title="text('轮换个人登录令牌？', 'Rotate personal login token?')" @update:open="confirmOpenChange"><template #body><div class="flex justify-end gap-2"><UButton variant="outline" :label="text('取消', 'Cancel')" @click="showRotate = false" /><UButton :loading="rotating" :label="text('确认', 'Confirm')" @click="rotateToken" /></div></template></UModal>
    <USlideover :open="!!revealed" :title="text('请立即保存登录令牌', 'Save your login token now')" @update:open="revealOpenChange"><template #body><code class="block break-all rounded bg-elevated p-3">{{ revealed }}</code></template></USlideover>
  </div>
</template>
