<script setup lang="ts">
import type { Provider, ModelEntry, User } from '../types'
import type { PrefixCategory } from '../composables/useWorkbench'
const props = defineProps<{ open: boolean, links: { to: string, label: string, icon: string }[] }>()
const emit = defineEmits<{ 'update:open': [open: boolean] }>()
const { prefs } = useWorkbench()
const api = useApi()
const session = useSession()
const { text } = useUiLocale()
const query = ref('')
const results = ref<{ label: string, to: string, group: PrefixCategory }[]>([])
let searchId = 0
watch([query, () => props.open], async () => {
  if (!props.open) return
  const current = ++searchId
  const prefix = Object.entries(prefs.value.prefixes).find(([, value]) => query.value.startsWith(value))?.[0] as PrefixCategory | undefined
  const allowed = !prefix || prefix === 'pages' || prefix === 'models' || (prefix === 'providers' && session.isStaff.value) || (prefix === 'users' && (session.isStaff.value || session.isObserver.value))
  if (!allowed) { results.value = []; return }
  const term = (prefix ? query.value.slice(prefix.length) : query.value).trim().toLowerCase()
  const groups = prefix ? [prefix] : ['pages', 'models', 'providers', 'users']
  const items: typeof results.value = []
  if (groups.includes('pages')) items.push(...props.links.map(link => ({ label: link.label, to: link.to, group: 'pages' as const })))
  if (term.length >= 1) {
    const requests: Promise<void>[] = []
    if (groups.includes('models')) requests.push(api.get<ModelEntry[]>('/api/models').then(rows => { items.push(...rows.map(row => ({ label: row.display_name || row.model_id, to: `/models?model=${encodeURIComponent(row.model_id)}`, group: 'models' as const }))) }).catch(() => {}))
    if (session.isStaff.value && groups.includes('providers')) requests.push(api.get<Provider[]>('/api/admin/providers').then(rows => { items.push(...rows.map(row => ({ label: row.name, to: `/providers?provider=${row.id}`, group: 'providers' as const }))) }).catch(() => {}))
    if ((session.isStaff.value || session.isObserver.value) && groups.includes('users')) requests.push(api.get<User[]>('/api/admin/users').then(rows => { items.push(...rows.map(row => ({ label: row.name || row.username || row.sub, to: `/users?user=${row.id}`, group: 'users' as const }))) }).catch(() => {}))
    await Promise.all(requests)
  }
  if (current === searchId) results.value = items.filter(item => item.label.toLowerCase().includes(term)).slice(0, 30)
}, { immediate: true })
function select(to: string) { emit('update:open', false); query.value = ''; void navigateTo(to) }
</script>
<template>
  <UModal :open="open" :title="text('快速跳转', 'Quick navigation')" @update:open="emit('update:open', $event)">
    <template #body>
      <UInput v-model="query" autofocus :placeholder="text('搜索；/ 页面、! 模型、@ 提供商、# 用户', 'Search; / pages, ! models, @ providers, # users')" class="w-full" />
      <div class="mt-3 max-h-80 overflow-y-auto">
        <button v-for="(item, index) in results" :key="index" class="flex w-full justify-between rounded px-3 py-2 text-left text-sm hover:bg-elevated" @click="select(item.to)">
          <span>{{ item.label }}</span><span class="text-muted">{{ item.group }}</span>
        </button>
      </div>
    </template>
  </UModal>
</template>
