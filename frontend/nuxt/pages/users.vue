<script setup lang="ts">
import type { User } from '../types'
const api = useApi()
const route = useRoute()
const session = useSession()
const { text } = useUiLocale()
const { data, status, error, refresh } = await useAsyncData('users', () => api.get<User[]>('/api/admin/users'))
const filters = ref<Record<string, string>>({})
const fields = computed(() => [
  { key: 'name', label: text('姓名/用户名', 'Name/username') },
  { key: 'role', label: text('角色', 'Role') },
  { key: 'enabled', label: text('状态', 'Status') }
])
const rows = computed(() => (data.value || []).filter(user => Object.entries(filters.value).every(([key, value]) => {
  if (!value) return true
  if (key === 'name') return [user.name, user.username, user.email, user.sub, String(user.id)].some(part => (part || '').toLowerCase().includes(value.toLowerCase()))
  return String(user[key as keyof User] ?? '').toLowerCase().includes(value.toLowerCase())
})))
const selected = ref<User | null>(null)
const toast = useToast()
const router = useRouter()
function select(user: User) { selected.value = user; void router.replace({ query: { ...route.query, user: String(user.id) } }) }
watch(() => route.query.user, (id) => {
  if (!id) selected.value = null
})
watch([data, () => route.query.user], ([users, id]) => {
  if (typeof id === 'string') selected.value = users?.find(user => String(user.id) === id) || null
}, { immediate: true })
function selectionOpenChange(open: boolean) {
  if (!open) {
    selected.value = null
    if (route.query.user) void router.replace({ query: { ...route.query, user: undefined } })
  }
}
const logoutTarget = ref<User | null>(null)
const loggingOut = ref(false)
async function forceLogout(user: User) {
  if (loggingOut.value) return
  loggingOut.value = true
  try { await api.post(`/api/admin/users/${user.id}/force-logout`); logoutTarget.value = null; toast.add({ title: text('已强制退出', 'Signed out'), color: 'success' }) }
  catch (e) { toast.add({ title: String(e), color: 'error' }) }
  finally { loggingOut.value = false }
}
function confirmOpenChange(open: boolean) { if (!open) logoutTarget.value = null }
function confirmLogout() { if (logoutTarget.value) void forceLogout(logoutTarget.value) }
</script>
<template>
  <div class="space-y-5">
    <div class="flex justify-between"><h1 class="text-2xl font-bold">{{ text('用户', 'Users') }}</h1><UButton icon="i-lucide-refresh-cw" variant="outline" :label="text('刷新', 'Refresh')" @click="refresh()" /></div>
    <ConditionFilter v-model="filters" :fields="fields" />
    <UAlert v-if="error" color="error" :title="error.message" />
    <div v-else-if="status === 'pending'">{{ text('加载中…', 'Loading…') }}</div>
    <UCard v-else>
      <button v-for="user in rows" :key="user.id" class="flex w-full items-center gap-2 border-b border-default py-3 text-left last:border-0 hover:bg-elevated" @click="select(user)">
        <div class="min-w-0 flex-1"><div class="font-medium">{{ user.name || user.username || user.sub }}</div><div class="truncate text-sm text-muted">{{ user.username || user.sub }}#{{ user.id }} · {{ user.email }}</div></div>
        <UBadge>{{ user.role }}</UBadge><UBadge :color="user.enabled ? 'success' : 'neutral'">{{ user.enabled ? text('启用', 'Enabled') : text('禁用', 'Disabled') }}</UBadge>
      </button>
    </UCard>
    <USlideover :open="!!selected" :title="selected?.name || selected?.username || selected?.sub" @update:open="selectionOpenChange">
      <template #body><div v-if="selected" class="space-y-4">
        <p>{{ selected.username || selected.sub }}#{{ selected.id }}</p>
        <p class="text-sm text-muted">{{ selected.email }} · {{ selected.role }}</p>
        <p v-if="!session.isStaff.value" class="text-sm text-muted">{{ text('仅可查看所管理身份组的用户', 'Only users in your managed groups are visible') }}</p>
        <UButton v-if="selected.id !== session.user.value?.id && (session.isOwner.value || selected.role === 'member')" variant="outline" icon="i-lucide-log-out" :label="text('强制退出', 'Force sign out')" @click="logoutTarget = selected" />
      </div></template>
    </USlideover>
    <UModal :open="!!logoutTarget" :title="text('强制退出该用户？', 'Force sign out this user?')" @update:open="confirmOpenChange"><template #body><div class="flex justify-end gap-2"><UButton variant="outline" :label="text('取消', 'Cancel')" @click="logoutTarget = null" /><UButton color="error" :loading="loggingOut" :label="text('确认', 'Confirm')" @click="confirmLogout" /></div></template></UModal>
  </div>
</template>
