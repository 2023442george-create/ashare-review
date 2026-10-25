<template>
  <div class="stack">
    <Panel :title="cur.desc || '游资选股器'" :sub="res.note">
      <template #extra>
        <span class="pill" v-for="s in strategies" :key="s.key" :class="{ active: strategy === s.key }"
              @click="switchTo(s.key)" :title="s.desc">{{ nameOf(s.key) }}</span>
      </template>
      <div class="small muted" style="margin-bottom:8px">
        共 {{ res.count || 0 }} 只。评分为规则引擎输出（封成比、市值、换手、封板时间、主线归属、席位质量等加权），仅供缩小观察范围，<b style="color:#ffb020">不构成买卖建议</b>。
      </div>
      <div class="scroll-y" style="max-height:600px">
        <table class="tbl">
          <thead><tr>
            <th class="num">评分</th><th>代码</th><th>名称</th><th class="num">现价</th><th class="num">涨幅</th>
            <th>连板</th><th>行业/主线</th><th class="num">封单</th><th class="num">封成比%</th>
            <th class="num">成交额</th><th class="num">流通市值</th><th class="num">换手%</th>
            <th>板型</th><th>首封</th><th>入选理由</th><th></th>
          </tr></thead>
          <tbody>
            <tr v-for="r in (res.items || [])" :key="r.code + (r.line || '')">
              <td class="num"><span class="tag" :class="r.score >= 90 ? 'red' : r.score >= 60 ? 'gold' : 'gray'">{{ r.score }}</span></td>
              <td class="mono dim">{{ r.code }}</td>
              <td><b>{{ r.name }}</b></td>
              <td class="num mono">{{ num(r.price) }}</td>
              <td class="num"><PctText :v="r.pct ?? r.today_pct" /></td>
              <td><span class="tag" v-if="r.boards" :class="r.boards >= 3 ? 'red' : r.boards === 2 ? 'gold' : 'gray'">{{ r.days_board || (r.boards + '板') }}</span>
                  <span class="dim" v-else>—</span></td>
              <td class="small">{{ r.line || r.industry || '—' }}</td>
              <td class="num mono">{{ r.fund_yi ? r.fund_yi + '亿' : '—' }}</td>
              <td class="num mono" :class="r.seal_ratio >= 30 ? 'up' : ''">{{ num(r.seal_ratio, 1) }}</td>
              <td class="num mono muted">{{ r.amount_yi ? r.amount_yi + '亿' : '—' }}</td>
              <td class="num mono muted">{{ r.float_mv_yi ? r.float_mv_yi + '亿' : '—' }}</td>
              <td class="num mono muted">{{ num(r.turnover, 1) }}</td>
              <td><span class="tag gray" v-if="r.board_type">{{ r.board_type }}</span><span v-else class="dim">—</span></td>
              <td class="mono small muted">{{ r.first_time || '—' }}</td>
              <td class="small" style="white-space:normal;max-width:340px;line-height:1.5">
                <span class="tag blue tiny" v-for="(w, i) in (r.why || []).slice(0, 4)" :key="i" style="margin-right:3px">{{ w }}</span>
              </td>
              <td><button class="btn" style="padding:2px 8px" @click="addWatch(r)">自选</button></td>
            </tr>
          </tbody>
        </table>
        <div v-if="!(res.items || []).length" class="empty">今日该策略无标的</div>
      </div>
    </Panel>

    <div class="grid" style="grid-template-columns:1fr 1fr">
      <Panel title="策略说明" sub="游资常用打法与数据对应关系">
        <div v-for="s in strategies" :key="s.key" class="small" style="padding:7px 0;border-bottom:1px dashed #232d40">
          <b :style="{ color: strategy === s.key ? '#ffb020' : '#e8eef7', cursor: 'pointer' }" @click="switchTo(s.key)">{{ nameOf(s.key) }}</b>
          <div class="dim" style="line-height:1.6;margin-top:2px">{{ s.desc }}</div>
        </div>
      </Panel>
      <Panel title="自选观察池" sub="加入后可在报告里跟踪">
        <div v-for="w in watch" :key="w.code" class="between small" style="padding:6px 0;border-bottom:1px dashed #232d40">
          <span><b>{{ w.name || w.code }}</b> <span class="dim mono">{{ w.code }}</span>
            <span class="tag gray tiny" v-if="w.tag">{{ w.tag }}</span></span>
          <span class="row">
            <PctText :v="w.pct" />
            <button class="btn" style="padding:1px 7px" @click="delWatch(w.code)">删除</button>
          </span>
        </div>
        <div v-if="!watch.length" class="empty">还没有自选，点击表格右侧「自选」加入</div>
      </Panel>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import Panel from '../components/Panel.vue'
import PctText from '../components/PctText.vue'
import { api } from '../api'
import { toast } from '../store'
import { num } from '../format'

const NAMES = { first_board: '首板优选', relay: '二板接力', rebound: '断板反包', game_money: '游资龙虎榜', main_line: '主线龙头', risk: '风险回避池' }
const strategy = ref('first_board')
const res = ref({}); const strategies = ref([]); const watch = ref([])
const cur = computed(() => strategies.value.find(s => s.key === strategy.value) || {})
const nameOf = k => NAMES[k] || k

async function switchTo(k) {
  strategy.value = k
  try { res.value = await api.screener(k) } catch (e) { res.value = {}; toast('筛选失败：' + e.message) }
}
async function addWatch(r) {
  try { await api.addWatch(r.code, r.name, nameOf(strategy.value)); toast(`已加入自选：${r.name}`); loadWatch() }
  catch (e) { toast('加入失败：' + e.message) }
}
async function delWatch(code) { try { await api.delWatch(code); loadWatch() } catch (e) {} }
async function loadWatch() { try { const r = await api.watchlist(); watch.value = r.items || [] } catch (e) { watch.value = [] } }

onMounted(async () => {
  try { const s = await api.strategies(); strategies.value = s.items || [] } catch (e) { strategies.value = Object.keys(NAMES).map(k => ({ key: k, desc: '' })) }
  await Promise.all([switchTo(strategy.value), loadWatch()])
})
</script>