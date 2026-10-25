<template>
  <div class="stack">
    <Panel :title="`次日竞价确认 · ${res.strategy_name || ''}`"
           :sub="`候选日 ${res.candidate_date || '—'} · ${(res.session || {}).label || ''} · 取价 ${res.as_of || '—'}`">
      <template #extra>
        <span class="pill" v-for="s in SUPPORTED" :key="s" :class="{ active: strategy === s }"
              @click="switchTo(s)">{{ NAMES[s] }}</span>
        <button class="btn" @click="load(true)" :disabled="busy">
          <span v-if="busy" class="spin"></span> 重新取价
        </button>
      </template>

      <div class="small" style="line-height:1.7;margin-bottom:10px">
        收盘选出来的票不等于明天买得到。这一页只做一件事：在 09:15–09:25 用
        <b>当时已经可见的数据</b>（竞价匹配价、竞价成交额）确认或否决昨天的计划，
        不读取盘中与收盘结果。<span class="tag gold">阈值是纪律线，不是收益承诺</span>
      </div>

      <div v-for="(w, i) in ((res.summary || {}).warnings || [])" :key="i" class="err"
           style="margin-bottom:6px">{{ w }}</div>

      <div class="grid" style="grid-template-columns:repeat(4,1fr);margin-bottom:12px">
        <StatCard label="候选数" :value="(res.summary || {}).total ?? '—'" />
        <StatCard label="竞价确认" :value="(res.summary || {}).confirm ?? '—'" color="#ff6b6b"
                  desc="高开在剧本内且量能达标" />
        <StatCard label="待观察" :value="(res.summary || {}).weak ?? '—'" color="#ffb020"
                  desc="价格可接受但量能或方向未确认" />
        <StatCard label="放弃/买不到" :value="(res.summary || {}).avoid ?? '—'" color="#8d9bb1"
                  desc="过度高开、低开证伪或涨停排队" />
      </div>

      <div class="scroll-y" style="max-height:560px">
        <table class="tbl">
          <thead><tr>
            <th>结论</th><th class="num">评分</th><th>代码</th><th>名称</th><th>连板</th>
            <th>行业</th><th class="num">昨收</th><th class="num">竞价价</th><th class="num">高开%</th>
            <th class="num">竞价额</th><th class="num">量能比%</th><th>执行动作</th>
          </tr></thead>
          <tbody>
            <tr v-for="r in (res.items || [])" :key="r.code">
              <td><span class="tag" :class="levelTag(r.level)">{{ r.verdict }}</span></td>
              <td class="num mono">{{ r.score }}</td>
              <td class="mono dim">{{ r.code }}</td>
              <td><b>{{ r.name }}</b></td>
              <td><span class="tag gray" v-if="r.days_board">{{ r.days_board }}</span><span v-else class="dim">—</span></td>
              <td class="small muted">{{ r.industry || '—' }}</td>
              <td class="num mono muted">{{ num(r.prev_close) }}</td>
              <td class="num mono">{{ num(r.price) }}</td>
              <td class="num"><PctText :v="r.gap" /></td>
              <td class="num mono muted">{{ r.auction_amount_yi ? r.auction_amount_yi + '亿' : '—' }}</td>
              <td class="num mono" :class="ratioCls(r)">{{ num(r.auction_amount_ratio, 2) }}</td>
              <td class="small" style="white-space:normal;max-width:380px;line-height:1.5">{{ r.action }}</td>
            </tr>
          </tbody>
        </table>
        <div v-if="!(res.items || []).length" class="empty">暂无候选（目标交易日没有可用涨停池或选股结果）</div>
      </div>
    </Panel>

    <div class="grid" style="grid-template-columns:1fr 1fr">
      <Panel title="判定口径" sub="每个阈值的含义">
        <div class="kv">
          <template v-for="(v, k) in (res.method || {})" :key="k">
            <span class="kk">{{ METHOD_CN[k] || k }}</span><span class="small">{{ v }}</span>
          </template>
        </div>
      </Panel>
      <Panel title="上一份复盘的环境" sub="竞价只确认执行，不负责选股">
        <div class="kv">
          <span class="kk">情绪分</span><span class="mono">{{ (res.context || {}).sentiment_score ?? '—' }}</span>
          <span class="kk">情绪阶段</span><span>{{ (res.context || {}).phase || '—' }}</span>
          <span class="kk">快照数据质量</span><span>{{ (res.context || {}).snapshot_quality || '—' }}</span>
          <span class="kk">说明</span><span class="small muted">{{ (res.context || {}).note }}</span>
        </div>
      </Panel>
    </div>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import Panel from '../components/Panel.vue'
import StatCard from '../components/StatCard.vue'
import PctText from '../components/PctText.vue'
import { api } from '../api'
import { toast } from '../store'
import { num } from '../format'

const SUPPORTED = ['first_board', 'relay', 'main_line', 'game_money']
const NAMES = { first_board: '首板优选', relay: '二板接力', main_line: '主线龙头', game_money: '龙虎榜游资票' }
const METHOD_CN = { window: '时间窗', gap: '高开幅度', amount_ratio: '量能比', discipline: '纪律' }

const strategy = ref('first_board')
const res = ref({})
const busy = ref(false)

const levelTag = l => ({ pass: 'red', weak: 'gold', avoid: 'gray', unbuyable: 'purple', no_data: 'gray', wait: 'blue' }[l] || 'gray')
const ratioCls = r => (r.auction_amount_ratio === null || r.auction_amount_ratio === undefined ? '' : (r.level === 'weak' ? 'down' : 'up'))

async function load(force = false) {
  busy.value = true
  try { res.value = await api.auction(strategy.value, force) }
  catch (e) { res.value = {}; toast('竞价确认失败：' + e.message) }
  finally { busy.value = false }
}
function switchTo(s) { strategy.value = s; load() }
onMounted(() => load())
</script>
