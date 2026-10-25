import { reactive } from 'vue'
import { api } from './api'

export const store = reactive({
  health: null, sources: {}, hosts: {}, priority: {},
  offline: false, tradeDate: '', autoRefresh: false,
  loading: {}, toast: '', indicators: null, backendUp: false,
})

let timer = null

export async function loadHealth() {
  try {
    const h = await api.health()
    Object.assign(store, {
      health: h, sources: h.sources || {}, hosts: h.hosts || {}, priority: h.priority || {},
      offline: !!h.offline, tradeDate: h.trade_date || '', backendUp: true,
    })
  } catch (e) { store.backendUp = false }
}

export async function loadIndicators() {
  if (store.indicators) return store.indicators
  try { store.indicators = await api.indicators() }
  catch (e) { store.indicators = { indexes: [], global: [], sentiment: [] } }
  return store.indicators
}

export function toast(msg, ms = 2800) {
  store.toast = msg
  setTimeout(() => { if (store.toast === msg) store.toast = '' }, ms)
}

export function roleOf(key) {
  const all = [].concat(store.indicators?.indexes || [], store.indicators?.global || [])
  const hit = all.find(i => i.key === key)
  return hit ? hit.role : ''
}

export function indicatorHelp(name) {
  const hit = (store.indicators?.sentiment || []).find(i => i.name === name || i.key === name)
  return hit ? `${hit.name}：${hit.how}` : ''
}

export function setAutoRefresh(on, intervalSec, cb) {
  store.autoRefresh = on
  if (timer) { clearInterval(timer); timer = null }
  if (on && cb) timer = setInterval(cb, intervalSec * 1000)
}

export function srcTag(meta) {
  if (!meta) return ''
  const map = { eastmoney: '东财', tencent: '腾讯', sina: '新浪', wallstcn: '见闻', cls: '财联社',
    yahoo: 'Yahoo', stooq: 'Stooq', akshare: 'akshare', mock: '样例', multi: '多源', none: '无' }
  return map[meta.source] || meta.source || ''
}