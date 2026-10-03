<script setup lang="ts">
const { load: loadLocale } = useUiLocale()
const { load: loadPrefs } = useWorkbench()
const { user } = useSession()
watch(user, (value) => { if (value) loadPrefs() }, { immediate: true })
onMounted(loadLocale)
</script>

<template>
  <UApp>
    <NuxtLayout><NuxtPage /></NuxtLayout>
  </UApp>
</template>
