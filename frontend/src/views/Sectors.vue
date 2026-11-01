<template>
  <div class="stack">
    <Panel title="主线判定" sub="涨停家数 × 连板高度 × 板块涨幅 × 主力净流入 四维交叉验证" :how="how('mainline')">
      <div v-if="(ml.warnings || []).length" class="small"
           style="margin-bottom:10px;padding:8px 10px;border-radius:6px;background:#2a2113;border:1px solid #5c4617;color:#ffcf70">
        ⚠ {{ (ml.warnings || []).join('；') }}
      </div>
      <div class="grid" style="grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:10px">
        <div class="stat" v-for="(l, i) in (ml.main_lines || []).slice(0, 6)" :key="l.name" :class="{ hl: i < 2 }">
          <div class="between">
            <b style="font-size:14px">{{ i + 1 }}. {{ l.name }}</b>
            <span style="display:flex;gap:6px;align-items:center">
              <span class="tag" :style="l.confirmed ? 'background:#14261f;color:#63d6a3;border:1px solid #24533f' : 'background:#2a2113;color:#ffcf70;border:1px solid #5c4617'">
                {{ l.confirmed ? '四维确认' : '待确认' }}
              </span>
              <span class="tag gold">主线分 {{ l.score }}</span>
            </span>
          </div>
          <div class="row-wrap small" style="margin-top:7px">
            <span class="tag red">涨停 {{ l.zt_count }} 家</span>
            <span class="tag gold">最高 {{ l.max_boards }} 板</span>
            <span :class="cls(l.pct)">{{ l.pct == null ? '涨幅缺失' : signed(l.pct) + '%' }}</span>
            <span :class="cls(l.main_flow_yi)">{{ l.main_flow_yi == null ? '资金缺失' : '主力 ' + signed(l.main_flow_yi, 1) + '亿' }}</span>
          </div>
          <div v-if="(l.members || []).length > 1" class="tiny dim" style="margin-top:4px">
            归并自：{{ (l.members || []).join(' / ') }}
          </div>
          <div v-if="!l.confirmed && (l.confirm_gaps || []).length" class="small"
               style="margin-top:5px;color:#ffcf70">缺口：{{ (l.confirm_gaps || []).join('、') }}</div>
          <div class="small dim" style="margin-top:6px;line-height:1.6">{{ l.reason }}</div>
          <div class="row-wrap small" style="margin-top:6px">
            <span class="chip" v-for="s in seatOf(l.name)" :key="s.code">
              <i v-if="s.seat_label" class="tiny" style="font-style:normal;opacity:.75">{{ s.seat_label }}</i>
              {{ s.name }}<b>{{ s.boards }}板</b>
            </span>
          </div>
        </div>
      </div>
      <div v-if="!(ml.main_lines || []).length" class="empty">今日无明显主线（涨停分散），建议降低预期</div>
    </Panel>

    <div class="grid" style="grid-template-columns:1.5fr 1fr">
      <Panel nopad tight>
        <div class="panel-hd">
          <h3>板块榜单<span class="sub">共 {{ rows.length }} 个 · 口径：{{ (ml.board_taxonomy || []).join(' / ') || '未知' }}</span></h3>
          <div class="row">
            <span class="pill" :class="{ active: kind === 'industry' }" @click="switchKind('industry')">行业</span>
            <span class="pill" :class="{ active: kind === 'concept' }" @click="switchKind('concept')">概念</span>
            <span class="pill" :class="{ active: sort === 'pct' }" @click="switchSort('pct')">按涨幅</span>
            <span class="pill" :class="{ active: sort === 'flow' }" @click="switchSort('flow')">按主力净流入</span>
            <input class="inp" style="width:100px" v-model="kw" placeholder="搜索板块" />
          </div>
        </div>
        <div v-if="fh.counts_unavailable" class="small" style="margin:0 12px 8px;padding:7px 10px;border-radius:6px;
                    line-height:1.7;background:#2a2113;border:1px solid #5c4617">
          <b style="color:#ffcf70">涨/跌家数本次未取到</b>
          <span class="muted"> · 数据源 {{ meta.source || '—' }}</span>
          <div class="muted">{{ fh.note }}</div>
          <button class="btn" style="margin-top:6px;padding:2px 8px" @click="runProbe" :disabled="probing">
            <span v-if="probing" class="spin"></span> 探测字段
          </button>
          <div v-if="probe" class="mono tiny" style="margin-top:6px;line-height:1.6">
            <div v-for="h in (probe.hosts || [])" :key="h.host">
              {{ h.host }} · 可达 {{ h.reachable ? '是' : '否' }} · {{ h.rows }} 行 ·
              缺字段 {{ (h.missing_requested || []).join(',') || '无' }}
            </div>
            <div class="muted" style="white-space:normal">{{ probe.how_to_read }}</div>
          </div>
        </div>
        <div class="scroll-y" style="max-height:560px">
          <table class="tbl">
            <thead><tr><th>#</th><th>板块</th><th class="num">涨跌幅</th>
              <th class="num">5日/20日 <span class="help" :title="h('pct_nd')">?</span></th>
              <th class="num">主力净流入 <span class="help" :title="h('main_flow')">?</span></th>
              <th class="num">净占比% <span class="help" :title="h('main_flow_ratio')">?</span></th><th class="num">涨/跌家数</th><th>领涨股</th><th class="num">换手%</th></tr></thead>
            <tbody>
              <tr v-for="(r, i) in filtered" :key="r.code">
                <td class="dim">{{ i + 1 }}</td>
                <td><b>{{ r.name }}</b> <span class="dim tiny">{{ r.code }}</span></td>
                <td class="num"><PctText :v="r.pct" /></td>
                <td class="num small"><PctText :v="r.pct_5d" /> / <PctText :v="r.pct_20d" /></td>
                <td class="num mono" :class="cls(r.main_flow)">{{ signed(r.main_flow_yi, 2) }}亿</td>
                <td class="num mono muted">{{ num(r.main_flow_ratio, 2) }}</td>
                <td class="num small">
                  <template v-if="r.up_count === null || r.up_count === undefined"><span class="dim">—</span></template>
                  <template v-else><span class="up">{{ r.up_count }}</span>/<span class="down">{{ r.down_count ?? '—' }}</span></template>
                </td>
                <td class="small">{{ r.lead_stock || '—' }} <PctText :v="r.lead_pct" class="small" /></td>
                <td class="num mono muted">{{ num(r.turnover, 2) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </Panel>

      <div class="stack">
        <Panel title="板块涨幅 TOP10" sub="红=资金流入，绿=资金流出">
          <EChart :option="flowOpt" :height="250" />
        </Panel>
        <Panel title="资金流出 TOP8" sub="资金撤离方向，规避">
          <div v-for="r in (ml.flow_out_top || []).slice(0, 8)" :key="r.code" class="between small" style="padding:5px 0;border-bottom:1px dashed #232d40">
            <span>{{ r.name }}</span>
            <span><PctText :v="r.pct" /> <span class="down mono">{{ signed(r.main_flow_yi, 1) }}亿</span></span>
          </div>
        </Panel>
      </div>
    </div>

    <Panel title="个股主力资金净流入榜" sub="主力资金是按大单估算的，不是真实账户数据（前50）" nopad tight>
      <template #extra><span class="src">{{ srcName2 }}</span></template>
      <div class="scroll-y" style="max-height:420px">
        <table class="tbl">
          <thead><tr><th>代码</th><th>名称</th><th class="num">现价</th><th class="num">涨幅</th>
            <th class="num">主力净流入</th><th class="num">净占比%</th><th class="num">超大单</th><th class="num">大单</th>
            <th class="num">换手%</th><th class="num">总市值(亿)</th></tr></thead>
          <tbody>
            <tr v-for="r in flow" :key="r.code">
              <td class="mono dim">{{ r.code }}</td><td><b>{{ r.name }}</b></td>
              <td class="num mono">{{ num(r.price) }}</td>
              <td class="num"><PctText :v="r.pct" /></td>
              <td class="num mono" :class="cls(r.main_flow)">{{ signed(r.main_flow_yi, 2) }}亿</td>
              <td class="num mono" :class="cls(r.main_flow_ratio)">{{ num(r.main_flow_ratio, 1) }}</td>
              <td class="num mono muted">{{ signed(r.super_flow_yi, 2) }}</td>
              <td class="num mono muted">{{ signed(r.big_flow_yi, 2) }}</td>
              <td class="num mono muted">{{ num(r.turnover, 1) }}</td>
              <td class="num mono muted">{{ num(r.total_mv_yi, 0) }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </Panel>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import Panel from '../components/Panel.vue'
import EChart from '../components/EChart.vue'
import PctText from '../components/PctText.vue'
import { api } from '../api'
import { indicatorHelp as h, indicatorHow as how, srcTag } from '../store'
import { cls, num, signed } from '../format'

const ml = ref({}); const rows = ref([]); const flow = ref([])
const kind = ref('industry'); const sort = ref('pct'); const kw = ref('')
const bd = ref({}); const fd = ref({})
const probe = ref(null); const probing = ref(false)
const srcName2 = computed(() => srcTag(fd.value.meta))
// field_health 区分"这一列上游没给"和"这一列真的是 0"
const fh = computed(() => bd.value.field_health || {})
const meta = computed(() => bd.value.meta || {})

const filtered = computed(() => {
  let r = rows.value.slice()
  if (kw.value) r = r.filter(x => (x.name || '').includes(kw.value))
  return r
})

const flowOpt = computed(() => {
  const top = (ml.value.hot_concepts || []).slice(0, 10).reverse()
  return {
    grid: { left: 96, right: 46, top: 10, bottom: 20 },
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
    xAxis: { type: 'value', splitLine: { lineStyle: { color: '#1a2233' } }, axisLabel: { color: '#5f6d84' } },
    yAxis: { type: 'category', data: top.map(x => x.name), axisLabel: { color: '#8d9bb1', fontSize: 10 }, axisLine: { lineStyle: { color: '#232d40' } } },
    series: [{ type: 'bar', barWidth: '58%',
      data: top.map(x => ({ value: x.pct, itemStyle: { color: (x.main_flow_yi || 0) >= 0 ? '#ff6b6b' : '#00b578', borderRadius: 3 } })),
      label: { show: true, position: 'right', color: '#8d9bb1', fontSize: 10, formatter: p => p.value + '%' } }]
  }
})

// 板块内身位：龙一/龙二/跟风由后端按 连板高度→封单额→首封时间 排好，前端只展示；
// 缺失时退回原始成分股列表。
function seatOf(name) {
  const p = (ml.value.positions || {})[name]
  if (p && p.length) return p.slice(0, 6)
  const l = (ml.value.main_lines || []).find(x => x.name === name)
  return (l && l.stocks ? l.stocks : []).slice(0, 6)
}

async function switchKind(k) { kind.value = k; await loadBoards() }
async function switchSort(s) { sort.value = s; await loadBoards() }
async function loadBoards() {
  try { bd.value = await api.sectors(kind.value, sort.value, 60); rows.value = bd.value.items || [] }
  catch (e) { bd.value = {}; rows.value = [] }
  probe.value = null
}
async function runProbe() {
  probing.value = true
  try { probe.value = await api.sectorProbe(kind.value) }
  catch (e) { probe.value = { hosts: [], how_to_read: '探测失败：' + e.message } }
  finally { probing.value = false }
}
onMounted(async () => {
  const [a, b] = await Promise.allSettled([api.mainline(), api.stockflow(50)])
  if (a.status === 'fulfilled') ml.value = a.value
  if (b.status === 'fulfilled') { fd.value = b.value; flow.value = b.value.items || [] }
  await loadBoards()
})
</script>