export default defineNuxtRouteMiddleware(async (to) => {
  if (import.meta.server) return
  const session = useSession()
  if (!session.loaded.value) await session.refresh()
  if (to.path === '/login' || to.path === '/login/callback') {
    if (session.user.value && to.path === '/login') return navigateTo('/dashboard')
    return
  }
  if (!session.user.value) return navigateTo('/login')
  const implemented = ['/dashboard', '/providers', '/models', '/nodes', '/health', '/chat', '/token', '/tokens', '/users', '/role-groups', '/stats', '/logs', '/audit', '/settings', '/preferences']
  if (!implemented.some(path => to.path === path || to.path.startsWith(`${path}/`))) return navigateTo('/dashboard')
  if (to.path === '/preferences' && !session.isStaff.value) return navigateTo('/dashboard')
  if (['/providers', '/nodes', '/role-groups', '/settings'].some((path) => to.path.startsWith(path)) && !session.isStaff.value) return navigateTo('/dashboard')
  if (to.path.startsWith('/tokens') && !session.isOwner.value) return navigateTo('/dashboard')
  if (['/users', '/audit'].some((path) => to.path.startsWith(path)) && !session.isStaff.value && !session.isObserver.value) return navigateTo('/dashboard')
})
