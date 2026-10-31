<template>
  <div class="layout">
    <aside class="sidebar">
      <div class="logo">复盘罗盘<small>A股游资复盘工作台</small></div>
      <template v-for="(grp, gi) in groups" :key="gi">
        <div class="nav-sep txt">{{ grp.name }}</div>
        <div v-for="r in grp.items" :key="r.path" class="nav-item"
             :class="{ active: route.path === r.path }" @click="router.push(r.path)">
          <span class="ico">{{ r.meta.ico }}</span><span class="txt">{{ r.meta.title }}</span>
        </div>
      </template>
      <div style="flex:1"></div>
      <div class="txt tiny dim" style="padding:8px;line-height:1.7">
        数据源 {{ okCount }}/{{ totalCount }} 正常<br />
        <span v-if="store.offline" class="tag gold">离线样例模式</span>
      </div>
    </aside>

    <div class="main">
      <div class="topbar">
        <b style="font-size:14px">{{ route.meta.title }}</b>
        <span class="tag gray" v-if="store.tradeDate">交易日 {{ store.tradeDate }}</span>
        <span class="tag blue">{{ clock }}</span>
        <div style="flex:1"></div>
        <label class="row tiny muted" style="cursor:pointer">
          <input type="checkbox" v-model="auto" @change="toggleAuto" /> 自动刷新(60s)
        </label>
        <button class="btn" @click="reload" :disabled="busy">
          <span v-if="busy" class="spin"></span> {{ busy ? '刷新中' : '强制刷新' }}
        </button>
        <router-link to="/report"><button class="btn primary">生成复盘报告</button></router-link>
      </div>
      <div class="content">
        <div v-if="!store.backendUp" class="err" style="margin-bottom:12px">
          未连接到后端服务（{{ apiOrigin }}）。请先启动：<b>python backend\run.py</b> 或 <b>.\scripts\start.ps1</b>，
          然后刷新本页面。若使用 <b>npm run dev</b>，请确认 vite 代理指向后端实际监听的端口。
        </div>
        <!-- 节假日表缺年份时交易日历会悄悄算错，必须显眼提示 -->
        <div v-if="store.health && store.health.calendar && store.health.calendar.warning" class="err" style="margin-bottom:12px">
          {{ store.health.calendar.warning }}
        </div>
        <router-view v-slot="{ Component }">
          <keep-alive :max="6"><component :is="Component" :key="route.fullPath" /></keep-alive>
        </router-view>
      </div>
    </div>
    <div class="toast" v-if="store.toast">{{ store.toast }}</div>
  </div>
</template>

<script setup>
import { computed, onMounted, onBeforeUnmount, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { store, loadHealth, loadIndicators, setAutoRefresh, toast } from './store'
import { api } from './api'

const route = useRoute()
const router = useRouter()
// 不要硬编码端口：后端端口由 REVIEW_PORT 决定，写死的数字只会误导人去连错的地方
const apiOrigin = (typeof location !== 'undefined' && location.origin && location.origin !== 'null')
  ? location.origin : 'http://127.0.0.1:8000'
const clock = ref('')
const auto = ref(false)
const busy = ref(false)

const groups = computed(() => {
  const rs = router.getRoutes().filter(r => r.meta && r.meta.title)
  const map = {}
  rs.forEach(r => { const g = r.meta.grp || '其它'; (map[g] = map[g] || []).push(r) })
  return Object.keys(map).map(k => ({ name: k, items: map[k] }))
})
const okCount = computed(() => Object.values(store.sources).filter(s => s.ok > 0).length)
const totalCount = computed(() => Object.keys(store.sources).length || 0)

let ct = null
function tick() { clock.value = new Date().toLocaleTimeString('zh-CN', { hour12: false }) }

async function reload() {
  busy.value = true
  try { await api.refresh('all'); toast('缓存已清空并重新拉取'); await loadHealth() }
  catch (e) { toast('刷新失败：' + e.message) }
  finally { busy.value = false }
}
function toggleAuto() {
  setAutoRefresh(auto.value, 60, () => { loadHealth() })
  toast(auto.value ? '已开启自动刷新（每60秒）' : '已关闭自动刷新')
}

onMounted(async () => {
  tick(); ct = setInterval(tick, 1000)
  await Promise.all([loadHealth(), loadIndicators()])
})
onBeforeUnmount(() => { clearInterval(ct); setAutoRefresh(false) })
</script>