<template>
  <div class="stack">
    <!-- 情绪温度 + 核心指标 -->
    <div class="grid" style="grid-template-columns: 300px repeat(4, 1fr)">
      <div class="stat hl" style="display:flex;gap:14px;align-items:center">
        <EChart :option="gaugeOpt" :height="118" style="flex:0 0 132px" />
        <div>
          <div class="k">市场情绪温度</div>
          <div class="v" :style="{ color: senti.color || '#ffb020' }">{{ senti.score ?? '—' }}</div>
          <div class="row" style="margin-top:4px">
            <span class="tag gold">{{ senti.label || '—' }}</span>
            <span class="tag" :style="{ background: phaseBg, color: phaseFg }">
              {{ senti.phase ? senti.phase.phase : '—' }}
              <template v-if="senti.phase && senti.phase.score_delta"> ({{ senti.phase.score_delta > 0 ? '+' : '' }}{{ senti.phase.score_delta }})</template>
            </span>
          </div>
          <div class="d small" style="margin-top:6px;line-height:1.6">{{ senti.advice }}</div>
        </div>
      </div>
      <StatCard label="涨停 / 跌停" :value="`${m.limit_up ?? '—'} / ${m.limit_down ?? 0}`"
                :desc="`炸板 ${m.broken ?? 0} 家`" :help="h('涨停家数')" />
      <StatCard label="炸板率" :value="pctv(m.broken_rate)" :sign="false"
                :color="m.broken_rate > 35 ? '#ff4d4f' : m.broken_rate < 20 ? '#00b578' : '#ffb020'"
                :desc="`封板率 ${pctv(m.seal_rate)}`" :help="h('炸板率')" />
      <StatCard label="最高连板" :value="(m.max_boards || 0) + ' 板'" color="#ffb020"
                :desc="`连板 ${m.lianban_count ?? 0} 家 / 首板 ${m.first_board_count ?? 0} 家`" :help="h('最高连板')" />
      <StatCard label="昨涨停可成交溢价" :value="pctv(m.tradable_premium)" :sign="true"
                :desc="`样本 ${m.tradable_premium_sample ?? 0}/${m.premium_sample ?? 0}｜买不到 ${pctv(m.unbuyable_rate)}｜晋级率 ${pctv(m.promote_rate)}`"
                help="只统计今日开盘确实能买入的样本（剔除开盘即一字封死），开盘价->收盘价。收盘口径含买不到的票，已降级为参考值。" />
    </div>

    <div class="grid" style="grid-template-columns: 1.35fr 1fr">
      <!-- 指数 -->
      <Panel title="核心指数" :sub="`两市成交 ${ov.turnover ? ov.turnover.total_yi : '—'} 亿${ov.turnover && ov.turnover.estimated ? '（估算）' : ''}`" :loading="!ov.indices">
        <template #extra>
          <span class="tag gold" v-if="ov.turnover && ov.turnover.estimated">成交额估算</span>
          <span class="tag gray" v-if="ov.turnover && ov.turnover.level">{{ ov.turnover.level.label }}</span>
          <span class="src">{{ srcName }}</span>
        </template>
        <table class="tbl">
          <thead><tr><th>指数</th><th class="num">最新</th><th class="num">涨跌幅</th><th class="num">成交额(亿)</th><th class="num">振幅</th></tr></thead>
          <tbody>
            <tr v-for="i in ov.indices" :key="i.key">
              <td><span class="help" v-if="i.role" :title="i.role">?</span> {{ i.name }}</td>
              <td class="num mono">{{ num(i.price) }}</td>
              <td class="num"><PctText :v="i.pct" /></td>
              <td class="num mono muted">{{ num(i.amount_yi, 1) }}</td>
              <td class="num mono muted">{{ num(i.amplitude, 2) }}</td>
            </tr>
          </tbody>
        </table>
        <div class="divider"></div>
        <div class="kv small">
          <span class="kk">量能档位 <span class="help" :title="h('两市成交额')">?</span></span><span>{{ lv.label }}（{{ lv.tip }}）</span>
          <span class="kk">较昨日</span><span>{{ ov.turnover && ov.turnover.delta_yi !== null ? signed(ov.turnover.delta_yi, 0) + ' 亿' : '—' }}　5日均量 {{ ov.turnover && ov.turnover.ma5_yi ? Math.round(ov.turnover.ma5_yi) + ' 亿' : '—' }}</span>
          <span class="kk">涨跌家数 <span class="help" :title="h('上涨家数占比')">?</span></span>
          <span><span class="up">涨 {{ m.up ?? '—' }}</span> / <span class="down">跌 {{ m.down ?? '—' }}</span> / 平 {{ m.flat ?? '—' }}　占比 {{ pctv(m.up_ratio) }}</span>
        </div>
      </Panel>

      <!-- 涨跌分布 -->
      <Panel title="涨跌分布" sub="市场宽度：普涨还是分化">
        <EChart :option="histOpt" :height="230" />
        <div class="small muted center">涨停 {{ m.limit_up ?? 0 }} 家 · 涨幅&gt;5% {{ m.gt5_up ?? '—' }} 家 · 跌幅&gt;5% {{ m.lt5_down ?? '—' }} 家</div>
      </Panel>
    </div>

    <div class="grid" style="grid-template-columns: 1.35fr 1fr">
      <Panel title="指数走势 + 成交量" sub="量能是情绪的燃料">
        <template #extra>
          <span v-for="s in symList" :key="s.k" class="pill" :class="{ active: sym === s.k }" @click="sym = s.k">{{ s.n }}</span>
        </template>
        <EChart :option="klineOpt" :height="330" />
      </Panel>

      <div class="stack">
        <Panel title="外围信号" sub="隔夜与亚太，决定开盘策略">
          <template #extra><span class="tag" :class="sig.score >= 2 ? 'red' : sig.score <= -2 ? 'green' : 'gray'">{{ sig.overall || '—' }}</span></template>
          <div class="small" style="line-height:1.9">
            <div v-for="(s, i) in (sig.signals || []).slice(0, 6)" :key="i">
              <span class="tag" :class="s.level === '利好' ? 'red' : s.level === '利空' ? 'green' : 'gray'">{{ s.level }}</span>
              {{ s.text }}
            </div>
            <div v-if="!(sig.signals || []).length" class="empty">暂无外围数据</div>
          </div>
        </Panel>
        <Panel title="连板天梯" :sub="`最高 ${ladder.max_boards || 0} 板`" nopad tight>
          <template #extra><span class="help" :title="h('连板天梯')">?</span></template>
          <div style="padding:6px 10px">
            <div class="ladder-row" v-for="lv in (ladder.levels || []).slice(0, 5)" :key="lv.boards">
              <div class="ladder-lv">{{ lv.boards }}板</div>
              <div class="ladder-stocks">
                <span class="chip" v-for="s in lv.stocks.slice(0, 6)" :key="s.code">
                  {{ s.name }} <b class="tiny">{{ s.industry }}</b>
                </span>
                <span class="dim tiny" v-if="lv.count > 6">等{{ lv.count }}家</span>
              </div>
            </div>
            <div class="small muted" style="margin-top:6px">{{ ladder.comment }}</div>
          </div>
        </Panel>
      </div>
    </div>

    <div class="grid" style="grid-template-columns: 1fr 1fr">
      <Panel title="今日主线" sub="涨停结构 × 板块涨幅 × 主力资金" :how="how('mainline')">
        <template #extra><router-link to="/sectors" class="small">更多 →</router-link></template>
        <div v-for="l in (ml.main_lines || []).slice(0, 5)" :key="l.name" style="padding:7px 0;border-bottom:1px dashed #232d40">
          <div class="between">
            <b>{{ l.name }}</b>
            <span class="small">
              <span class="tag red">涨停{{ l.zt_count }}家</span>
              <span class="tag gold">{{ l.max_boards }}板</span>
              <PctText :v="l.pct" />
              <span class="muted"> 主力{{ signed(l.main_flow_yi, 1) }}亿</span>
            </span>
          </div>
          <div class="small dim" style="margin-top:3px">{{ l.reason }}</div>
          <div class="row-wrap small" style="margin-top:4px">
            <span class="chip" v-for="s in (l.stocks || []).slice(0, 5)" :key="s.code">{{ s.name }}<b>{{ s.boards }}板</b></span>
          </div>
        </div>
        <div v-if="!(ml.main_lines || []).length" class="empty">暂无主线数据</div>
      </Panel>

      <Panel title="最新快讯" sub="多源聚合去重">
        <template #extra><router-link to="/news" class="small">更多 →</router-link></template>
        <div class="row-wrap small" style="margin-bottom:8px">
          <span class="tag purple" v-for="w in (nw.hot_words || []).slice(0, 10)" :key="w.word">{{ w.word }} {{ w.count }}</span>
        </div>
        <div style="max-height:250px;overflow-y:auto">
          <div class="news-item" :class="{ imp: n.important }" v-for="(n, i) in (nw.items || []).slice(0, 14)" :key="i">
            <div class="t">{{ n.title }}</div>
            <div class="m"><span>{{ shortTime(n.time) }}</span><span class="src">{{ n.source }}</span>
              <span class="tag gray" v-for="t in (n.tags || []).slice(0, 2)" :key="t">{{ t }}</span></div>
          </div>
        </div>
      </Panel>
    </div>
  </div>
</template>
<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import Panel from '../components/Panel.vue'
import StatCard from '../components/StatCard.vue'
import EChart from '../components/EChart.vue'
import PctText from '../components/PctText.vue'
import { api } from '../api'
import { indicatorHelp, indicatorHow as how, loadIndicators, srcTag } from '../store'
import { num, pct as pctf, signed, shortTime, scoreColor, phaseColor } from '../format'

const ov = ref({})
const senti = ref({})
const ladder = ref({})
const ml = ref({})
const sig = ref({})
const nw = ref({})
const kl = ref([])
const sym = ref('sh000001')
const symList = [{ k: 'sh000001', n: '上证' }, { k: 'sz399006', n: '创业板' },
  { k: 'sh000852', n: '中证1000' }, { k: 'sz399303', n: '国证2000' }, { k: 'sh000688', n: '科创50' }]

const m = computed(() => senti.value.metrics || {})
const lv = computed(() => (ov.value.turnover || {}).level || {})
const srcName = computed(() => srcTag(ov.value.meta))
const pctv = v => (v === null || v === undefined ? '—' : Number(v).toFixed(2) + '%')
const h = n => indicatorHelp(n)
const phaseFg = computed(() => phaseColor((senti.value.phase || {}).phase))
const phaseBg = computed(() => phaseFg.value + '22')

const gaugeOpt = computed(() => ({
  grid: null, tooltip: null,
  series: [{
    type: 'gauge', startAngle: 210, endAngle: -30, min: 0, max: 100, radius: '100%',
    center: ['50%', '62%'], progress: { show: true, width: 10, itemStyle: { color: scoreColor(senti.value.score || 0) } },
    axisLine: { lineStyle: { width: 10, color: [[1, '#1a2233']] } },
    axisTick: { show: false }, splitLine: { show: false }, axisLabel: { show: false },
    pointer: { show: false }, anchor: { show: false },
    detail: { show: false }, data: [{ value: senti.value.score || 0 }],
  }],
}))

const histOpt = computed(() => {
  const hs = m.value.histogram || []
  return {
    grid: { left: 42, right: 12, top: 18, bottom: 44 },
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
    xAxis: { type: 'category', data: hs.map(x => x.label), axisLabel: { rotate: 42, color: '#8d9bb1', fontSize: 10 },
      axisLine: { lineStyle: { color: '#232d40' } } },
    yAxis: { type: 'value', splitLine: { lineStyle: { color: '#1a2233' } }, axisLabel: { color: '#5f6d84' } },
    series: [{
      type: 'bar', data: hs.map(x => ({
        value: x.value,
        itemStyle: { color: x.type === 'up' || x.type === 'limit_up' ? (x.type === 'limit_up' ? '#ff3b3b' : '#ff6b6b')
          : x.type === 'down' || x.type === 'limit_down' ? (x.type === 'limit_down' ? '#00875a' : '#00b578') : '#5f6d84' },
      })), barWidth: '62%',
    }],
  }
})

const klineOpt = computed(() => {
  const rows = kl.value || []
  const dates = rows.map(r => r[0])
  const ohlc = rows.map(r => [r[1], r[2], r[4], r[3]])   // [open, close, low, high]
  const vols = rows.map((r, i) => ({ value: r[5], itemStyle: { color: r[2] >= r[1] ? 'rgba(255,77,79,.55)' : 'rgba(0,181,120,.5)' } }))
  const closes = rows.map(r => r[2])
  const ma = (n) => closes.map((_, i) => (i < n - 1 ? null : +(closes.slice(i - n + 1, i + 1).reduce((a, b) => a + b, 0) / n).toFixed(2)))
  return {
    grid: [{ left: 52, right: 14, top: 16, height: '58%' }, { left: 52, right: 14, top: '76%', height: '18%' }],
    tooltip: { trigger: 'axis', axisPointer: { type: 'cross' } },
    xAxis: [
      { type: 'category', data: dates, boundaryGap: true, axisLabel: { color: '#5f6d84', fontSize: 10 }, axisLine: { lineStyle: { color: '#232d40' } } },
      { type: 'category', gridIndex: 1, data: dates, axisLabel: { show: false }, axisLine: { lineStyle: { color: '#232d40' } } },
    ],
    yAxis: [
      { scale: true, splitLine: { lineStyle: { color: '#1a2233' } }, axisLabel: { color: '#5f6d84' } },
      { gridIndex: 1, splitLine: { show: false }, axisLabel: { color: '#5f6d84', fontSize: 9, formatter: v => (v / 1e8).toFixed(0) + '亿' } },
    ],
    dataZoom: [{ type: 'inside', xAxisIndex: [0, 1], start: Math.max(0, 100 - 60 / Math.max(1, rows.length) * 100), end: 100 }],
    series: [
      { type: 'candlestick', data: ohlc, itemStyle: { color: '#ff4d4f', color0: '#00b578', borderColor: '#ff4d4f', borderColor0: '#00b578' } },
      { type: 'line', data: ma(5), smooth: true, showSymbol: false, lineStyle: { width: 1, color: '#ffb020' }, name: 'MA5' },
      { type: 'line', data: ma(20), smooth: true, showSymbol: false, lineStyle: { width: 1, color: '#4c9aff' }, name: 'MA20' },
      { type: 'bar', xAxisIndex: 1, yAxisIndex: 1, data: vols, name: '成交量' },
    ],
  }
})

async function loadK() {
  try { const r = await api.kline(sym.value, 150); kl.value = r.items || [] } catch (e) { kl.value = [] }
}

async function loadAll() {
  await loadIndicators()
  const [a, b, c, d, e, f] = await Promise.allSettled([
    api.marketOverview(), api.sentiment(), api.ladder(), api.mainline(), api.global(), api.news({ limit: 40 }),
  ])
  if (a.status === 'fulfilled') ov.value = a.value
  if (b.status === 'fulfilled') senti.value = b.value
  if (c.status === 'fulfilled') ladder.value = c.value
  if (d.status === 'fulfilled') ml.value = d.value
  if (e.status === 'fulfilled') sig.value = e.value.signal || {}
  if (f.status === 'fulfilled') nw.value = f.value
  loadK()
}
watch(sym, loadK)
onMounted(loadAll)
defineExpose({ reload: loadAll })
</script>