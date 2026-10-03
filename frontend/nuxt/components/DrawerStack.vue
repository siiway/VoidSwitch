<script setup lang="ts">
const { stack, warning, close, syncHistory, discardTop } = useDrawers()
const { text } = useUiLocale()
const route = useRoute()
const shaking = ref(false)
const mounted = ref(false)
const back = (event: PopStateEvent) => {
  if (stack.value.length) syncHistory(Number(event.state?.drawerDepth) || 0)
}
const beforeUnload = (e: BeforeUnloadEvent) => {
  if (stack.value.some(item => item.dirty)) { e.preventDefault(); e.returnValue = '' }
}
watch(stack, (items) => {
  if (mounted.value && items.length === 0 && (location.search.includes('provider=') || location.search.includes('model='))) {
    history.replaceState({ ...history.state, drawerDepth: 0, drawerDirect: false }, '', route.path)
  }
})
watch(() => route.path, () => {
  if (!stack.value.some(item => item.dirty) && stack.value.length) { stack.value = []; warning.value = false }
})
function requestClose() {
  if (stack.value.at(-1)?.dirty) {
    warning.value = true
    shaking.value = true
    window.setTimeout(() => shaking.value = false, 210)
  } else if (history.state?.drawerDirect) {
    close()
  } else if (history.state?.drawerDepth) {
    history.back()
  } else {
    close()
  }
}
function save() { window.dispatchEvent(new CustomEvent('vs-save-drawer', { detail: stack.value.at(-1)?.id })) }
function discard() {
  discardTop()
  if (history.state?.drawerDirect) close(true)
  else if (history.state?.drawerDepth) history.back()
  else close(true)
}
onMounted(() => {
  mounted.value = true
  window.addEventListener('popstate', back)
  window.addEventListener('beforeunload', beforeUnload)
})
onUnmounted(() => { window.removeEventListener('popstate', back); window.removeEventListener('beforeunload', beforeUnload) })
</script>
<template>
  <template v-for="(entry, index) in stack" :key="index">
    <USlideover :open="true" :overlay="index === 0" :modal="index === stack.length - 1" :dismissible="false" :close="false" :ui="{ content: 'max-w-2xl' }" @close:prevent="index === stack.length - 1 && requestClose()">
      <template #content>
        <div class="stack-panel flex h-full flex-col bg-default" :data-behind="index < stack.length - 1" :class="{ 'stack-shake': shaking && index === stack.length - 1 }">
          <header class="flex items-center gap-3 border-b border-default p-4">
            <UButton icon="i-lucide-arrow-left" color="neutral" variant="ghost" :aria-label="text('返回', 'Back')" @click="requestClose" />
            <h2 class="flex-1 font-semibold">{{ entry.kind }} {{ entry.id }}</h2>
            <UButton icon="i-lucide-x" color="neutral" variant="ghost" :aria-label="text('关闭', 'Close')" @click="requestClose" />
          </header>
          <div v-if="warning && index === stack.length - 1" class="flex flex-wrap items-center gap-2 border-b border-warning bg-warning/10 p-3 text-sm">
            {{ text('有未保存的更改', 'You have unsaved changes') }}
            <UButton v-if="entry.kind === 'provider' || entry.kind === 'route'" size="xs" :label="text('保存', 'Save')" @click="save" />
            <UButton size="xs" color="error" variant="outline" :label="text('放弃更改', 'Discard')" @click="discard" />
            <UButton size="xs" color="neutral" variant="ghost" :label="text('继续编辑', 'Continue editing')" @click="warning = false" />
          </div>
          <div class="flex-1 overflow-y-auto p-4"><DrawerContent :entry="entry" /></div>
        </div>
      </template>
    </USlideover>
  </template>
</template>
