<template>
  <div class="stack">
    <div class="grid" style="grid-template-columns:repeat(6,1fr)">
      <StatCard label="情绪总分" :value="s.score ?? '—'" :color="scoreColor(s.score)" :bar="s.score"
                :desc="bandDesc" :help="(s.score_band || {}).note" />
      <StatCard label="涨停家数" :value="m.limit_up ?? '—'" :desc="`首板${m.first_board_count ?? 0} / 连板${m.lianban_count ?? 0}`" :help="h('涨停家数')" />
      <StatCard label="跌停家数" :value="m.limit_down ?? 0" :color="(m.limit_down || 0) > 10 ? '#ff4d4f' : '#00b578'" :help="h('跌停家数')" />
      <StatCard label="炸板率" :value="pctv(m.broken_rate)" :color="(m.broken_rate || 0) > 35 ? '#ff4d4f' : '#ffb020'"
                :desc="`炸板 ${m.broken ?? 0} 家`" :help="h('炸板率')" />
      <StatCard label="最高连板" :value="(m.max_boards || 0) + ' 板'" color="#ffb020" :help="h('最高连板')" />
      <StatCard label="昨涨停可成交溢价" :value="pctv(m.tradable_premium)" :sign="true"
                :desc="premDesc" :help="premHelp">
        <template #badge>
          <span class="tag gold tiny" v-if="(s.low_confidence_factors || []).includes('tradable_premium')">样本不足</span>
        </template>
      </StatCard>
    </div>

    <div class="grid" style="grid-template-columns:1.4fr 1fr">
      <Panel title="情绪周期曲线" sub="情绪分/涨停家数/最高板，用于识别冰点→修复→发酵→高潮→退潮">
        <EChart :option="histOpt" :height="300" />
      </Panel>
      <Panel title="情绪因子拆解" :sub="`加权总分 ${s.score ?? '—'}`">
        <EChart :option="compOpt" :height="260" />
        <div class="small muted" style="line-height:1.6;margin-top:4px">
          有效自由度
          <b :style="{ color: fi.effective_factors && fi.effective_factors < 2.5 ? '#ffcf70' : '#63d6a3' }">
            {{ fi.effective_factors ?? '样本不足' }}</b>
          / 名义 {{ fi.nominal_factors ?? 7 }} 个因子<span v-if="fi.verdict"> · {{ fi.verdict }}</span>
          <div v-if="!fi.effective_factors">{{ fi.note }}</div>
          <div v-if="(s.low_confidence_factors || []).length" style="color:#ffcf70">
            低置信因子（样本不足已退回中性分）：{{ (s.low_confidence_factors || []).join('、') }}
          </div>
        </div>
      </Panel>
    </div>

    <div class="grid" style="grid-template-columns:1fr 1fr">
      <Panel title="周期阶段判定" sub="规则引擎输出">
        <div class="row" style="gap:12px;margin-bottom:10px">
          <span class="tag" :style="{ background: phaseFg + '22', color: phaseFg, fontSize: '14px', padding: '5px 14px' }">
            {{ (s.phase || {}).phase || '—' }}
          </span>
          <span class="small muted">{{ (s.phase || {}).desc }}</span>
        </div>
        <div class="kv small">
          <span class="kk">情绪分变化</span><span>{{ (s.phase || {}).score_delta ?? '—' }}（趋势：{{ (s.phase || {}).trend || '—' }}）</span>
          <span class="kk">操作建议</span><span>{{ s.advice }}</span>
          <span class="kk">封板率</span><span>{{ pctv(m.seal_rate) }}（涨停 / (涨停+炸板)）</span>
          <span class="kk">一字板</span><span>{{ m.one_word_count ?? 0 }} 家（一字多=分歧小但买不进）</span>
          <span class="kk">未知板型</span><span>{{ m.unknown_board_count ?? 0 }} 家（源缺首封时间，不再按一字板处理）</span>
          <span class="kk">尾盘板</span><span>{{ m.late_board_count ?? 0 }} 家（尾盘偷袭，次日溢价差）</span>
          <span class="kk">烂板</span><span>{{ m.bad_board_count ?? 0 }} 家（炸板≥2次，谨慎接力）</span>
          <span class="kk">涨停封单合计</span><span>{{ m.fund_total_yi ?? '—' }} 亿，平均封成比 {{ m.avg_seal_ratio ?? '—' }}%</span>
        </div>
        <div class="divider"></div>
        <div class="small muted" style="line-height:1.8">
          <b style="color:#ffb020">游资用法：</b>情绪分是「仓位油门」。分数上行 + 最高板抬升 = 加仓窗口；
          分数见顶回落 + 炸板率抬升 = 立即减仓，不要等指数。
        </div>
      </Panel>

      <Panel title="昨日涨停今日表现" :sub="`共 ${pp.prev_limit_up || 0} 只（隔日溢价明细）`">
        <template #extra>
          <span class="tag gray">红盘率 {{ pctv(pp.red_ratio) }}</span>
          <span class="tag" :class="pp.premium_available ? 'blue' : 'gold'">
            开盘不可成交 {{ pp.unbuyable_count ?? '—' }} 只
          </span>
        </template>
        <div v-if="pp.premium_unavailable_reason" class="small muted" style="margin-bottom:8px">
          {{ pp.premium_unavailable_reason }}
        </div>
        <div class="scroll-y" style="max-height:300px">
          <table class="tbl">
            <thead><tr><th>代码</th><th>名称</th><th class="num">收盘涨幅</th><th class="num">开盘隔夜</th>
              <th class="num">开盘→收盘</th><th>是否连板</th></tr></thead>
            <tbody>
              <tr v-for="r in (pp.sample || []).slice(0, 60)" :key="r.code">
                <td class="mono dim">{{ r.code }}</td><td>{{ r.name }}</td>
                <td class="num"><PctText :v="r.pct" /></td>
                <td class="num"><PctText :v="r.open_gap" /></td>
                <td class="num"><PctText :v="r.open_entry_pct" /></td>
                <td><span class="tag" :class="r.promoted ? 'red' : 'gray'">{{ r.promoted ? '晋级' : '断板' }}</span></td>
              </tr>
            </tbody>
          </table>
        </div>
      </Panel>
    </div>

    <Panel title="指标说明书" sub="游资视角：每个指标怎么用">
      <div class="grid" style="grid-template-columns:repeat(auto-fill,minmax(330px,1fr));gap:10px">
        <div class="chip" style="padding:9px 11px" v-for="i in helps" :key="i.key">
          <b style="color:#e8eef7">{{ i.name }}</b>
          <div class="small muted" style="margin-top:4px;line-height:1.7;white-space:normal">{{ i.how }}</div>
        </div>
      </div>
    </Panel>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import Panel from '../components/Panel.vue'
import StatCard from '../components/StatCard.vue'
import EChart from '../components/EChart.vue'
import PctText from '../components/PctText.vue'
import { api } from '../api'
import { indicatorHelp, loadIndicators, store } from '../store'
import { pct as pctf, scoreColor, phaseColor } from '../format'

const s = ref({}); const hist = ref([]); const helps = ref([])
const m = computed(() => s.value.metrics || {})
const pp = computed(() => s.value.prev_premium_detail || {})
const fi = computed(() => s.value.factor_independence || {})
const bandDesc = computed(() => {
  const b = s.value.score_band || {}
  const head = (s.value.label || '') + ' · ' + ((s.value.phase || {}).phase || '')
  return b.lo === undefined || b.lo === null ? head : `${head}｜扰动区间 ${b.lo}–${b.hi}`
})
const premDesc = computed(() => {
  const d = pp.value || {}
  const st = (d.stats || {}).tradable || {}
  const ci = st.ci || {}
  const n = `样本 ${d.tradable_sample ?? 0}/${d.premium_sample ?? 0}`
  const mid = st.median === undefined || st.median === null ? '' : `｜中位 ${st.median}%`
  const iv = ci.lo === undefined || ci.lo === null ? '' : `｜95% [${ci.lo}, ${ci.hi}]`
  const nb = d.unbuyable_rate === undefined || d.unbuyable_rate === null ? '' : `｜买不到 ${d.unbuyable_rate}%`
  return n + mid + iv + nb
})
const premHelp = computed(() =>
  '评分口径：只统计今日开盘确实能买入的样本（剔除开盘即一字封死），从开盘价算到收盘价。' +
  '收盘涨跌幅口径含全天买不到的票，会高估赚钱效应，已降级为参考值：' +
  (pp.value.avg_premium ?? '—') + '%')
const pctv = v => (v === null || v === undefined ? '—' : Number(v).toFixed(2) + '%')
const h = n => indicatorHelp(n)
const phaseFg = computed(() => phaseColor((s.value.phase || {}).phase))

const histOpt = computed(() => {
  const rows = (s.value.score_history || []).concat(hist.value.filter(x => !(s.value.score_history || []).some(y => y.date === x.trade_date)).map(x => ({ date: x.trade_date, score: x.score, limit_up: x.limit_up, max_boards: x.max_boards })))
  const uniq = {}; rows.forEach(r => { if (r.date) uniq[r.date] = r })
  const arr = Object.values(uniq).sort((a, b) => a.date.localeCompare(b.date))
  return {
    grid: { left: 40, right: 42, top: 30, bottom: 30 },
    tooltip: { trigger: 'axis' },
    legend: { data: ['情绪分', '涨停家数', '最高板'], textStyle: { color: '#8d9bb1', fontSize: 10 }, top: 0, right: 8 },
    xAxis: { type: 'category', data: arr.map(r => r.date.slice(5)), axisLabel: { color: '#5f6d84', fontSize: 10 }, axisLine: { lineStyle: { color: '#232d40' } } },
    yAxis: [
      { type: 'value', max: 100, splitLine: { lineStyle: { color: '#1a2233' } }, axisLabel: { color: '#5f6d84' } },
      { type: 'value', splitLine: { show: false }, axisLabel: { color: '#5f6d84' } },
    ],
    series: [
      { name: '情绪分', type: 'line', smooth: true, data: arr.map(r => r.score), symbolSize: 5,
        lineStyle: { width: 2, color: '#ffb020' }, itemStyle: { color: '#ffb020' },
        areaStyle: { color: 'rgba(255,176,32,.12)' },
        markLine: { silent: true, symbol: 'none', label: { color: '#5f6d84', fontSize: 9 },
          data: [{ yAxis: 70, lineStyle: { color: '#ff7a45', type: 'dashed' } }, { yAxis: 40, lineStyle: { color: '#4c9aff', type: 'dashed' } }] } },
      { name: '涨停家数', type: 'bar', yAxisIndex: 1, data: arr.map(r => r.limit_up), barWidth: '40%', itemStyle: { color: 'rgba(255,77,79,.45)' } },
      { name: '最高板', type: 'line', yAxisIndex: 1, step: 'end', data: arr.map(r => r.max_boards), symbolSize: 4, lineStyle: { color: '#a97bff', width: 1.5 } },
    ],
  }
})

const compOpt = computed(() => {
  const cs = s.value.components || []
  return {
    grid: { left: 96, right: 40, top: 12, bottom: 22 },
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' }, formatter: p => { const c = cs[p[0].dataIndex]; return `${c.name}：${c.value}${c.unit || ''}<br/>得分 ${c.score} · 权重 ${(c.weight * 100).toFixed(0)}%<br/><span style="color:#8d9bb1">${c.tip}</span>` } },
    xAxis: { type: 'value', max: 100, splitLine: { lineStyle: { color: '#1a2233' } }, axisLabel: { color: '#5f6d84' } },
    yAxis: { type: 'category', data: cs.map(c => c.name).reverse(), axisLabel: { color: '#8d9bb1', fontSize: 11 }, axisLine: { lineStyle: { color: '#232d40' } } },
    series: [{ type: 'bar', data: cs.map(c => ({ value: c.score, itemStyle: { color: scoreColor(c.score), borderRadius: 3 } })).reverse(), barWidth: '55%',
      label: { show: true, position: 'right', color: '#8d9bb1', fontSize: 10, formatter: '{c}' } }],
  }
})

onMounted(async () => {
  await loadIndicators()
  helps.value = store.indicators?.sentiment || []
  const [a, b] = await Promise.allSettled([api.sentiment(), api.sentimentHistory(60)])
  if (a.status === 'fulfilled') s.value = a.value
  if (b.status === 'fulfilled') hist.value = b.value.items || []
})
</script>