<template>
  <div class="stack">
    <div class="grid" style="grid-template-columns:repeat(4,1fr)">
      <StatCard label="上榜个股" :value="data.count ?? 0" :desc="`数据日期 ${data.date || '—'}`" />
      <StatCard label="知名资金净买入 TOP" :value="top1 ? top1.name : '—'" color="#ffb020"
                :desc="top1 ? `${top1.game_tag} · 净买 ${top1.known_net_yi}亿` : ''" />
      <StatCard label="机构专用净买入" :value="(data.inst_net_yi ?? '—') + ' 亿'" :sign="true"
                desc="机构专用席位合计净额" :help="h('inst_net')" />
      <StatCard label="股通席位净买入" :value="(data.north_net_yi ?? '—') + ' 亿'" :sign="true"
                desc="仅上榜个股，不等同全市场北向" :help="h('north_net')" />
    </div>

    <div class="grid" style="grid-template-columns:1.6fr 1fr">
      <Panel nopad tight>
        <div class="panel-hd">
          <h3>龙虎榜明细<span class="sub">按龙虎榜净买入排序</span></h3>
          <div class="row">
            <input class="inp" v-model="date" type="date" @change="load" />
            <label class="small muted row"><input type="checkbox" v-model="onlyKnown" /> 只看知名资金</label>
            <span class="src">{{ srcName }}</span>
          </div>
        </div>
        <div class="scroll-y" style="max-height:600px">
          <table class="tbl">
            <thead><tr><th>代码</th><th>名称</th><th class="num">收盘</th><th class="num">涨幅</th>
              <th class="num">成交额</th><th class="num">买入</th><th class="num">卖出</th>
              <th class="num">净额 <span class="help" :title="h('lhb_net')">?</span></th>
              <th>资金属性</th><th>上榜原因</th></tr></thead>
            <tbody>
              <template v-for="r in filtered" :key="r.code + r.reason">
                <tr @click="toggle(r.code)" style="cursor:pointer">
                  <td class="mono dim">{{ r.code }}</td><td><b>{{ r.name }}</b>
                    <span class="tiny" :class="expanded === r.code ? 'up' : 'dim'">{{ expanded === r.code ? '▲' : '▼' }}</span></td>
                  <td class="num mono">{{ num(r.close) }}</td>
                  <td class="num"><PctText :v="r.pct" /></td>
                  <td class="num mono muted">{{ num(r.amount_yi, 2) }}亿</td>
                  <td class="num mono up">{{ num(r.buy_yi, 2) }}亿</td>
                  <td class="num mono down">{{ num(r.sell_yi, 2) }}亿</td>
                  <td class="num mono bold" :class="cls(r.net)">{{ signed(r.net_yi, 2) }}亿</td>
                  <td><span class="tag" :class="tagClass(r.game_tag)">{{ r.game_tag || '—' }}</span></td>
                  <td class="small dim" style="max-width:230px;overflow:hidden;text-overflow:ellipsis">{{ r.reason }}</td>
                </tr>
                <tr v-if="expanded === r.code">
                  <td colspan="10" style="background:#0f1420;padding:10px 14px">
                    <div class="small muted" style="margin-bottom:6px">买卖席位（点击行收起）· 次日涨幅 {{ r.d1_pct ?? '—' }}%</div>
                    <table class="tbl">
                      <thead><tr><th>营业部</th><th>识别</th><th class="num">买入</th><th class="num">卖出</th><th class="num">净额</th>
                        <th class="num">3日胜率% <span class="help" :title="h('win_3day')">?</span></th><th class="num">3日上榜次数</th><th>操作风格 / 次日提示</th></tr></thead>
                      <tbody>
                        <tr v-for="(s, i) in (r.seats || []).slice(0, 10)" :key="i">
                          <td style="max-width:250px;overflow:hidden;text-overflow:ellipsis" :title="s.dept">{{ s.dept }}</td>
                          <td><span class="tag" :class="tagClass(s.tag)" v-if="s.tag || s.seat">{{ s.seat || s.tag }}</span>
                              <span class="dim tiny" v-else>普通席位</span></td>
                          <td class="num mono up">{{ s.buy ? money(s.buy) : '—' }}</td>
                          <td class="num mono down">{{ s.sell ? money(s.sell) : '—' }}</td>
                          <td class="num mono bold" :class="cls(s.net)">{{ money(s.net) }}</td>
                          <td class="num mono muted">{{ num(s.win_3day, 1) }}</td>
                          <td class="num mono muted">{{ s.times_3day }}</td>
                          <td class="small dim" style="max-width:330px;white-space:normal;line-height:1.5">
                            {{ s.style }}<br v-if="s.next_hint" /><span style="color:#ffb020">{{ s.next_hint }}</span></td>
                        </tr>
                      </tbody>
                    </table>
                  </td>
                </tr>
              </template>
            </tbody>
          </table>
          <div v-if="!filtered.length" class="empty">当日无龙虎榜数据（交易所一般 17:00-19:00 公布）</div>
        </div>
      </Panel>

      <div class="stack">
        <Panel title="活跃营业部排行" sub="净买入最多 8 家 / 净卖出最多 8 家">
          <div v-for="s in seatRows" :key="s.dept" class="between small"
               style="padding:6px 0;border-bottom:1px dashed #232d40">
            <span style="max-width:210px;overflow:hidden;text-overflow:ellipsis" :title="s.dept">
              {{ s.seat || s.dept }}
              <span class="tag gray tiny" v-if="s.tag">{{ s.tag }}</span>
            </span>
            <span class="nowrap"><span class="dim tiny">{{ s.times }}次</span>
              <b class="mono" :class="cls(s.net_yi)" style="margin-left:6px">{{ signed(s.net_yi, 2) }}亿</b></span>
          </div>
        </Panel>
        <Panel title="游资席位图鉴" sub="民间公开归纳，仅作参考">
          <div class="small" style="line-height:1.9;max-height:330px;overflow-y:auto">
            <div v-for="s in seatDoc" :key="s.name" style="border-bottom:1px dashed #232d40;padding:5px 0">
              <b style="color:#ffb020">{{ s.name }}</b> <span class="tag" :class="tagClass(s.tag)">{{ s.tag }}</span>
              <div class="dim" style="font-size:11px;line-height:1.6">{{ s.style }}</div>
              <div style="font-size:11px;color:#8d9bb1">{{ s.next }}</div>
            </div>
          </div>
        </Panel>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import Panel from '../components/Panel.vue'
import StatCard from '../components/StatCard.vue'
import PctText from '../components/PctText.vue'
import { api } from '../api'
import { indicatorHelp as h, srcTag } from '../store'
import { cls, money, num, signed } from '../format'

const data = ref({}); const date = ref(''); const onlyKnown = ref(false); const expanded = ref('')
const srcName = computed(() => srcTag(data.value.meta))
const filtered = computed(() => {
  let rows = data.value.items || []
  if (onlyKnown.value) rows = rows.filter(r => (r.known_net_yi || 0) !== 0 && r.game_tag)
  return rows
})
const top1 = computed(() => (data.value.items || []).slice().sort((a, b) => (b.known_net_yi || 0) - (a.known_net_yi || 0))[0])
const seatRows = computed(() => {
  const r = data.value.seat_rank || []
  return r.length <= 16 ? r : [...r.slice(0, 8), ...r.slice(-8)]
})
function toggle(c) { expanded.value = expanded.value === c ? '' : c }
function tagClass(t) {
  if (!t) return 'gray'
  if (t.includes('顶级')) return 'red'
  if (t.includes('一线')) return 'gold'
  if (t.includes('机构')) return 'blue'
  if (t.includes('散户')) return 'green'
  if (t.includes('外资')) return 'purple'
  if (t.includes('量化')) return 'gray'
  return 'gray'
}
const seatDoc = [
  { name: '华鑫上海分公司', tag: '顶级游资', style: '赵老哥系常用席位，偏好主线龙头、连板接力，手法凶悍', next: '跟风资金多，次日高开概率大但易冲高回落' },
  { name: '上海江苏路（章盟主）', tag: '顶级游资', style: '章建平常用，资金量极大，偏好大市值主线与波段', next: '大资金进场通常代表主线级别行情' },
  { name: '溧阳路（孙哥）', tag: '顶级游资', style: '偏好中大盘趋势票与主线龙头，持仓周期偏长', next: '有中线资金属性，次日承接较好' },
  { name: '佛山无影脚', tag: '一线游资', style: '光大佛山绿景路，打板著称，专攻首板与二板', next: '隔日超短资金会抢跑，兑现快' },
  { name: '荣超商务中心', tag: '一线游资', style: '深圳系资金，题材首板/二板通吃', next: '隔日溢价中等' },
  { name: '银河绍兴', tag: '一线游资', style: '浙江资金，偏好小市值题材连板', next: '波动大，注意次日分歧' },
  { name: '东明路（小鳄鱼）', tag: '一线游资', style: '偏好情绪龙头，敢于高位接力', next: '龙头一致性强时溢价高' },
  { name: '拉萨天团', tag: '散户大本营', style: '东财拉萨系列营业部，散户追涨集中营', next: '★大额买入常是情绪末端信号，警惕接盘' },
  { name: '机构专用', tag: '机构', style: '公募/私募/保险等机构资金', next: '机构净买入的题材持续性通常好于纯游资票' },
  { name: '券商总部席位', tag: '量化通道', style: '多为量化/程序化交易通道单', next: '方向意义弱，需结合其他席位判断' },
]
async function load() {
  try { data.value = await api.lhb(date.value) } catch (e) { data.value = {} }
}
onMounted(load)
</script>