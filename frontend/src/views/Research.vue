<template>
  <div class="stack">
    <!-- 1. 研究状态：由账本算出来，不是写死的字段 -->
    <Panel title="研究状态" :sub="`方法版本 ${st.methodology_version || '—'} · 参数指纹 ${st.param_digest || '—'}`">
      <template #extra>
        <button class="btn" @click="doFreeze" :disabled="busy">冻结今日信号</button>
        <button class="btn" @click="doSettle" :disabled="busy">结算前瞻结果</button>
        <button class="btn" @click="loadAll" :disabled="busy"><span v-if="busy" class="spin"></span> 刷新</button>
      </template>

      <div class="grid" style="grid-template-columns:repeat(5,1fr);margin-bottom:12px">
        <StatCard label="已冻结交易日" :value="st.frozen_days ?? '—'" desc="收盘后记下候选的天数" />
        <StatCard label="已结算交易日" :value="st.settled_days ?? '—'" desc="已回填前瞻结果的天数" />
        <StatCard label="来回成本假设" :value="(st.cost_pct ?? '—') + '%'" desc="佣金+过户费+印花税+滑点" />
        <StatCard label="收益基准" :value="st.benchmark || '—'" desc="题材/小盘 beta 对标" />
        <StatCard label="验证状态" value="未验证" color="#ffb020"
                  desc="本系统不会自行置为已验证" />
      </div>

      <div class="small" style="padding:9px 12px;border-radius:6px;line-height:1.75;
                  background:#211d14;border:1px solid #5c4617">
        <b style="color:#ffcf70">{{ st.stage_cn || '—' }}</b>
        <div class="muted" style="margin-top:4px">{{ st.statement }}</div>
        <div style="margin-top:6px" v-if="!st.params_stable">
          <span class="tag red">参数指纹不唯一</span>
          <span class="muted">账本内出现 {{ (st.param_digests_in_ledger || []).length }} 个指纹，期间改过阈值，分段样本不可合并解读。</span>
        </div>
      </div>

      <div style="margin-top:10px">
        <div class="small muted" style="margin-bottom:4px">把状态从「未验证」推进一步，需要同时满足：</div>
        <div class="small" v-for="(w, i) in (st.what_would_change_this || [])" :key="i"
             style="padding:3px 0;line-height:1.6">· {{ w }}</div>
      </div>

      <table class="tbl" style="margin-top:12px">
        <thead><tr><th>策略</th><th class="num">已结算交易日</th><th class="num">选中样本</th><th class="num">开盘买不到比例%</th></tr></thead>
        <tbody>
          <tr v-for="p in (st.per_strategy || [])" :key="p.strategy">
            <td>{{ NAMES[p.strategy] || p.strategy }}</td>
            <td class="num mono">{{ p.days }}</td>
            <td class="num mono">{{ p.selected }}</td>
            <td class="num mono" :class="p.untradable_rate > 20 ? 'down' : ''">{{ num(p.untradable_rate, 1) }}</td>
          </tr>
        </tbody>
      </table>
    </Panel>

    <!-- 2. 战绩表 -->
    <Panel title="前瞻战绩（扣费后超额）"
           :sub="rec.stage_cn || '选择策略与持有期'">
      <template #extra>
        <span class="pill" v-for="s in STRATS" :key="s" :class="{ active: strategy === s }"
              @click="strategy = s; loadRecord()">{{ NAMES[s] }}</span>
        <span class="pill" v-for="h in HORIZONS" :key="'h' + h" :class="{ active: horizon === h }"
              @click="horizon = h; loadRecord()">T+{{ h }}</span>
      </template>

      <div v-if="!rec.n_selected" class="empty">
        该策略该持有期尚无结算记录。先点「冻结今日信号」，次日之后点「结算前瞻结果」；
        收盘定时任务（15:14）会自动做这两件事。
      </div>
      <template v-else>
        <div class="small" style="line-height:1.7;margin-bottom:10px">
          报的是<b>扣费后相对基准的超额收益</b>，不是毛收益。短线票的毛收益几乎总是正的
          （小盘股 beta + 普涨），没有判别力。入场价固定为候选日<b>次一交易日开盘</b>，
          开盘即封死涨停的样本已剔除。
        </div>

        <div class="grid" style="grid-template-columns:repeat(4,1fr);margin-bottom:12px">
          <StatCard label="覆盖交易日" :value="rec.days" :desc="`${rec.first_date || ''} ~ ${rec.last_date || ''}`" />
          <StatCard label="选中样本 / 可选池" :value="`${rec.n_selected} / ${rec.n_universe}`" />
          <StatCard label="开盘买不到比例" :value="num(rec.untradable_rate, 1) + '%'"
                    :color="rec.untradable_rate > 20 ? '#ff6b6b' : ''" desc="已从统计正文剔除" />
          <StatCard label="分层置换 p 值"
                    :value="(rec.permutation || {}).p_value ?? '—'"
                    :color="pColor((rec.permutation || {}).p_value)"
                    desc="按交易日分层，日期效应已抵消" />
        </div>

        <table class="tbl">
          <thead><tr>
            <th>样本</th><th class="num">n</th><th class="num">均值%</th><th class="num">中位数%</th>
            <th class="num">25/75 分位</th><th class="num">95% 区间（均值）</th><th class="num">胜率%</th><th>可报</th>
          </tr></thead>
          <tbody>
            <tr v-for="row in statRows" :key="row.key">
              <td><b>{{ row.label }}</b></td>
              <td class="num mono">{{ row.d.n }}</td>
              <td class="num mono" :class="clsOf(row.d.mean)">{{ num(row.d.mean, 2) }}</td>
              <td class="num mono" :class="clsOf(row.d.median)">{{ num(row.d.median, 2) }}</td>
              <td class="num mono muted">{{ num(row.d.p25, 2) }} / {{ num(row.d.p75, 2) }}</td>
              <td class="num mono muted">
                [{{ num((row.d.ci || {}).lo, 2) }}, {{ num((row.d.ci || {}).hi, 2) }}]
              </td>
              <td class="num mono">{{ num(row.d.win_rate, 1) }}</td>
              <td><span class="tag" :class="row.d.reportable ? 'green' : 'gold'">
                {{ row.d.reportable ? '是' : '样本不足' }}</span></td>
            </tr>
          </tbody>
        </table>

        <div class="grid" style="grid-template-columns:1fr 1fr;margin-top:12px">
          <div>
            <div class="small muted" style="margin-bottom:4px">
              评分分层单调性：评分越高、后续超额越高才说明评分真有排序能力。
              只有最高档高，可能来自少数极端样本。
            </div>
            <table class="tbl">
              <thead><tr><th>档位</th><th class="num">n</th><th class="num">评分区间</th>
                <th class="num">中位超额%</th><th class="num">胜率%</th></tr></thead>
              <tbody>
                <tr v-for="b in ((rec.quintile || {}).buckets || [])" :key="b.bucket">
                  <td>第 {{ b.bucket }} 档</td>
                  <td class="num mono">{{ b.n }}</td>
                  <td class="num mono muted">{{ b.score_lo }}–{{ b.score_hi }}</td>
                  <td class="num mono" :class="clsOf(b.median)">{{ num(b.median, 2) }}</td>
                  <td class="num mono">{{ num(b.win_rate, 1) }}</td>
                </tr>
              </tbody>
            </table>
            <div class="small" style="margin-top:6px">
              单调：<span class="tag" :class="(rec.quintile || {}).monotonic ? 'green' : 'gold'">
                {{ (rec.quintile || {}).monotonic === null ? '样本不足' : ((rec.quintile || {}).monotonic ? '是' : '否') }}</span>
              <span class="muted" style="margin-left:8px">最高档-最低档 {{ num((rec.quintile || {}).spread_top_minus_bottom, 2) }}%</span>
            </div>
          </div>
          <div>
            <div class="small muted" style="margin-bottom:4px">
              置换检验：把「规则选出的票」换成「同一天同一可选池里随机抽同样多只」，
              重复上万次得到零分布。观测值落在零分布右尾越远，越难用运气解释。
            </div>
            <div class="kv">
              <span class="kk">覆盖交易日</span><span class="mono">{{ (rec.permutation || {}).days ?? '—' }}</span>
              <span class="kk">重抽样次数</span><span class="mono">{{ (rec.permutation || {}).iters ?? '—' }}</span>
              <span class="kk">实际观测均值</span><span class="mono">{{ num((rec.permutation || {}).observed, 3) }}%</span>
              <span class="kk">零分布均值</span><span class="mono">{{ num((rec.permutation || {}).null_mean, 3) }}%</span>
              <span class="kk">零分布 5%–95%</span><span class="mono">{{ num((rec.permutation || {}).null_p05, 3) }} ~ {{ num((rec.permutation || {}).null_p95, 3) }}</span>
              <span class="kk">效应量</span><span class="mono">{{ (rec.permutation || {}).effect_size ?? '—' }}</span>
              <span class="kk">p 值</span><span class="mono" :style="{ color: pColor((rec.permutation || {}).p_value) }">
                {{ (rec.permutation || {}).p_value ?? '—' }}</span>
            </div>
            <div class="small muted" style="margin-top:6px;line-height:1.6">
              {{ (rec.permutation || {}).note }}
            </div>
          </div>
        </div>

        <div class="small" style="margin-top:10px">
          <div class="muted" style="margin-bottom:3px">解读边界：</div>
          <div v-for="(c, i) in (rec.caveats || [])" :key="i" style="line-height:1.6">· {{ c }}</div>
        </div>
      </template>
    </Panel>

    <!-- 3. 多重检验 -->
    <Panel title="跨策略 × 持有期（BH 多重检验校正）"
           sub="同时看 4 策略 × 4 持有期必然会有一个 p<0.05；只有校正后仍显著的才算发现">
      <template #extra>
        <button class="btn" @click="loadMatrix" :disabled="mbusy">
          <span v-if="mbusy" class="spin"></span> 计算（较慢）
        </button>
      </template>
      <div v-if="!matrix.cells" class="empty">点「计算」执行；置换检验是 CPU 密集的，结果会缓存。</div>
      <template v-else>
        <table class="tbl">
          <thead><tr><th>策略</th><th>持有期</th><th>阶段</th><th class="num">交易日</th>
            <th class="num">样本</th><th class="num">买不到%</th><th class="num">p（未校正）</th>
            <th class="num">p（BH）</th><th>校正后是否算发现</th></tr></thead>
          <tbody>
            <tr v-for="c in matrix.cells" :key="c.strategy + c.horizon">
              <td>{{ NAMES[c.strategy] || c.strategy }}</td>
              <td>T+{{ c.horizon }}</td>
              <td class="small muted">{{ c.stage }}</td>
              <td class="num mono">{{ c.days }}</td>
              <td class="num mono">{{ c.n_selected }}</td>
              <td class="num mono">{{ num(c.untradable_rate, 1) }}</td>
              <td class="num mono">{{ c.p_value_raw ?? '—' }}</td>
              <td class="num mono" :style="{ color: pColor(c.p_value_bh) }">{{ c.p_value_bh ?? '—' }}</td>
              <td><span class="tag" :class="c.discovery_after_bh ? 'green' : 'gray'">
                {{ c.discovery_after_bh ? '是' : '否' }}</span></td>
            </tr>
          </tbody>
        </table>
        <div class="small muted" style="margin-top:8px;line-height:1.6">
          共 {{ (matrix.multiple_testing || {}).tests_run }} 次检验。{{ (matrix.multiple_testing || {}).note }}
        </div>
      </template>
    </Panel>

    <!-- 4. 对账 -->
    <Panel title="数据对账（两条独立路径 + 不变量）"
           :sub="rc.summary || '多源 failover 只保证「有数」，不保证「数对」'">
      <template #extra>
        <button class="btn" @click="loadReconcile" :disabled="rbusy">
          <span v-if="rbusy" class="spin"></span> 重新对账
        </button>
      </template>
      <div v-if="!rc.overall" class="empty">点「重新对账」执行。</div>
      <template v-else>
        <div class="small" style="margin-bottom:10px">
          总判定：<span class="tag" :class="overallTag(rc.overall)">{{ OVERALL_CN[rc.overall] || rc.overall }}</span>
        </div>
        <div class="grid" style="grid-template-columns:1fr 1fr">
          <div>
            <div class="small muted" style="margin-bottom:4px">路径 1 / 2：跨接口家数比对</div>
            <div class="kv">
              <span class="kk">涨停池（{{ (rc.cross_source || {}).pool_source }}）</span>
              <span class="mono">{{ (rc.cross_source || {}).pool_count }} 家</span>
              <span class="kk">分布第 11 档（{{ (rc.cross_source || {}).breadth_source }}）</span>
              <span class="mono">{{ (rc.cross_source || {}).breadth_count ?? '—' }} 家</span>
              <span class="kk">差异</span>
              <span class="mono">{{ (rc.cross_source || {}).diff ?? '—' }}（{{ num((rc.cross_source || {}).diff_pct, 2) }}%）</span>
            </div>
            <div class="small muted" style="margin-top:6px;line-height:1.6">{{ (rc.cross_source || {}).note }}</div>
          </div>
          <div>
            <div class="small muted" style="margin-bottom:4px">路径 3：按涨跌幅制度表独立判定封板</div>
            <div class="kv">
              <span class="kk">一致 / 已判定</span>
              <span class="mono">{{ (rc.price_based || {}).matched }} / {{ (rc.price_based || {}).decided }}
                （{{ num((rc.price_based || {}).match_rate, 2) }}%）</span>
              <span class="kk">不一致</span><span class="mono">{{ (rc.price_based || {}).mismatched }}</span>
              <span class="kk">口径未知（不计入分母）</span><span class="mono">{{ (rc.price_based || {}).unknown }}</span>
              <span class="kk">识别到 ST</span><span class="mono">{{ (rc.price_based || {}).st_detected }}</span>
            </div>
            <div class="small muted" style="margin-top:6px;line-height:1.6">{{ (rc.price_based || {}).note }}</div>
          </div>
        </div>

        <div v-if="((rc.price_based || {}).mismatched_sample || []).length" style="margin-top:10px">
          <div class="small muted" style="margin-bottom:4px">不一致样本（池内但按制度表未封在涨停价）</div>
          <table class="tbl">
            <thead><tr><th>代码</th><th>名称</th><th>板块</th><th class="num">收盘</th>
              <th class="num">涨幅%</th><th class="num">应有涨停价</th><th class="num">适用档位%</th></tr></thead>
            <tbody>
              <tr v-for="m in (rc.price_based || {}).mismatched_sample" :key="m.code">
                <td class="mono">{{ m.code }}</td><td>{{ m.name }}</td>
                <td class="small muted">{{ BOARD_CN[m.board] || m.board }}</td>
                <td class="num mono">{{ num(m.close) }}</td>
                <td class="num mono">{{ num(m.pct, 2) }}</td>
                <td class="num mono">{{ num(m.expected_limit_price) }}</td>
                <td class="num mono">{{ m.limit_pct ?? '—' }}</td>
              </tr>
            </tbody>
          </table>
        </div>

        <div style="margin-top:12px">
          <div class="small muted" style="margin-bottom:4px">不变量检查（违反即说明计算本身有误）</div>
          <table class="tbl">
            <thead><tr><th>检查项</th><th>结果</th><th>明细</th></tr></thead>
            <tbody>
              <tr v-for="(c, i) in (rc.invariants || [])" :key="i">
                <td>{{ c.check }}</td>
                <td><span class="tag" :class="c.ok === true ? 'green' : c.ok === false ? 'red' : 'gray'">
                  {{ c.ok === true ? '通过' : c.ok === false ? '失败' : '数据不足' }}</span></td>
                <td class="small mono muted">{{ c.detail }}</td>
              </tr>
            </tbody>
          </table>
        </div>

        <div class="small" style="margin-top:10px">
          <div class="muted" style="margin-bottom:3px">本对账的边界：</div>
          <div v-for="(l, i) in (rc.limits || [])" :key="i" style="line-height:1.6">· {{ l }}</div>
        </div>
      </template>
    </Panel>

    <!-- 5. 参数与制度 -->
    <div class="grid" style="grid-template-columns:1fr 1fr">
      <Panel title="规则参数与指纹" :sub="`复核的第一步：确认用的是哪组参数（${pm.version || '—'}）`">
        <div class="kv">
          <span class="kk">参数指纹</span><span class="mono">{{ pm.digest || '—' }}</span>
          <span class="kk">来回成本</span><span class="mono">{{ pm.cost_pct_round_trip ?? '—' }}%</span>
          <span class="kk">样本量下限</span><span class="mono">{{ ((pm.params || {}).stats || {}).min_sample ?? '—' }}</span>
          <span class="kk">Bootstrap 次数</span><span class="mono">{{ ((pm.params || {}).stats || {}).bootstrap_iters ?? '—' }}</span>
          <span class="kk">置换次数</span><span class="mono">{{ ((pm.params || {}).stats || {}).permutation_iters ?? '—' }}</span>
          <span class="kk">随机种子</span><span class="mono">{{ ((pm.params || {}).stats || {}).seed ?? '—' }}</span>
          <span class="kk">参数扰动幅度</span><span class="mono">{{ pctOf(((pm.params || {}).stats || {}).perturb) }}</span>
        </div>
        <div class="small muted" style="margin-top:8px;line-height:1.6">{{ pm.prior_note }}</div>
        <table class="tbl" style="margin-top:10px">
          <thead><tr><th>情绪因子</th><th class="num">权重</th><th>折分方式</th></tr></thead>
          <tbody>
            <tr v-for="(v, k) in ((pm.params || {}).sentiment || {})" :key="k">
              <td class="mono small">{{ k }}</td>
              <td class="num mono">{{ num(v.weight * 100, 1) }}%</td>
              <td class="small muted">{{ v.desc }}</td>
            </tr>
          </tbody>
        </table>
      </Panel>

      <Panel title="涨跌幅制度与口径变更时间线"
             sub="跨这些日期的任何序列都不是同一种数据">
        <table class="tbl">
          <thead><tr><th>板块</th><th class="num">普通股%</th><th class="num">风险警示%</th><th>置信</th></tr></thead>
          <tbody>
            <tr v-for="(v, k) in ((rg.note || {}).limits || {})" :key="k">
              <td>{{ BOARD_CN[k] || k }}</td>
              <td class="num mono">{{ v.normal ?? '—' }}</td>
              <td class="num mono">{{ v.st ?? '—' }}</td>
              <td><span class="tag" :class="v.confidence === 'high' ? 'green' : 'gold'">{{ v.confidence }}</span></td>
            </tr>
          </tbody>
        </table>
        <div class="small muted" style="margin-top:6px">{{ (rg.note || {}).warning }}</div>
        <div style="margin-top:10px">
          <div v-for="e in (rg.all_events || [])" :key="e.date" class="small"
               style="padding:6px 0;border-bottom:1px dashed #232d40;line-height:1.6">
            <b class="mono">{{ e.date }}</b> <span class="tag gray">{{ e.scope }}</span>
            <div>{{ e.what }}</div>
            <div class="muted">影响：{{ e.breaks }}</div>
          </div>
        </div>
      </Panel>
    </div>

    <!-- 6. 冻结记录 -->
    <Panel title="冻结记录（供第三方复核）"
           sub="每行都带真实冻结时间戳与参数指纹；重跑不改写时间戳">
      <template #extra>
        <select v-model="sigDate" @change="loadSignals" class="btn" style="padding:3px 8px">
          <option value="">最近一天</option>
          <option v-for="d in (sig.dates || []).slice().reverse()" :key="d" :value="d">{{ d }}</option>
        </select>
        <button class="btn" @click="loadSignals">查看</button>
      </template>
      <div v-if="!(sig.items || []).length" class="empty">账本为空；收盘后定时任务会自动冻结，也可点上方「冻结今日信号」。</div>
      <div v-else class="scroll-y" style="max-height:420px">
        <table class="tbl">
          <thead><tr><th>候选日</th><th>策略</th><th class="num">名次</th><th>选中</th>
            <th>代码</th><th>名称</th><th class="num">评分</th><th>参数指纹</th><th>冻结时间</th></tr></thead>
          <tbody>
            <tr v-for="r in (sig.items || []).slice(0, 400)" :key="r.trade_date + r.strategy + r.code">
              <td class="mono">{{ r.trade_date }}</td>
              <td class="small">{{ NAMES[r.strategy] || r.strategy }}</td>
              <td class="num mono">{{ r.rank ?? '—' }}</td>
              <td><span class="tag" :class="r.selected ? 'red' : 'gray'">{{ r.selected ? '选中' : '可选池' }}</span></td>
              <td class="mono dim">{{ r.code }}</td>
              <td>{{ r.name }}</td>
              <td class="num mono">{{ r.score ?? '—' }}</td>
              <td class="mono small muted">{{ r.param_digest }}</td>
              <td class="mono small muted">{{ r.frozen_at }}</td>
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
import StatCard from '../components/StatCard.vue'
import { api } from '../api'
import { toast } from '../store'
import { num, cls } from '../format'

const STRATS = ['first_board', 'relay', 'main_line', 'game_money']
const HORIZONS = [1, 2, 5, 10]
const NAMES = { first_board: '首板优选', relay: '二板接力', main_line: '主线龙头', game_money: '龙虎榜游资票' }
const BOARD_CN = { main_sh: '沪市主板', main_sz: '深市主板', chinext: '创业板', star: '科创板', bse: '北交所', unknown: '未知' }
const OVERALL_CN = { consistent: '两条独立路径一致', inconsistent: '不一致，需人工查口径', fail: '不变量失败，计算有误', incomplete: '路径缺数，本次无法交叉验证', error: '对账未能执行' }

const st = ref({}); const rec = ref({}); const matrix = ref({}); const rc = ref({})
const pm = ref({}); const rg = ref({}); const sig = ref({})
const strategy = ref('first_board'); const horizon = ref(1); const sigDate = ref('')
const busy = ref(false); const mbusy = ref(false); const rbusy = ref(false)

const clsOf = v => cls(v)
const pColor = p => (p === null || p === undefined ? '' : (p <= 0.05 ? '#ff6b6b' : '#8d9bb1'))
const pctOf = v => (v === null || v === undefined ? '—' : (v * 100).toFixed(0) + '%')
const overallTag = o => ({ consistent: 'green', inconsistent: 'gold', fail: 'red', incomplete: 'gray', error: 'gray' }[o] || 'gray')

const statRows = computed(() => [
  { key: 'sel', label: '选中组·扣费后超额', d: rec.value.selected || {} },
  { key: 'uni', label: '同日可选池·扣费后超额', d: rec.value.universe || {} },
  { key: 'net', label: '选中组·扣费后收益（未扣基准）', d: rec.value.selected_net_return || {} },
])

async function loadRecord() {
  try { rec.value = await api.trackRecord(strategy.value, horizon.value) }
  catch (e) { rec.value = {}; toast('战绩加载失败：' + e.message) }
}
async function loadMatrix() {
  mbusy.value = true
  try { matrix.value = await api.trackMatrix() }
  catch (e) { toast('多重检验失败：' + e.message) } finally { mbusy.value = false }
}
async function loadReconcile() {
  rbusy.value = true
  try { rc.value = await api.reconcile() }
  catch (e) { toast('对账失败：' + e.message) } finally { rbusy.value = false }
}
async function loadSignals() {
  try { sig.value = await api.trackSignals(sigDate.value) } catch (e) { sig.value = {} }
}
async function doFreeze() {
  busy.value = true
  try {
    const r = await api.trackFreeze()
    toast(r.ok ? `已冻结 ${r.frozen} 条记录` : `未冻结：${r.reason}`)
    await loadAll()
  } catch (e) { toast('冻结失败：' + e.message) } finally { busy.value = false }
}
async function doSettle() {
  busy.value = true
  try {
    const r = await api.trackSettle()
    toast(r.ok ? `已结算 ${r.settled} 条结果` : `未结算：${r.reason}`)
    await loadAll()
  } catch (e) { toast('结算失败：' + e.message) } finally { busy.value = false }
}
async function loadAll() {
  busy.value = true
  try {
    const [s, p, g] = await Promise.all([api.trackStatus(), api.researchParams(), api.researchRegime()])
    st.value = s; pm.value = p; rg.value = g
    await Promise.all([loadRecord(), loadSignals()])
  } catch (e) { toast('加载失败：' + e.message) } finally { busy.value = false }
}
onMounted(loadAll)
</script>
