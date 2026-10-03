<script setup lang="ts">
import type { Provider } from '../types'
const props = defineProps<{ id?: string }>()
const api = useApi()
const { stack, setDirty, close } = useDrawers()
const { text } = useUiLocale()
const toast = useToast()
const loading = ref(false)
const saving = ref(false)
const loadError = ref('')
const form = reactive({ name: '', base_url: '', enabled: true })
const original = ref('')
watch(() => props.id, async () => {
  loadError.value = ''
  if (!props.id) { form.name = ''; form.base_url = ''; form.enabled = true; original.value = JSON.stringify(form); return }
  loading.value = true
  try {
    const rows = await api.get<Provider[]>('/api/admin/providers')
    const row = rows.find(item => String(item.id) === props.id)
    if (!row) throw new Error(text('提供商不存在', 'Provider not found'))
    Object.assign(form, { name: row.name, base_url: row.base_url, enabled: row.enabled })
    original.value = JSON.stringify(form)
  } catch (error) { loadError.value = String(error) } finally { loading.value = false }
}, { immediate: true })
watch(form, () => {
  if (stack.value.at(-1)?.kind === 'provider' && stack.value.at(-1)?.id === props.id) setDirty(JSON.stringify(form) !== original.value)
})
const onSaveShortcut = (event: Event) => {
  if ((event as CustomEvent<string>).detail === props.id && stack.value.at(-1)?.kind === 'provider' && stack.value.at(-1)?.id === props.id) void save()
}
onMounted(() => {
  window.addEventListener('vs-save-drawer', onSaveShortcut)
})
onUnmounted(() => window.removeEventListener('vs-save-drawer', onSaveShortcut))
async function save() {
  if (saving.value) return
  if (loadError.value) return
  saving.value = true
  try {
    if (!props.id) throw new Error(text('新增提供商请使用完整表单', 'Use the complete form to add a provider'))
    await api.patch(`/api/admin/providers/${props.id}`, form)
    original.value = JSON.stringify(form)
    if (stack.value.at(-1)?.kind === 'provider' && stack.value.at(-1)?.id === props.id) setDirty(false)
    toast.add({ title: text('已保存', 'Saved'), color: 'success' })
    if (props.id && stack.value.at(-1)?.kind === 'provider' && stack.value.at(-1)?.id === props.id) {
      if (history.state?.drawerDirect) close(true)
      else if (history.state?.drawerDepth) history.back()
      else close(true)
    }
    await refreshNuxtData('providers')
  } catch (error) { toast.add({ title: String(error), color: 'error' }) } finally { saving.value = false }
}
</script>
<template>
  <div v-if="loading">{{ text('加载中…', 'Loading…') }}</div>
  <UAlert v-else-if="loadError" color="error" :title="loadError" />
  <div v-else class="space-y-6">
    <form class="space-y-4" @submit.prevent="save">
      <UFormField :label="text('名称', 'Name')"><UInput v-model="form.name" class="w-full" /></UFormField>
      <UFormField :label="text('地址', 'Base URL')"><UInput v-model="form.base_url" class="w-full" /></UFormField>
      <UCheckbox v-model="form.enabled" :label="text('启用', 'Enabled')" />
      <UButton type="submit" :loading="saving" :label="text('保存', 'Save')" />
    </form>
    <ProviderKeys v-if="id" :provider-id="Number(id)" />
  </div>
</template>
