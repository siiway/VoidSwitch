<script setup lang="ts">
const route = useRoute()
const session = useSession()
const { text, toggle, locale } = useUiLocale()
const colorMode = useColorMode()
const mobile = ref(false)
const palette = ref(false)
const nav = computed(() => [
  { title: text('概览', 'Overview'), links: [{ to: '/dashboard', label: text('仪表盘', 'Dashboard'), icon: 'i-lucide-layout-dashboard' }] },
  { title: text('路由', 'Routing'), links: [
    { to: '/providers', label: text('提供商', 'Providers'), icon: 'i-lucide-plug', staff: true },
    { to: '/models', label: text('模型', 'Models'), icon: 'i-lucide-box' },
    { to: '/nodes', label: text('节点', 'Nodes'), icon: 'i-lucide-network', staff: true },
    { to: '/health', label: text('健康', 'Health'), icon: 'i-lucide-heart-pulse' },
    { to: '/tokens', label: text('全局令牌', 'Global tokens'), icon: 'i-lucide-key-round', owner: true }
  ] },
  { title: text('账户', 'Account'), links: [
    { to: '/chat', label: text('聊天', 'Chat'), icon: 'i-lucide-message-circle' },
    { to: '/token', label: text('我的 API Key', 'My API keys'), icon: 'i-lucide-key' },
    { to: '/preferences', label: text('工作台偏好', 'Workbench preferences'), icon: 'i-lucide-sliders-horizontal', staff: true }
  ] },
  { title: text('运维', 'Operations'), links: [
    { to: '/users', label: text('用户', 'Users'), icon: 'i-lucide-users', observer: true },
    { to: '/stats', label: text('统计', 'Statistics'), icon: 'i-lucide-chart-no-axes-combined' },
    { to: '/logs', label: text('日志', 'Logs'), icon: 'i-lucide-scroll-text' },
    { to: '/audit', label: text('审计', 'Audit'), icon: 'i-lucide-shield-check', observer: true },
    { to: '/role-groups', label: text('身份组', 'Role groups'), icon: 'i-lucide-users-round', staff: true },
    { to: '/settings', label: text('系统设置', 'System settings'), icon: 'i-lucide-settings', staff: true }
  ] }
])
const links = computed(() => nav.value.flatMap(section => section.links).filter(item =>
  (!('staff' in item) || session.isStaff.value) && (!('owner' in item) || session.isOwner.value) && (!('observer' in item) || session.isStaff.value || session.isObserver.value)
))
const onShortcut = (e: KeyboardEvent) => {
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') { e.preventDefault(); palette.value = !palette.value }
}
onMounted(() => {
  window.addEventListener('keydown', onShortcut)
})
onUnmounted(() => window.removeEventListener('keydown', onShortcut))
function toggleTheme() { colorMode.preference = colorMode.value === 'dark' ? 'light' : 'dark' }
function signOut() { void session.logout() }
</script>

<template>
  <slot v-if="route.path.startsWith('/login')" />
  <div v-else class="flex h-screen overflow-hidden bg-default text-default">
    <div v-if="mobile" class="fixed inset-0 z-30 bg-black/50 lg:hidden" @click="mobile = false" />
    <aside :class="mobile ? 'translate-x-0' : '-translate-x-full lg:translate-x-0'" class="fixed inset-y-0 left-0 z-40 flex w-60 flex-col border-r border-default bg-default transition-transform lg:static">
      <div class="border-b border-default px-5 py-5 text-xl font-semibold">⚡ VoidSwitch</div>
      <nav class="flex-1 space-y-5 overflow-y-auto px-3 py-4">
        <section v-for="section in nav" :key="section.title">
          <div class="px-3 pb-1 text-xs font-semibold uppercase text-muted">{{ section.title }}</div>
          <template v-for="item in section.links" :key="item.to">
            <NuxtLink v-if="links.some(link => link.to === item.to)" :to="item.to" class="flex items-center gap-3 rounded-md px-3 py-2 text-sm hover:bg-elevated" :class="route.path === item.to ? 'bg-elevated font-semibold text-primary' : ''" @click="mobile = false">
              <UIcon :name="item.icon" class="size-4" />{{ item.label }}
            </NuxtLink>
          </template>
        </section>
      </nav>
      <div class="space-y-2 border-t border-default p-3 text-sm">
        <div class="truncate px-2">{{ session.user.value?.name || session.user.value?.username }} · {{ session.user.value?.role }}</div>
        <div class="flex gap-1">
          <UButton color="neutral" variant="ghost" icon="i-lucide-search" :aria-label="text('搜索', 'Search')" @click="palette = true" />
          <UButton color="neutral" variant="ghost" :label="locale === 'zh' ? 'EN' : '中'" @click="toggle" />
          <UButton color="neutral" variant="ghost" icon="i-lucide-moon" :aria-label="text('切换主题', 'Toggle theme')" @click="toggleTheme" />
          <UButton v-if="session.isStaff.value" to="/preferences" color="neutral" variant="ghost" icon="i-lucide-sliders-horizontal" :aria-label="text('工作台偏好', 'Workbench preferences')" />
          <UButton color="neutral" variant="ghost" icon="i-lucide-log-out" :aria-label="text('退出', 'Sign out')" @click="signOut" />
        </div>
      </div>
    </aside>
    <main class="min-w-0 flex-1 overflow-y-auto">
      <div class="border-b border-default p-2 lg:hidden"><UButton icon="i-lucide-menu" color="neutral" variant="ghost" @click="mobile = true" /></div>
      <div class="mx-auto max-w-7xl p-4 sm:p-6"><slot /></div>
    </main>
    <CommandPalette v-model:open="palette" :links="links" />
    <DrawerStack />
  </div>
</template>
