<template>
  <div class="stack">
    <Panel title="数据源优先级" sub="每类数据都会按顺序尝试，失败自动切换下一个（多源备用）">
      <template #extra>
        <label class="row small muted"><input type="checkbox" v-model="offline" @change="save" /> 离线样例模式</label>
        <button class="btn primary" @click="save">保存并生效</button>
      </template>
      <div v-for="(list, kind) in priority" :key="kind" class="row" style="padding:7px 0;border-bottom:1px dashed #232d40;flex-wrap:wrap">
        <b style="width:96px">{{ kindName(kind) }}</b>
        <template v-for="(s, i) in list" :key="s">
          <span class="chip" :style="{ borderColor: health(s) === 'ok' ? '#2f6f4f' : health(s) === 'bad' ? '#7a3040' : '#2e3a52' }">
            <span class="dim tiny">{{ i + 1 }}.</span> {{ nameOf(s) }}
            <b :style="{ color: health(s) === 'ok' ? '#00b578' : health(s) === 'bad' ? '#ff4d4f' : '#5f6d84' }">●</b>
            <span v-if="i < list.length - 1" style="cursor:pointer;margin-left:4px" @click="move(kind, i, 1)">⇄</span>
          </span>
          <span class="dim" v-if="i < list.length - 1">›</span>
        </template>
        <span class="dim tiny" style="margin-left:auto">{{ kindTip(kind) }}</span>
      </div>
      <div class="small dim" style="margin-top:10px;line-height:1.8">
        ● 绿色=最近调用成功，红色=失败，灰色=尚未调用。点击 ⇄ 可与后一个源交换优先级。<br />
        <b style="color:#ffb020">推荐配置（全部免费）：</b>
        行情 腾讯→新浪→东财；涨跌停池/龙虎榜/板块 东财→akshare；外围 东财→腾讯→新浪→Yahoo→Stooq；
        资讯 华尔街见闻→东财→新浪→财联社。装了 akshare 后可把它插到任意位置做兜底。
      </div>
    </Panel>

    <div class="grid" style="grid-template-columns:1fr 1fr">
      <Panel title="数据源健康度" sub="实时统计成功/失败次数与延迟">
        <table class="tbl">
          <thead><tr><th>数据源</th><th class="num">成功</th><th class="num">失败</th><th class="num">延迟ms</th><th>最近错误</th></tr></thead>
          <tbody>
            <tr v-for="(s, k) in sources" :key="k">
              <td><b>{{ nameOf(k) }}</b></td>
              <td class="num mono up">{{ s.ok }}</td>
              <td class="num mono" :class="s.fail ? 'down' : 'dim'">{{ s.fail }}</td>
              <td class="num mono muted">{{ s.ms }}</td>
              <td class="small dim" style="white-space:normal;max-width:280px">{{ s.last_error || '—' }}</td>
            </tr>
            <tr v-if="!Object.keys(sources).length"><td colspan="5" class="empty">还没有调用记录</td></tr>
          </tbody>
        </table>
        <div class="divider"></div>
        <div class="small muted">主机熔断（连续失败自动跳过一段时间）：</div>
        <div class="row-wrap small" style="margin-top:6px">
          <span class="chip" v-for="(v, k) in hosts" :key="k">
            {{ k }} <b>{{ v.fails }}次失败</b>
            <span v-if="v.blocked_seconds_left" class="down">熔断中 {{ v.blocked_seconds_left }}s</span>
          </span>
          <span class="dim" v-if="!Object.keys(hosts).length">无异常主机</span>
        </div>
      </Panel>

      <Panel title="指数/指标清单" sub="系统在看哪些指数，为什么">
        <div style="max-height:520px;overflow-y:auto">
          <div class="small muted" style="margin-bottom:6px"><b style="color:#ffb020">A股指数</b></div>
          <div v-for="i in (ind.indexes || [])" :key="i.key" style="padding:5px 0;border-bottom:1px dashed #232d40">
            <b>{{ i.name }}</b> <span class="dim mono tiny">{{ i.key }}</span>
            <div class="dim small" style="line-height:1.6">{{ i.role }}</div>
          </div>
          <div class="small muted" style="margin:12px 0 6px"><b style="color:#ffb020">外围市场</b></div>
          <div v-for="i in (ind.global || [])" :key="i.key" style="padding:5px 0;border-bottom:1px dashed #232d40">
            <b>{{ i.name }}</b> <span class="tag gray tiny">{{ i.group }}</span>
            <div class="dim small" style="line-height:1.6">{{ i.role }}</div>
          </div>
        </div>
      </Panel>
    </div>

    <Panel title="关于">
      <div class="small" style="line-height:2;color:#c8d3e2">
        <b style="color:#ffb020">复盘罗盘（游资版）</b> v1.0　·　后端 FastAPI + httpx + APScheduler + SQLite　·　前端 Vue3 + Vite + ECharts<br />
        全部数据来自公开免费接口：东方财富（push2 / push2delay / push2ex / datacenter / np-weblist）、腾讯财经（qt.gtimg.cn / web.ifzq.gtimg.cn）、
        新浪财经（hq.sinajs.cn / quotes.sina.cn / zhibo.sina.com.cn）、华尔街见闻（api-one.wallstcn.com）、财联社（可选，需签名）、
        Yahoo Finance / Stooq（海外兜底）、akshare / adata / baostock（可选兜底）。<br />
        <span class="dim">免责声明：本软件仅做数据聚合与经验规则输出，游资席位为民间公开归纳，不构成任何投资建议。</span>
      </div>
    </Panel>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import Panel from '../components/Panel.vue'
import { api } from '../api'
import { loadHealth, loadIndicators, store, toast } from '../store'

const priority = ref({}); const sources = ref({}); const hosts = ref({})
const offline = ref(false); const ind = ref({ indexes: [], global: [], sentiment: [] })

const NAMES = { eastmoney: '东方财富', tencent: '腾讯财经', sina: '新浪财经', wallstcn: '华尔街见闻', cls: '财联社',
  yahoo: 'Yahoo', stooq: 'Stooq', akshare: 'akshare', mock: '内置样例' }
const KINDS = { quote: '实时行情', kline: 'K线历史', limit_pool: '涨跌停池', sector: '板块资金', lhb: '龙虎榜',
  global: '外围市场', news: '快讯资讯', margin: '两融/北向' }
const TIPS = { quote: '腾讯最稳，新浪次之', kline: '腾讯日K无需鉴权', limit_pool: '东财 push2ex 独家口径',
  sector: '东财板块含主力净流入', lhb: '东财 datacenter 含营业部明细', global: '东财全球指数覆盖最全',
  news: '多源并发聚合去重', margin: '东财 datacenter 统计口径' }
const nameOf = k => NAMES[k] || k
const kindName = k => KINDS[k] || k
const kindTip = k => TIPS[k] || ''
const health = computed(() => k => {
  const s = sources.value[k] || sources.value[NAMES[k]]
  if (!s) return 'none'
  if (s.ok > 0 && (!s.last_error || s.ok > s.fail)) return 'ok'
  return s.fail > 0 ? 'bad' : 'none'
})

function move(kind, i, dir) {
  const arr = priority.value[kind]
  const j = i + dir
  if (j < 0 || j >= arr.length) return
  ;[arr[i], arr[j]] = [arr[j], arr[i]]
  priority.value = { ...priority.value }
}
async function save() {
  try { await api.saveSources({ priority: priority.value, offline: offline.value }); toast('已保存，新的优先级立即生效'); await loadHealth(); refresh() }
  catch (e) { toast('保存失败：' + e.message) }
}
function refresh() { sources.value = store.sources || {}; hosts.value = store.hosts || {}; offline.value = store.offline }

onMounted(async () => {
  await Promise.all([loadHealth(), loadIndicators()])
  priority.value = JSON.parse(JSON.stringify(store.priority || {}))
  ind.value = store.indicators || ind.value
  refresh()
})
</script>