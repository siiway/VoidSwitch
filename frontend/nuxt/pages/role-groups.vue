<script setup lang="ts">
import type { RoleGroup, RoleGroupMember } from '../types'
const api = useApi()
const { text } = useUiLocale()
const { isOwner } = useSession()
const { data, status, error, refresh } = await useAsyncData('role-groups', () => api.get<RoleGroup[]>('/api/admin/role-groups'))
const selected = ref<RoleGroup | null>(null)
const members = ref<RoleGroupMember[]>([])
const memberError = ref('')
const memberLoading = ref(false)
const toast = useToast()
async function open(group: RoleGroup) {
  selected.value = group
  memberError.value = ''
  members.value = []
  memberLoading.value = true
  try {
    const list = await api.get<RoleGroupMember[]>(`/api/admin/role-groups/${group.id}/members`)
    if (selected.value?.id === group.id) members.value = list
  } catch (e) { if (selected.value?.id === group.id) memberError.value = String(e) }
  finally { if (selected.value?.id === group.id) memberLoading.value = false }
}
async function remove(group: RoleGroup) {
  await api.del(`/api/admin/role-groups/${group.id}`)
  selected.value = null
  await refresh()
}
const pendingDelete = ref<RoleGroup | null>(null)
const deleting = ref(false)
function closeSelected(open: boolean) { if (!open) { selected.value = null; memberLoading.value = false } }
function closeDelete(open: boolean) { if (!open) pendingDelete.value = null }
async function confirmDelete() {
  if (!pendingDelete.value || deleting.value) return
  deleting.value = true
  try { await remove(pendingDelete.value); pendingDelete.value = null }
  catch (e) { toast.add({ title: String(e), color: 'error' }) }
  finally { deleting.value = false }
}
</script>
<template>
  <div class="space-y-5">
    <div class="flex justify-between"><h1 class="text-2xl font-bold">{{ text('身份组', 'Role groups') }}</h1><UButton icon="i-lucide-refresh-cw" variant="outline" :label="text('刷新', 'Refresh')" @click="refresh()" /></div>
    <UAlert v-if="error" color="error" :title="error.message" />
    <div v-else-if="status === 'pending'">{{ text('加载中…', 'Loading…') }}</div>
    <UCard v-else><button v-for="group in data" :key="group.id" class="flex w-full items-center gap-3 border-b border-default py-3 text-left last:border-0 hover:bg-elevated" @click="open(group)">
      <div class="flex-1"><strong>{{ group.name }}</strong><p class="text-sm text-muted">{{ group.description || group.slug }} · {{ group.member_count }} {{ text('成员', 'members') }}</p></div>
      <UBadge v-if="group.builtin" color="neutral">{{ text('内置', 'Built-in') }}</UBadge>
    </button></UCard>
    <USlideover :open="!!selected" :title="selected?.name" @update:open="closeSelected">
      <template #body><div v-if="selected" class="space-y-5">
        <p class="text-sm text-muted">{{ selected.description }}</p>
        <div class="font-semibold">{{ text('成员', 'Members') }}</div>
        <div v-if="memberLoading" class="text-sm text-muted">{{ text('加载中…', 'Loading…') }}</div>
        <UAlert v-if="memberError" color="error" :title="memberError" />
        <div v-for="member in members" :key="member.user_id" class="border-b border-default py-2 text-sm">{{ member.name }} · {{ member.role }} <UBadge v-if="member.is_admin" color="info">admin</UBadge></div>
        <UButton v-if="!selected.builtin && isOwner" color="error" variant="outline" :label="text('删除身份组', 'Delete role group')" @click="pendingDelete = selected" />
      </div></template>
    </USlideover>
    <UModal :open="!!pendingDelete" :title="text('删除身份组？', 'Delete role group?')" @update:open="closeDelete"><template #body><div class="flex justify-end gap-2"><UButton variant="outline" :label="text('取消', 'Cancel')" @click="pendingDelete = null" /><UButton color="error" :loading="deleting" :label="text('删除', 'Delete')" @click="confirmDelete" /></div></template></UModal>
  </div>
</template>
