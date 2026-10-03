export type DrawerEntry = { kind: 'provider' | 'model' | 'route', id?: string, dirty?: boolean }

export function useDrawers() {
  const stack = useState<DrawerEntry[]>('drawer-stack', () => [])
  const warning = useState('drawer-warning', () => false)
  function open(entry: DrawerEntry) {
    stack.value = [...stack.value, entry]
    if (import.meta.client) history.pushState({ ...history.state, drawerDepth: stack.value.length, drawerDirect: false }, '', location.href)
  }
  function close(force = false) {
    if (stack.value.at(-1)?.dirty && !force) { warning.value = true; return false }
    warning.value = false
    stack.value = stack.value.slice(0, -1)
    if (import.meta.client && history.state?.drawerDepth) history.replaceState({ ...history.state, drawerDepth: stack.value.length }, '', location.href)
    return true
  }
  function setDirty(dirty: boolean, kind?: DrawerEntry['kind'], id?: string) {
    const entry = kind ? stack.value.find(item => item.kind === kind && item.id === id) : stack.value.at(-1)
    if (entry) entry.dirty = dirty
  }
  function syncHistory(depth: number) {
    if (depth < stack.value.length) {
      if (stack.value.slice(depth).some(item => item.dirty)) {
        warning.value = true
        history.pushState({ ...history.state, drawerDepth: stack.value.length }, '', location.href)
      } else {
        warning.value = false
        stack.value = stack.value.slice(0, depth)
      }
    }
  }
  function discardTop() {
    const top = stack.value.at(-1)
    if (top) top.dirty = false
    warning.value = false
  }
  return { stack, warning, open, close, setDirty, syncHistory, discardTop }
}
