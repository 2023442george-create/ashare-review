<template>
  <div class="stack">
    <Panel title="连板天梯" :sub="ladder.comment" :how="how('ladder')" :loading="!ladder.levels">
      <template #extra><span class="tag gold">最高 {{ ladder.max_boards || 0 }} 板</span>
        <span class="tag gray" v-if="(ladder.gaps || []).length">断层：{{ ladder.gaps.join(',') }} 板</span>
        <span class="tag green" v-else>梯队完整</span></template>
      <div class="ladder-row" v-for="lv in (ladder.levels || [])" :key="lv.boards">
        <div class="ladder-lv">{{ lv.boards }}板<span class="tiny dim"> ×{{ lv.count }}</span></div>
        <div class="ladder-stocks">
          <span class="chip" v-for="s in lv.stocks" :key="s.code" :title="`${s.industry}｜封单${money(s.fund)}｜封成比${s.seal_ratio}%｜${s.board_type}｜首封${s.first_time}`">
            {{ s.name }} <b class="tiny">{{ s.board_type }}</b>
          </span>
        </div>
      </div>
    </Panel>

    <Panel nopad tight>
      <template #extra></template>
      <div class="panel-hd">
        <h3>涨跌停明细
          <span class="sub">{{ kindName }} {{ filtered.length }} 只 · 数据日期 {{ data.date || '—' }}</span>
        </h3>
        <div class="row">
          <span class="pill" v-for="k in kinds" :key="k.k" :class="{ active: kind === k.k }" @click="switchKind(k.k)">{{ k.n }}（{{ counts[k.k] ?? '—' }}）</span>
          <select class="inp" v-model="fType">
            <option value="">全部板型</option>
            <option v-for="t in types" :key="t" :value="t">{{ t }}</option>
          </select>
          <label class="small muted row"><input type="checkbox" v-model="onlyLb" /> 只看连板</label>
          <input class="inp" style="width:110px" v-model="kw" placeholder="搜索名称/代码/行业" />
          <span class="src">{{ srcName }}</span>
        </div>
      </div>
      <div class="scroll-y" style="max-height:620px">
        <table class="tbl">
          <thead><tr>
            <th @click="sortBy('code')">代码</th><th @click="sortBy('name')">名称</th>
            <th class="num" @click="sortBy('pct')">涨幅%</th>
            <th class="num" @click="sortBy('boards')">连板</th>
            <th>板型 <span class="help" :title="h('board_type')">?</span></th>
            <th @click="sortBy('first_time')">首封 <span class="help" :title="h('first_time')">?</span></th><th @click="sortBy('last_time')">末封</th>
            <th class="num" @click="sortBy('fund')">封单额 <span class="help" :title="h('fund')">?</span></th>
            <th class="num" @click="sortBy('seal_ratio')">封成比% <span class="help" :title="h('seal_ratio')">?</span></th>
            <th class="num" @click="sortBy('fund_mv_ratio')">封单/流通% <span class="help" :title="h('fund_mv_ratio')">?</span></th>
            <th class="num" @click="sortBy('amount')">成交额</th>
            <th class="num" @click="sortBy('float_mv')">流通市值</th>
            <th class="num" @click="sortBy('turnover')">换手%</th>
            <th class="num" @click="sortBy('broken_times')">炸板</th>
            <th @click="sortBy('industry')">行业</th><th>统计 <span class="help" :title="h('days_board')">?</span></th>
          </tr></thead>
          <tbody>
            <tr v-for="r in filtered" :key="r.code">
              <td class="mono dim">{{ r.code }}</td>
              <td><b>{{ r.name }}</b></td>
              <td class="num"><PctText :v="r.pct" /></td>
              <td class="num"><span class="tag" :class="r.boards >= 3 ? 'red' : r.boards === 2 ? 'gold' : 'gray'">{{ r.boards }}板</span></td>
              <td><span class="tag" :class="typeClass(r.board_type)">{{ r.board_type }}</span></td>
              <td class="mono small">{{ r.first_time || '—' }}</td>
              <td class="mono small muted">{{ r.last_time || '—' }}</td>
              <td class="num mono">{{ money(r.fund) }}</td>
              <td class="num mono" :class="r.seal_ratio >= 30 ? 'up' : r.seal_ratio < 5 ? 'down' : ''">{{ num(r.seal_ratio, 1) }}</td>
              <td class="num mono muted">{{ num(r.fund_mv_ratio, 2) }}</td>
              <td class="num mono muted">{{ money(r.amount) }}</td>
              <td class="num mono muted">{{ money(r.float_mv, 1) }}</td>
              <td class="num mono muted">{{ num(r.turnover, 1) }}</td>
              <td class="num" :class="r.broken_times > 0 ? 'down' : 'dim'">{{ r.broken_times || 0 }}</td>
              <td class="small">{{ r.industry }}</td>
              <td class="small dim">{{ r.days_board }}</td>
            </tr>
          </tbody>
        </table>
        <div v-if="!filtered.length" class="empty">没有符合条件的记录</div>
      </div>
    </Panel>

    <div class="grid" style="grid-template-columns:1fr 1fr">
      <Panel title="板型分布" sub="一字/秒板说明一致性强，烂板/尾盘板说明分歧大">
        <EChart :option="typeOpt" :height="230" />
      </Panel>
      <Panel title="行业涨停分布" sub="哪个方向在批量涨停 = 主线所在">
        <EChart :option="indOpt" :height="230" />
      </Panel>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import Panel from '../components/Panel.vue'
import EChart from '../components/EChart.vue'
import PctText from '../components/PctText.vue'
import { api } from '../api'
import { indicatorHelp as h, indicatorHow as how, srcTag } from '../store'
import { money, num } from '../format'

const kinds = [{ k: 'zt', n: '涨停池' }, { k: 'zb', n: '炸板池' }, { k: 'dt', n: '跌停池' }]
const kind = ref('zt'); const counts = ref({})
const data = ref({}); const ladder = ref({})
const kw = ref(''); const onlyLb = ref(false); const fType = ref('')
const sortKey = ref('fund'); const sortAsc = ref(false)
const types = ['一字板', 'T字板', '秒板', '换手板', '烂板', '尾盘板']

const kindName = computed(() => (kinds.find(k => k.k === kind.value) || {}).n)
const srcName = computed(() => srcTag(data.value.meta))
const typeClass = t => ({ 一字板: 'red', 秒板: 'gold', T字板: 'gold', 换手板: 'blue', 烂板: 'green', 尾盘板: 'gray' }[t] || 'gray')

const filtered = computed(() => {
  let rows = (data.value.items || []).slice()
  if (kw.value) { const k = kw.value.toLowerCase(); rows = rows.filter(r => (r.name + r.code + (r.industry || '')).toLowerCase().includes(k)) }
  if (onlyLb.value) rows = rows.filter(r => (r.boards || 1) >= 2)
  if (fType.value) rows = rows.filter(r => r.board_type === fType.value)
  const key = sortKey.value
  rows.sort((a, b) => { const x = a[key], y = b[key]; const r = typeof x === 'number' ? x - (y || 0) : String(x || '').localeCompare(String(y || '')); return sortAsc.value ? r : -r })
  return rows
})
function sortBy(k) { if (sortKey.value === k) sortAsc.value = !sortAsc.value; else { sortKey.value = k; sortAsc.value = false } }

const typeOpt = computed(() => {
  const c = {}; (data.value.items || []).forEach(r => { c[r.board_type] = (c[r.board_type] || 0) + 1 })
  const keys = Object.keys(c)
  return {
    tooltip: { trigger: 'item' },
    legend: { bottom: 0, textStyle: { color: '#8d9bb1', fontSize: 10 } },
    series: [{ type: 'pie', radius: ['42%', '68%'], center: ['50%', '44%'],
      data: keys.map(k => ({ name: k, value: c[k] })),
      label: { color: '#8d9bb1', fontSize: 10, formatter: '{b}\n{c}' },
      itemStyle: { borderColor: '#131a28', borderWidth: 2 } }]
  }
})
const indOpt = computed(() => {
  const c = {}; (data.value.items || []).forEach(r => { const k = r.industry || '其他'; c[k] = (c[k] || 0) + 1 })
  const arr = Object.entries(c).sort((a, b) => b[1] - a[1]).slice(0, 14).reverse()
  return {
    grid: { left: 88, right: 30, top: 10, bottom: 20 },
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
    xAxis: { type: 'value', splitLine: { lineStyle: { color: '#1a2233' } }, axisLabel: { color: '#5f6d84' } },
    yAxis: { type: 'category', data: arr.map(x => x[0]), axisLabel: { color: '#8d9bb1', fontSize: 11 }, axisLine: { lineStyle: { color: '#232d40' } } },
    series: [{ type: 'bar', data: arr.map(x => x[1]), barWidth: '60%', itemStyle: { color: '#ff6b6b', borderRadius: 3 },
      label: { show: true, position: 'right', color: '#8d9bb1', fontSize: 10 } }]
  }
})

async function switchKind(k) { kind.value = k; await loadPool() }
async function loadPool() {
  try { data.value = await api.limitPool(kind.value) } catch (e) { data.value = {} }
}
async function loadCounts() {
  const rs = await Promise.allSettled(kinds.map(k => api.limitPool(k.k)))
  rs.forEach((r, i) => { if (r.status === 'fulfilled') counts.value[kinds[i].k] = (r.value.items || []).length })
}
onMounted(async () => { await Promise.all([loadPool(), (async () => { try { ladder.value = await api.ladder() } catch (e) {} })(), loadCounts()]) })
</script>