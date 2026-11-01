<template>
  <div class="stack">
    <Panel title="外围综合信号" :sub="`信号分 ${sig.score ?? 0}（正=偏多，负=偏空）`">
      <template #extra>
        <span class="tag" :class="sig.score >= 2 ? 'red' : sig.score <= -2 ? 'green' : 'gray'" style="font-size:12px;padding:3px 10px">
          {{ sig.overall || '—' }}
        </span>
      </template>
      <div class="small muted" style="margin-bottom:8px">{{ sig.tip }}</div>
      <div class="grid" style="grid-template-columns:repeat(auto-fit,minmax(340px,1fr));gap:8px">
        <div v-for="(s, i) in (sig.signals || [])" :key="i" class="chip" style="padding:8px 10px;white-space:normal">
          <span class="tag" :class="s.level === '利好' ? 'red' : s.level === '利空' ? 'green' : 'gray'">{{ s.level }}</span>
          {{ s.text }}
        </div>
      </div>
    </Panel>

    <div v-for="g in (data.groups || [])" :key="g.name">
      <Panel :title="g.name" :sub="groupSub(g.name)">
        <div class="grid" style="grid-template-columns:repeat(auto-fill,minmax(215px,1fr));gap:10px">
          <div class="stat" v-for="it in g.items" :key="it.key" :class="{ hl: it.key === 'A50' || it.key === 'SOX' || it.key === 'HXC' }">
            <div class="k">
              {{ it.name }}
              <span class="help" v-if="it.role" :title="it.role">?</span>
              <span class="tag gold tiny" v-if="it.stale" :title="`行情时间 ${it.time}，不参与信号`">数据偏旧</span>
            </div>
            <div class="between" style="margin-top:4px">
              <span class="v mono" :class="cls(it.pct)" style="font-size:18px">{{ num(it.price, it.price > 1000 ? 2 : 4) }}</span>
              <span class="mono" :class="cls(it.pct)" style="font-size:13px">{{ pctf(it.pct) }}</span>
            </div>
            <div class="d tiny">
              <span class="src">{{ it.source }}</span>
              <span v-if="it.high"> 高 {{ num(it.high, 2) }} / 低 {{ num(it.low, 2) }}</span>
            </div>
            <div class="d tiny dim" style="line-height:1.5;margin-top:4px;white-space:normal">{{ it.role }}</div>
          </div>
        </div>
      </Panel>
    </div>

    <div class="grid" style="grid-template-columns:1fr 1fr">
      <Panel title="游资看外围的顺序" sub="9:00 前必看">
        <ol class="small" style="line-height:2;padding-left:18px;color:#c8d3e2">
          <li><b style="color:#ffb020">A50期货</b>（富时中国A50）：A股开盘前唯一实时先行指标，决定竞价策略</li>
          <li><b style="color:#ffb020">纳斯达克金龙</b>：中概隔夜表现，与A股/港股情绪同步性最高</li>
          <li><b style="color:#ffb020">费城半导体</b>：直接决定A股芯片、存储、设备板块的开盘溢价</li>
          <li><b>纳指 / 标普</b>：全球科技与风险偏好，影响AI、算力主线</li>
          <li><b>恒生科技</b>：日内与A股TMT联动，港股弱则A股难独立走强</li>
          <li><b>日经 / 韩股</b>：亚太风险偏好，韩股与存储链高度相关</li>
          <li><b>离岸人民币 / 美元指数</b>：贬值加速时警惕权重护盘失败、题材杀跌</li>
          <li><b>VIX / 美债10Y</b>：全球估值分母，快速上行压制高估值成长</li>
          <li><b>原油 / 黄金</b>：通胀与避险，影响周期与贵金属板块</li>
        </ol>
      </Panel>
      <Panel title="跨市场传导速查" sub="经验规则">
        <table class="tbl">
          <thead><tr><th>外围变化</th><th>A股对应板块</th><th>方向</th></tr></thead>
          <tbody>
            <tr v-for="r in map" :key="r[0]">
              <td class="small">{{ r[0] }}</td><td class="small">{{ r[1] }}</td>
              <td><span class="tag" :class="r[2] === '利好' ? 'red' : r[2] === '利空' ? 'green' : 'gray'">{{ r[2] }}</span></td>
            </tr>
          </tbody>
        </table>
      </Panel>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import Panel from '../components/Panel.vue'
import { api } from '../api'
import { cls, num, pct as pctf } from '../format'

const data = ref({}); const sig = computed(() => data.value.signal || {})
const map = [
  ['费城半导体 +2%以上', '半导体/存储/设备/PCB', '利好'],
  ['纳指大涨、AI龙头新高', '算力/光模块/液冷/AI应用', '利好'],
  ['中概金龙 +2%', '港股互联网映射、A股消费/中特估', '利好'],
  ['A50期货高开 >0.5%', '权重蓝筹、券商', '利好'],
  ['日经/韩股大跌 >2%', '亚太科技链、出口链', '利空'],
  ['离岸人民币快速贬值', '航空/造纸(外币负债)、外资重仓白马', '利空'],
  ['美元指数走强', '有色/黄金/成长股', '利空'],
  ['原油大涨 >3%', '石油石化/油运/煤炭', '利好'],
  ['原油大涨 >3%', '航空/化工下游/物流', '利空'],
  ['黄金大涨', '贵金属/黄金股', '利好'],
  ['VIX > 25', '全市场（降仓）', '利空'],
  ['美债10Y快速上行', '创业板/科创/高估值成长', '利空'],
  ['恒生科技大涨', 'A股TMT、AI应用、传媒', '利好'],
]
function groupSub(n) {
  return { 美股: '隔夜收盘，影响今日开盘情绪', 中概: 'A股/港股情绪的先行指标', 亚太: '今日盘中同步',
    港股: '与A股同步交易', 汇率商品: '通胀、避险与外资流向', 期货: '★开盘前必看', 利率: '全球估值分母' }[n] || ''
}
onMounted(async () => { try { data.value = await api.global() } catch (e) { data.value = {} } })
</script>