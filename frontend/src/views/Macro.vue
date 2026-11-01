<!--
  宏观水位页：回答"整体该积极还是防守"。
  数据来自 /api/macro/overview（估值分位、ERP、国债、红利息差、成交额/两融分位、宽基 ETF 份额、温度分）
  和 /api/macro/history（每日温度快照）。缺失项显示"—"并列在「数据缺口」里，不会用 0 代替。
-->
<template>
  <div class="stack">
    <div v-if="err" class="err">{{ err }}</div>

    <!-- 第一行：最关键的 6 个数 -->
    <div class="grid" style="grid-template-columns:repeat(6,1fr)">
      <StatCard label="宏观温度" :value="t.score ?? '—'" :color="t.score == null ? '' : scoreColor(t.score)"
                :bar="t.score ?? null" :desc="tempDesc" :help="h('temperature')" />
      <StatCard label="沪深300 PE" :value="num(v300.pe, 2)" :desc="pctDesc(v300.pe_pct, '近10年分位')"
                :help="h('csi300') + '（来源：' + (v300.pe_source || '—') + '）'" />
      <StatCard label="中证全指 PE" :value="num(vall.pe, 2)" :desc="pctDesc(vall.pe_pct, '近10年分位')"
                :help="h('csiall') + '（来源：' + (vall.pe_source || '—') + '）'" />
      <StatCard label="股债性价比 ERP" :value="pv(erp.erp)" :desc="pctDesc(erp.erp_pct, '近10年分位')" :help="h('erp')" />
      <StatCard label="10年期国债" :value="pv(rates.cn10y, 3)" :desc="bpDesc" :help="h('cn10y')" />
      <StatCard label="两融余额" :value="margin.balance_yi == null ? '—' : num(margin.balance_yi, 0) + ' 亿'"
                :desc="`占流通市值 ${pv(margin.float_ratio)}（分位 ${margin.float_ratio_pct ?? '—'}%）· ${(margin.date || '—').slice(5)}`"
                :help="h('margin')" />
    </div>

    <div class="grid" style="grid-template-columns:1.3fr 1fr">
      <!-- 温度分由哪几项组成、每项多热 -->
      <Panel title="温度构成" :sub="`数据日 ${d.as_of || '—'}；总分 = (估值分 + 资金分) / 2，ERP 取反向`" :loading="loading">
        <template #extra>
          <button class="btn" @click="load(true)" :disabled="busy">
            <span v-if="busy" class="spin"></span> {{ busy ? '重新拉取中' : '重新拉取' }}
          </button>
        </template>
        <table class="tbl">
          <thead><tr><th>指标</th><th class="num">当前值</th><th class="num">历史分位</th>
            <th style="width:28%">热度</th><th>窗口</th><th>来源</th></tr></thead>
          <tbody v-for="g in GROUPS" :key="g.key">
            <!-- 分组标题行：子分数 + 档位 -->
            <tr style="background:rgba(255,255,255,.03)">
              <td colspan="6">
                <b>{{ g.name }}</b>
                <span class="mono" style="margin-left:8px;font-size:14px"
                      :style="{ color: sub(g.key).score == null ? '#8d9bb1' : scoreColor(sub(g.key).score) }">
                  {{ sub(g.key).score ?? '—' }}</span>
                <span class="small muted" style="margin-left:6px">{{ sub(g.key).label }} · 可用 {{ sub(g.key).used ?? 0 }}/{{ sub(g.key).total ?? 0 }}</span>
                <span class="small dim" style="margin-left:8px">{{ g.desc }}</span>
                <span v-if="g.key === 'flow' && sub('flow').estimated" class="tag gold tiny" style="margin-left:6px">含按量推算的成交额</span>
              </td>
            </tr>
            <tr v-for="c in comps.filter(x => x.group === g.key)" :key="c.key">
              <td>{{ c.name }} <span v-if="c.how" class="help" :title="c.how">?</span></td>
              <td class="num mono">{{ c.value == null ? '—' : num(c.value, c.unit === '亿' ? 0 : 2) + ' ' + c.unit }}</td>
              <td class="num mono">{{ c.pct == null ? '—' : c.pct + '%' }}</td>
              <td>
                <div class="bar" v-if="c.heat != null"><i :style="{ width: c.heat + '%', background: scoreColor(c.heat) }"></i></div>
                <span v-else class="small dim">缺数据，不计入</span>
              </td>
              <td class="small muted">{{ c.window }}</td>
              <td class="small"><span class="src">{{ c.source || '—' }}</span></td>
            </tr>
          </tbody>
        </table>
        <div class="small muted" style="line-height:1.7;margin-top:8px">
          <b :style="{ color: t.score == null ? '#8d9bb1' : scoreColor(t.score) }">{{ t.label || '—' }}</b>：{{ t.tip }}
          <div class="dim">{{ d.disclaimer }}</div>
        </div>
      </Panel>

      <!-- 温度历史：定时任务每天 15:25 / 21:10 写一条 -->
      <Panel title="温度历史" sub="每个交易日收盘后自动记录" :loading="loading"
             :empty="hist.length < 2" empty-text="每个交易日 15:25 自动记录一条，攒满两天后显示曲线">
        <EChart :option="histOpt" :height="250" />
      </Panel>
    </div>

    <div class="grid" style="grid-template-columns:1fr 1fr">
      <Panel title="股债性价比 ERP" :sub="erpSub" :how="erp.how" :loading="loading" :empty="!(erp.series || []).length">
        <EChart :option="erpOpt" :height="260" />
      </Panel>
      <Panel title="估值（滚动 PE）" sub="近10年，中证官方口径" :how="how('pe')" :loading="loading" :empty="!(v300.pe_series || []).length">
        <EChart :option="peOpt" :height="230" />
        <div class="row-wrap small" style="gap:6px;margin-top:6px">
          <span class="chip" v-for="v in val" :key="v.key">
            {{ v.name }}<template v-if="v.pb_proxy">（取{{ v.pb_proxy }}）</template>：PB {{ num(v.pb, 2) }}（{{ v.pb_pct == null ? '分位—' : '分位 ' + v.pb_pct + '%' }}）·
            股息率 {{ pv(v.dividend_yield) }}
          </span>
        </div>
        <div class="small dim" style="margin-top:4px">PB = 市值 / 净资产，亏损时 PE 失真可以看它；股息率 = 分红 / 市值，高于国债越多越有吸引力</div>
      </Panel>
    </div>

    <div class="grid" style="grid-template-columns:1fr 1fr">
      <Panel title="利率" :sub="`中美10年利差 ${pv(rates.spread)}；美国10年 ${pv(rates.us10y)}`" :how="rates.how" :loading="loading"
             :empty="!(rates.series || []).length">
        <EChart :option="rateOpt" :height="230" />
        <div class="row-wrap small" style="gap:6px;margin-top:6px">
          <span class="chip">中国2年 {{ pv(rates.cn2y, 3) }}</span>
          <span class="chip">中国30年 {{ pv(rates.cn30y, 3) }}</span>
          <span class="chip">
            期限利差 10Y−2Y <b>{{ pv(rates.term_spread, 3) }}</b>（近10年分位 {{ rates.term_pct ?? '—' }}%，20日
            {{ rates.term_chg20_bp == null ? '—' : signed(rates.term_chg20_bp, 1) + 'bp' }}）
            <span class="help" :title="rates.term_how">?</span>
          </span>
          <span class="chip">
            红利股息率差：{{ div.name }} {{ pv(div.dividend_yield) }} − 10年国债 = <b>{{ pv(div.spread) }}</b>
            <span class="help" :title="div.how">?</span>
          </span>
        </div>
      </Panel>
      <Panel title="资金水位" :sub="flowSub" :how="how('flows')" :loading="loading"
             :empty="!(turnover.series || []).length && !(margin.series || []).length">
        <EChart :option="flowOpt" :height="230" />
        <div class="small muted" style="margin-top:6px">
          最新成交额 {{ turnover.latest_yi == null ? '—' : num(turnover.latest_yi, 0) + ' 亿' }}，
          20日均值 {{ turnover.ma20_yi == null ? '—' : num(turnover.ma20_yi, 0) + ' 亿' }}（分位 {{ turnover.pct ?? '—' }}%）；
          两融余额分位 {{ margin.pct ?? '—' }}%，20日变化 <span :class="cls(margin.chg20_yi)">{{ signed(margin.chg20_yi, 0) }} 亿</span>（{{ margin.date || '—' }}）；
          融资买入占成交额 <b>{{ pv(mbuy.ratio) }}</b>（5日均 {{ pv(mbuy.ma5) }}，分位 {{ mbuy.pct ?? '—' }}%）
          <span class="help" :title="mbuy.how">?</span>
          <span v-if="turnover.estimated" class="tag gold tiny">成交额为按量推算</span>
        </div>
      </Panel>
    </div>

    <!-- 宽基 ETF 份额：国家队托底最直接的公开痕迹 -->
    <Panel title="宽基 ETF 份额" :sub="etfSub" :how="how('etf')" :loading="loading" :empty="!(etf.items || []).length"
           :empty-text="etf.error || '暂无 ETF 份额数据'">
      <table class="tbl">
        <thead><tr><th>跟踪指数</th><th class="num">合计份额(亿份)</th><th class="num">较前1日</th>
          <th class="num">较前5日</th><th class="num">较前20日</th><th>产品</th></tr></thead>
        <tbody>
          <tr v-for="g in (etf.groups || [])" :key="g.track">
            <td><b>{{ g.track }}</b></td>
            <td class="num mono">{{ num(g.shares_yi, 2) }}</td>
            <td class="num mono" v-for="lag in [1, 5, 20]" :key="lag" :class="cls(g['chg_' + lag + 'd'])">
              {{ signed(g['chg_' + lag + 'd'], 2) }} <span class="small">({{ pctf(g['chg_' + lag + 'd_pct']) }})</span>
            </td>
            <td class="small muted">{{ g.codes.join(' / ') }}</td>
          </tr>
        </tbody>
      </table>
      <details style="margin-top:8px">
        <summary class="small muted" style="cursor:pointer">逐只明细</summary>
        <table class="tbl" style="margin-top:6px">
          <thead><tr><th>代码</th><th>名称</th><th class="num">份额(亿份)</th><th class="num">较前1日</th>
            <th class="num">较前5日</th><th class="num">较前20日</th></tr></thead>
          <tbody>
            <tr v-for="r in (etf.items || [])" :key="r.code">
              <td class="mono dim">{{ r.code }}</td><td>{{ r.name }}</td>
              <td class="num mono">{{ num(r.shares_yi, 2) }}</td>
              <td class="num mono" v-for="lag in [1, 5, 20]" :key="lag" :class="cls(r['chg_' + lag + 'd'])">
                {{ signed(r['chg_' + lag + 'd'], 2) }}
              </td>
            </tr>
          </tbody>
        </table>
      </details>
    </Panel>

    <!-- 股指期货前 20 会员多空持仓：大机构在期货端怎么站队 -->
    <Panel title="股指期货会员持仓" :sub="futSub" :how="how('futures')" :loading="loading" :empty="!futVars.some(v => v.date)"
           :empty-text="fut.error || '暂无持仓排名数据'">
      <div class="grid" style="grid-template-columns:repeat(4,1fr);gap:8px;margin-bottom:10px">
        <div class="stat" v-for="v in futVars" :key="v.code" :class="{ hl: futSel === v.code }"
             style="cursor:pointer" @click="futSel = v.code">
          <div class="k">{{ v.code }} · {{ v.index }}股指期货</div>
          <div class="v mono" :class="cls(v.net)" style="font-size:18px">{{ signed(v.net, 0) }}</div>
          <div class="d tiny">净持仓（手），较前日 <span :class="cls(v.net_chg)">{{ signed(v.net_chg, 0) }}</span></div>
          <div class="d tiny dim">多 {{ num(v.long, 0) }}（{{ signed(v.long_chg, 0) }}） / 空 {{ num(v.short, 0) }}（{{ signed(v.short_chg, 0) }}）</div>
          <div class="d tiny" v-if="basisOf(v.code).contract">
            主力 {{ basisOf(v.code).contract }} 基差 <span :class="cls(basisOf(v.code).basis_pct)">{{ pctf(basisOf(v.code).basis_pct) }}</span>
            · 年化 <span :class="cls(basisOf(v.code).annual_pct)">{{ pctf(basisOf(v.code).annual_pct) }}</span>
            <span class="dim">（剩 {{ basisOf(v.code).days }} 天）</span>
          </div>
        </div>
      </div>
      <!-- 品种对照：代码 → 现货指数 → 每点价值，换算一手合约金额用 -->
      <div class="row-wrap small" style="gap:6px;margin-bottom:10px">
        <span class="chip" v-for="f in FUT_INFO" :key="f.code">
          <b>{{ f.code }}</b> = {{ f.index }}股指期货 · 每点 {{ f.mult }} 元（一手 ≈ 指数点位 × {{ f.mult }}）
        </span>
      </div>
      <div class="grid" style="grid-template-columns:1fr 1.2fr">
        <div>
          <div class="small muted" style="margin-bottom:4px">前20会员合计净持仓趋势（负数 = 净空）</div>
          <EChart :option="futOpt" :height="260" />
        </div>
        <div>
          <div class="small muted" style="margin-bottom:4px">
            {{ futCur.code }}（{{ futCur.index }}）主要会员（{{ futCur.date || '—' }}，合约 {{ (futCur.contracts || []).join(' / ') }}）
          </div>
          <div class="scroll-y" style="max-height:270px">
            <table class="tbl">
              <thead><tr><th>会员</th><th class="num">多单(增减)</th><th class="num">空单(增减)</th><th class="num">净持仓(增减)</th></tr></thead>
              <tbody>
                <tr v-for="m in (futCur.members || [])" :key="m.name">
                  <td :style="m.name.includes('中信') ? 'color:#ffb020;font-weight:700' : ''">{{ m.name }}</td>
                  <td class="num mono">{{ num(m.long, 0) }} <span class="small" :class="cls(m.long_chg)">({{ signed(m.long_chg, 0) }})</span></td>
                  <td class="num mono">{{ num(m.short, 0) }} <span class="small" :class="cls(-m.short_chg)">({{ signed(m.short_chg, 0) }})</span></td>
                  <td class="num mono" :class="cls(m.net)">{{ signed(m.net, 0) }}
                    <span class="small" :class="cls(m.net_chg)">({{ signed(m.net_chg, 0) }})</span></td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </div>
      <div class="grid" style="grid-template-columns:1fr 1fr;margin-top:10px">
        <div>
          <div class="small muted" style="margin-bottom:4px">主力合约年化基差（负数 = 贴水）<span class="help" :title="h('basis')">?</span></div>
          <EChart :option="basisOpt" :height="200" />
        </div>
        <div class="small muted" style="line-height:1.8">
          <div>{{ basis.how }}</div>
          <div class="dim">基差口径：{{ basis.caliber || '—' }}</div>
          <div style="margin-top:6px">{{ fut.how }}</div>
          <div class="dim">持仓口径：{{ fut.caliber }}</div>
        </div>
      </div>
    </Panel>

    <!-- 风格比值：资金在追小盘还是抱大盘、偏防守还是偏进攻 -->
    <div class="grid" style="grid-template-columns:1fr 1fr">
      <Panel title="风格比值" sub="窗口起点 = 100，近约2年" :how="how('style')" :loading="loading" :empty="!styles.some(x => x.value != null)">
        <EChart :option="styleOpt" :height="230" />
        <div class="stack" style="gap:4px;margin-top:6px">
          <div class="small" v-for="x in styles" :key="x.key">
            <b>{{ x.name }}</b>（{{ x.num }} / {{ x.den }}）：分位 {{ x.pct ?? '—' }}%，20日
            <span :class="cls(x.chg20_pct)">{{ pctf(x.chg20_pct) }}</span>
            <div class="dim">{{ x.how }}</div>
          </div>
        </div>
      </Panel>
      <!-- AH 溢价：A 股相对 H 股贵多少 -->
      <Panel title="AH 溢价指数" :sub="`恒生沪深港通AH股溢价指数；${ah.date || '—'}，来源 ${ah.source || '—'}`" :how="ah.how" :loading="loading"
             :empty="ah.value == null">
        <div class="row" style="gap:14px;margin-bottom:4px">
          <span class="mono" style="font-size:22px" :style="{ color: ah.pct == null ? '#e8eef7' : scoreColor(ah.pct) }">{{ num(ah.value, 2) }}</span>
          <span class="small muted" v-if="(ah.series || []).length">近约2年分位 {{ ah.pct ?? '—' }}% · 20日 <span :class="cls(ah.chg20)">{{ signed(ah.chg20, 2) }}</span></span>
          <span class="small muted" v-else>较前日 <span :class="cls(ah.chg1)">{{ signed(ah.chg1, 2) }}</span> · 历史 K 线暂不可用，没有分位和走势</span>
        </div>
        <EChart v-if="(ah.series || []).length" :option="ahOpt" :height="200" />
      </Panel>
    </div>

    <div class="grid" style="grid-template-columns:1fr 1fr">
      <!-- 南向资金：内地资金往港股跑的力度 -->
      <Panel title="南向资金" :sub="`港股通（沪+深）每日净买入，亿元；来源 ${south.source || '—'}`" :how="south.how" :loading="loading"
             :empty="south.latest == null">
        <div class="row-wrap small" style="gap:6px;margin-bottom:6px">
          <span class="chip">{{ south.date }} 净买入 <b :class="cls(south.latest)">{{ signed(south.latest, 2) }}</b></span>
          <span class="chip">近5日 <b :class="cls(south.sum5)">{{ signed(south.sum5, 1) }}</b></span>
          <span class="chip">近20日 <b :class="cls(south.sum20)">{{ signed(south.sum20, 1) }}</b>（近一年分位 {{ south.sum20_pct ?? '—' }}%）</span>
          <span class="chip">近60日 <b :class="cls(south.sum60)">{{ signed(south.sum60, 1) }}</b></span>
        </div>
        <EChart :option="southOpt" :height="200" />
      </Panel>
      <!-- 限售解禁：未来供给压力 -->
      <Panel title="限售股解禁" :sub="`实际解禁市值（亿元），按当前股价估算；来源 ${lift.source || '—'}`" :how="lift.how" :loading="loading"
             :empty="lift.next30_yi == null">
        <div class="row-wrap small" style="gap:6px;margin-bottom:6px">
          <span class="chip">未来7日 <b>{{ num(lift.next7_yi, 0) }}</b></span>
          <span class="chip">未来30日 <b :style="{ color: (lift.next30_yi || 0) > (lift.past30_yi || 0) ? '#00b578' : '' }">{{ num(lift.next30_yi, 0) }}</b>
            （{{ lift.next30_count ?? '—' }} 家次）</span>
          <span class="chip">过去30日 {{ num(lift.past30_yi, 0) }}</span>
        </div>
        <EChart :option="liftOpt" :height="200" />
        <div class="small muted">
          解禁最多的几天：<span v-for="r in (lift.top_days || [])" :key="r.date" style="margin-right:10px">{{ r.date.slice(5) }} {{ num(r.cap_yi, 0) }}亿</span>
        </div>
      </Panel>
    </div>

    <!-- 缺口与探针：缺什么、为什么缺，一键核对每个源 -->
    <Panel title="数据缺口与接口核对" sub="缺失项不计入温度分，也不会用 0 或样例值代替">
      <template #extra>
        <button class="btn" @click="runProbe" :disabled="probing">
          <span v-if="probing" class="spin"></span> {{ probing ? '探测中' : '探测数据源' }}
        </button>
      </template>
      <ul v-if="gaps.length" class="small" style="line-height:1.9;padding-left:18px;margin:0">
        <li v-for="(g, i) in gaps" :key="i" style="color:#ffcf70">{{ g }}</li>
      </ul>
      <div v-else-if="!loading" class="small muted">本次所有分项都取到了数据。</div>
      <div class="small dim" style="margin-top:6px">
        来源：<span v-for="(v, k) in ((d.meta || {}).sources || {})" :key="k" style="margin-right:10px">{{ k }}={{ v }}</span>
        <span v-if="(d.meta || {}).cached" class="tag gray tiny">缓存</span>
        <span v-if="(d.meta || {}).offline" class="tag gold tiny">离线样例</span>
      </div>
      <table v-if="probeRes" class="tbl" style="margin-top:10px">
        <thead><tr><th>接口</th><th>状态</th><th class="num">行数</th><th class="num">耗时</th><th>详情</th></tr></thead>
        <tbody>
          <tr v-if="probeRes.note"><td colspan="5" class="small muted">{{ probeRes.note }}</td></tr>
          <tr v-for="p in (probeRes.items || [])" :key="p.name">
            <td>{{ p.name }}</td>
            <td><span class="tag" :class="p.ok ? 'green' : 'red'">{{ p.ok ? '可用' : '不可用' }}</span></td>
            <td class="num mono">{{ p.rows ?? '—' }}</td>
            <td class="num mono">{{ p.elapsed_ms }}ms</td>
            <td class="small mono" style="white-space:normal;word-break:break-all">{{ probeDetail(p) }}</td>
          </tr>
        </tbody>
      </table>
    </Panel>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import Panel from '../components/Panel.vue'
import StatCard from '../components/StatCard.vue'
import EChart from '../components/EChart.vue'
import { api } from '../api'
import { indicatorHelp as h, indicatorHow as how } from '../store'
import { cls, num, pct as pctf, signed, scoreColor } from '../format'

// ---------- 状态 ----------
const d = ref({})              // /api/macro/overview 的完整响应
const hist = ref([])           // 每日温度快照
const loading = ref(true)
const busy = ref(false)
const err = ref('')
const probeRes = ref(null)     // 探针结果，点按钮后才有
const probing = ref(false)

// ---------- 从响应里拆出各分项（全部给空对象兜底，模板里不用判空） ----------
const t = computed(() => d.value.temperature || {})
const comps = computed(() => d.value.components || [])
const val = computed(() => d.value.valuation || [])
const v300 = computed(() => val.value[0] || {})
const vall = computed(() => val.value[1] || {})
const erp = computed(() => d.value.erp || {})
const rates = computed(() => d.value.rates || {})
const div = computed(() => d.value.dividend || {})
const turnover = computed(() => (d.value.flows || {}).turnover || {})
const margin = computed(() => (d.value.flows || {}).margin || {})
const etf = computed(() => d.value.etf || {})
const gaps = computed(() => d.value.gaps || [])
// 温度分的两个子分数：估值看大方向（慢），资金看热度（快）
const GROUPS = [
  { key: 'valuation', name: '估值分', desc: '慢变量：一年以上的大方向' },
  { key: 'flow', name: '资金分', desc: '快变量：几周内的冷热' },
]
const sub = k => t.value[k] || {}
const tempDesc = computed(() => `${t.value.label || '—'} · 估值 ${sub('valuation').score ?? '—'} / 资金 ${sub('flow').score ?? '—'}`)
const fut = computed(() => d.value.futures || {})
const futVars = computed(() => fut.value.varieties || [])
const futSel = ref('IF')                       // 当前查看会员明细的品种
const futCur = computed(() => futVars.value.find(v => v.code === futSel.value) || {})
const mbuy = computed(() => (d.value.flows || {}).margin_buy || {})
const basis = computed(() => d.value.basis || {})
const basisOf = code => (basis.value.items || []).find(x => x.code === code) || {}
const styles = computed(() => (d.value.style || {}).items || [])
const ah = computed(() => (d.value.cross || {}).ah || {})
const south = computed(() => (d.value.cross || {}).south || {})
const lift = computed(() => d.value.lift || {})

// ---------- 文案格式化 ----------
/** 百分数（不带正负号），缺失显示 — */
const pv = (v, k = 2) => (v === null || v === undefined ? '—' : Number(v).toFixed(k) + '%')
/** 分位说明：缺失时直接说明原因，而不是显示 0% */
const pctDesc = (p, label) => (p === null || p === undefined ? label + '：样本不足或缺数据' : `${label} ${p}%`)
const bpDesc = computed(() => {
  const b = rates.value.cn10y_chg20_bp
  return b === null || b === undefined ? '20日变化 —' : `20日变化 ${b > 0 ? '+' : ''}${b}bp`
})
const erpSub = computed(() => {
  const e = erp.value
  return e.erp == null ? '缺数据' : `盈利收益率 ${pv(e.earnings_yield)} − 10年国债 ${pv(e.cn10y, 3)}；样本 ${e.n} 天，自 ${e.from}`
})
const flowSub = computed(() => `成交额来源 ${turnover.value.source || '—'}，两融来源 ${margin.value.source || '—'}`)
const etfSub = computed(() => {
  const e = etf.value
  const ds = e.dates || {}
  return `统计日 ${e.date || '—'}（对比 ${ds['1d'] || '—'} / ${ds['5d'] || '—'} / ${ds['20d'] || '—'}）；${e.coverage || ''}`
})
const futSub = computed(() => {
  const f = fut.value
  return f.date ? `中金所 ${f.date}，近 ${f.days} 个交易日；点卡片切换品种` : '中金所每日 16:30 左右公布'
})
/** 探针一行的详情：优先显示错误，其次缺失字段/代码，最后是样例值 */
function probeDetail(p) {
  if (p.error) return p.error
  const parts = []
  if (p.missing_fields && p.missing_fields.length) parts.push('缺字段 ' + p.missing_fields.join(','))
  if (p.missing_codes && p.missing_codes.length) parts.push('缺代码 ' + p.missing_codes.join(','))
  if (p.date) parts.push('统计日 ' + p.date)
  if (p.sample) parts.push('样例 ' + JSON.stringify(p.sample))
  if (p.raw_keys && p.raw_keys.length && (!p.ok || p.show_keys)) parts.push('实际字段 ' + p.raw_keys.join(','))
  return parts.join('；') || '—'
}

// ---------- 图表：统一深色主题的时间轴折线 ----------
const AX = { axisLabel: { color: '#5f6d84', fontSize: 10 }, axisLine: { lineStyle: { color: '#232d40' } },
  splitLine: { lineStyle: { color: '#1a2233' } } }
const LEGEND = { textStyle: { color: '#8d9bb1', fontSize: 10 }, top: 0, right: 8 }
/** 生成一条无点标记的折线系列 */
const ln = (name, data, color, more = {}) => Object.assign(
  { name, type: 'line', data, showSymbol: false, lineStyle: { width: 1.6, color }, itemStyle: { color } }, more)
/** 时间轴折线图的公共骨架 */
function timeOpt(series, yAxis, legend = true) {
  const opt = {
    grid: { left: 50, right: 46, top: legend ? 30 : 16, bottom: 26 },
    tooltip: { trigger: 'axis' },
    xAxis: Object.assign({ type: 'time' }, AX, { splitLine: { show: false } }),
    yAxis, series,
  }
  if (legend) opt.legend = LEGEND
  return opt
}
const yVal = (name, more = {}) => Object.assign({ type: 'value', name, scale: true,
  nameTextStyle: { color: '#5f6d84', fontSize: 10 } }, AX, more)

// ERP：一条线 + 20%/中位/80% 三条历史分位参考线
const erpOpt = computed(() => {
  const q = erp.value.q || {}
  const marks = [['q20', '20%', '#36cfc9'], ['q50', '中位', '#8d9bb1'], ['q80', '80%', '#ff7a45']]
    .filter(([k]) => q[k] !== null && q[k] !== undefined)
    .map(([k, label, c]) => ({ yAxis: q[k], lineStyle: { color: c, type: 'dashed' },
      label: { formatter: `${label} {c}%`, color: c, fontSize: 9, position: 'insideEndTop' } }))
  return timeOpt([ln('ERP', erp.value.series || [], '#ffb020', {
    areaStyle: { color: 'rgba(255,176,32,.08)' },
    markLine: { silent: true, symbol: 'none', data: marks } })], yVal('%'), false)
})
// 估值：沪深300 与中证全指两条 PE
const peOpt = computed(() => timeOpt([
  ln('沪深300', v300.value.pe_series || [], '#ff7a45'),
  ln('中证全指', vall.value.pe_series || [], '#4c9aff'),
], yVal('倍')))
// 利率：中国10Y、美国10Y 与中美利差
const rateOpt = computed(() => {
  const rs = rates.value.series || []
  return timeOpt([
    ln('中国10Y', rs.map(r => [r[0], r[1]]), '#ffb020'),
    ln('美国10Y', rs.map(r => [r[0], r[2]]), '#4c9aff'),
    ln('中美利差', rs.map(r => [r[0], r[3]]), '#a97bff', { lineStyle: { width: 1, type: 'dashed', color: '#a97bff' } }),
    ln('期限利差10Y-2Y', rs.map(r => [r[0], r[4]]), '#36cfc9', { lineStyle: { width: 1, type: 'dashed', color: '#36cfc9' } }),
  ], yVal('%'))
})
// 资金：成交额20日均值（左轴）与两融余额（右轴）
const flowOpt = computed(() => timeOpt([
  ln('成交额20日均值', turnover.value.series || [], '#ffb020'),
  ln('两融余额', margin.value.series || [], '#a97bff', { yAxisIndex: 1 }),
], [yVal('成交额(亿)'), yVal('两融(亿)', { splitLine: { show: false } })]))
// 股指期货：品种对照表（中金所合约乘数）与四个品种前20会员合计净持仓
const FUT_INFO = [
  { code: 'IF', index: '沪深300', mult: 300 }, { code: 'IH', index: '上证50', mult: 300 },
  { code: 'IC', index: '中证500', mult: 200 }, { code: 'IM', index: '中证1000', mult: 200 },
]
const FUT_COLORS = ['#ff7a45', '#ffb020', '#4c9aff', '#a97bff']
const futOpt = computed(() => timeOpt(futVars.value.map((v, i) =>
  ln(`${v.code} ${v.index}`, (v.history || []).map(r => [r[0], r[3]]), FUT_COLORS[i % 4], { showSymbol: true, symbolSize: 3 })), yVal('手')))
// 期指主力合约年化基差
const basisOpt = computed(() => {
  const h = basis.value.history || {}
  return timeOpt(FUT_INFO.map((f, i) => ln(`${f.code} ${f.index}`, (h[f.code] || []).map(r => [r[0], r[1]]),
    FUT_COLORS[i], { showSymbol: true, symbolSize: 3 })), yVal('%'))
})
// 风格比值：归一化后同图比较
const styleOpt = computed(() => timeOpt(styles.value.map((x, i) =>
  ln(x.name, x.series || [], ['#ff7a45', '#4c9aff'][i % 2])), yVal('起点=100')))
// AH 溢价：一条线 + 20% / 80% 分位参考线
const ahOpt = computed(() => {
  const q = ah.value.q || {}
  const marks = [['q20', '20%', '#36cfc9'], ['q80', '80%', '#ff7a45']].filter(([k]) => q[k] != null)
    .map(([k, label, c]) => ({ yAxis: q[k], lineStyle: { color: c, type: 'dashed' },
      label: { formatter: `${label} {c}`, color: c, fontSize: 9, position: 'insideEndTop' } }))
  return timeOpt([ln('AH溢价', ah.value.series || [], '#ffb020', { markLine: { silent: true, symbol: 'none', data: marks } })],
    yVal(''), false)
})
// 南向资金：每日净买入柱（红 = 净买入，绿 = 净卖出）
const southOpt = computed(() => timeOpt([{
  name: '净买入', type: 'bar', barMaxWidth: 6,
  data: (south.value.series || []).map(r => ({ value: r, itemStyle: { color: r[1] >= 0 ? '#ff4d4f' : '#00b578' } })),
}], yVal('亿元'), false))
// 限售解禁：未来30日逐日柱
const liftOpt = computed(() => timeOpt([{
  name: '解禁市值', type: 'bar', barMaxWidth: 10, itemStyle: { color: '#a97bff' },
  data: (lift.value.future || []).map(r => [r.date, r.cap_yi]),
}], yVal('亿元'), false))
// 温度历史：0~100，20/80 两条档位线
const histOpt = computed(() => timeOpt([ln('温度分', hist.value.map(r => [r.trade_date, r.score]), '#ff7a45', {
  showSymbol: true, symbolSize: 4,
  markLine: { silent: true, symbol: 'none', data: [
    { yAxis: 80, lineStyle: { color: '#ff4d4f', type: 'dashed' }, label: { formatter: '过热', color: '#ff4d4f', fontSize: 9 } },
    { yAxis: 20, lineStyle: { color: '#36cfc9', type: 'dashed' }, label: { formatter: '冰点', color: '#36cfc9', fontSize: 9 } }] },
})], yVal('', { min: 0, max: 100, scale: false }), false))

// ---------- 取数 ----------
/** 拉取总览与历史；force=true 时后端绕过缓存重新抓取所有宏观源 */
async function load(force = false) {
  busy.value = force
  err.value = ''
  try {
    // 两个请求互不依赖，并发发出；一个失败不影响另一个
    const [a, b] = await Promise.allSettled([api.macro(force), api.macroHistory(250)])
    if (a.status === 'fulfilled') d.value = a.value
    else err.value = '宏观数据加载失败：' + a.reason.message
    if (b.status === 'fulfilled') hist.value = (b.value.items || []).filter(r => r.score !== null && r.score !== undefined)
  } finally {
    loading.value = false
    busy.value = false
  }
}
/** 调用探针接口，逐个检查数据源是否可用、字段是否齐全 */
async function runProbe() {
  probing.value = true
  try { probeRes.value = await api.macroProbe() } catch (e) { probeRes.value = { items: [], note: '探测失败：' + e.message } }
  finally { probing.value = false }
}

onMounted(() => load(false))
</script>
