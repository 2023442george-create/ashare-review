<template>
  <div class="stack">
    <Panel :loading="loading">
      <div class="between" style="flex-wrap:wrap;gap:14px">
        <div class="row" style="gap:18px">
          <div style="text-align:center">
            <div class="tiny muted">综合评分</div>
            <div class="mono" :style="{ fontSize: '40px', fontWeight: 800, color: scoreColor(c.score) }">{{ c.score ?? '—' }}</div>
            <div class="tiny muted mono" v-if="(c.band || {}).lo !== undefined && (c.band || {}).lo !== null"
                 :title="c.band.note">±{{ c.band.perturb_pct }}% 扰动区间<br />{{ c.band.lo }}–{{ c.band.hi }}</div>
          </div>
          <div>
            <div class="row-wrap">
              <span class="tag gold" style="font-size:13px;padding:4px 12px">建议仓位 {{ c.position || '—' }}</span>
              <span class="tag" :style="{ background: phaseFg + '22', color: phaseFg, fontSize: '13px', padding: '4px 12px' }">
                {{ (r.sentiment || {}).phase ? r.sentiment.phase.phase : '—' }}期
              </span>
              <span class="tag gray">{{ r.date }}</span>
            </div>
            <div class="small muted" style="margin-top:7px;max-width:640px;line-height:1.7">{{ c.position_tip }}</div>
          </div>
        </div>
        <div class="row">
          <button class="btn" @click="load(true)" :disabled="loading">重新生成</button>
          <button class="btn" @click="copyMd">复制Markdown</button>
          <button class="btn primary" @click="dl">下载 .md</button>
        </div>
      </div>
      <div v-if="q.level" class="small" style="margin-top:10px;padding:8px 11px;border-radius:6px;line-height:1.75"
           :style="q.level === 'invalid' ? 'background:#2b171a;border:1px solid #5d252c' : q.level === 'limited' ? 'background:#2a2113;border:1px solid #5c4617' : 'background:#14261f;border:1px solid #24533f'">
        <b :style="{ color: q.level === 'invalid' ? '#ff7875' : q.level === 'limited' ? '#ffcf70' : '#63d6a3' }">
          数据体检：{{ q.level === 'invalid' ? '不足，已禁止仓位输出' : q.level === 'limited' ? '有限，结论需降权' : '完整' }}
        </b>
        <span class="muted"> · {{ q.as_of }}</span>
        <div v-for="(x, i) in [...(q.blockers || []), ...(q.warnings || [])]" :key="i" class="muted">· {{ x.message }}</div>
      </div>
      <div v-if="rs.stage" class="small" style="margin-top:10px;padding:8px 11px;border-radius:6px;line-height:1.7;background:#211d14;border:1px solid #5c4617">
        <div class="between" style="flex-wrap:wrap;gap:8px">
          <b style="color:#ffcf70">策略验证：未验证 · {{ rs.stage_cn }}</b>
          <router-link to="/research" class="tag blue" style="cursor:pointer">打开证据与验证页 →</router-link>
        </div>
        <div class="row-wrap" style="margin-top:5px;gap:6px">
          <span class="tag gray">已冻结 {{ rs.frozen_days ?? 0 }} 日</span>
          <span class="tag gray">已结算 {{ rs.settled_days ?? 0 }} 日</span>
          <span class="tag gray">成本假设 {{ rs.cost_pct }}%</span>
          <span class="tag gray">基准 {{ rs.benchmark }}</span>
          <span class="tag" :class="rs.params_stable ? 'gray' : 'red'">参数指纹 {{ rs.param_digest }}</span>
        </div>
        <div class="muted" style="margin-top:5px">{{ rs.statement }}</div>
      </div>
      <div v-if="rc.overall" class="small" style="margin-top:8px;padding:8px 11px;border-radius:6px;line-height:1.7"
           :style="rc.overall === 'consistent' ? 'background:#14261f;border:1px solid #24533f' : 'background:#2a2113;border:1px solid #5c4617'">
        <b :style="{ color: rc.overall === 'consistent' ? '#63d6a3' : '#ffcf70' }">数据对账：{{ rc.summary }}</b>
        <span class="muted" v-if="(rc.invariants_failed || []).length">
          · 不变量失败 {{ rc.invariants_failed.length }} 项</span>
      </div>
      <div class="divider"></div>
      <div class="grid" style="grid-template-columns:repeat(4,1fr);gap:10px">
        <div class="stat" v-for="p in (c.parts || [])" :key="p.name">
          <div class="k">{{ p.name }} <span class="dim tiny">权重{{ (p.weight * 100).toFixed(0) }}%</span></div>
          <div class="v mono" :style="{ color: scoreColor(p.score) }">{{ p.score }}</div>
          <div class="d tiny">{{ p.source }}</div>
          <div class="bar" style="margin-top:6px"><i :style="{ width: p.score + '%', background: scoreColor(p.score) }"></i></div>
        </div>
      </div>
    </Panel>

    <div class="grid" style="grid-template-columns:1.25fr 1fr">
      <Panel title="作战计划" sub="从仓位到风控的执行清单">
        <div v-for="(s, i) in (r.action_plan || [])" :key="i" style="padding:8px 0;border-bottom:1px dashed #232d40">
          <b style="color:#ffb020">{{ s.step }}</b>
          <div class="small" style="line-height:1.75;margin-top:3px;color:#c8d3e2;white-space:normal">{{ s.detail }}</div>
        </div>
      </Panel>

      <div class="stack">
        <Panel title="明日关注池" sub="由选股器自动生成">
          <div class="small muted" style="margin-bottom:5px">首板优选</div>
          <div class="row-wrap">
            <span class="chip" v-for="s in ((r.picks || {}).first_board || []).slice(0, 8)" :key="s.code">
              {{ s.name }} <b>{{ s.score }}</b>
            </span>
          </div>
          <div class="small muted" style="margin:9px 0 5px">接力候选</div>
          <div class="row-wrap">
            <span class="chip" v-for="s in ((r.picks || {}).relay || []).slice(0, 8)" :key="s.code">
              {{ s.name }} <b>{{ s.days_board }}</b>
            </span>
          </div>
          <div class="small muted" style="margin:9px 0 5px">风险回避</div>
          <div class="row-wrap">
            <span class="chip" style="border-color:#3a2530" v-for="s in ((r.picks || {}).risk || []).slice(0, 8)" :key="s.code">
              {{ s.name }} <b style="color:#00b578">{{ s.risk || '炸板' }}</b>
            </span>
          </div>
        </Panel>

        <Panel title="复盘笔记" sub="只保存在本地 SQLite">
          <textarea class="inp" style="width:100%;min-height:120px;line-height:1.7" v-model="note"
                    placeholder="记录今天的操作、情绪判断、明天的预案…（本地保存，不会上传）"></textarea>
          <div class="row" style="margin-top:8px;justify-content:flex-end">
            <button class="btn" @click="saveNote">保存笔记</button>
          </div>
        </Panel>
      </div>
    </div>

    <Panel nopad tight>
      <div class="panel-hd">
        <h3>报告全文<span class="sub">Markdown，可直接粘贴到笔记/公众号</span></h3>
        <div class="row">
          <span class="pill" :class="{ active: view === 'html' }" @click="view = 'html'">渲染视图</span>
          <span class="pill" :class="{ active: view === 'raw' }" @click="view = 'raw'">原文</span>
        </div>
      </div>
      <div class="panel-bd">
        <div v-if="view === 'html'" class="md" v-html="html"></div>
        <pre v-else class="small" style="white-space:pre-wrap;color:#a9b6c9;margin:0">{{ r.markdown }}</pre>
      </div>
    </Panel>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import Panel from '../components/Panel.vue'
import { api } from '../api'
import { toast } from '../store'
import { download, md2html, phaseColor, scoreColor } from '../format'

const r = ref({}); const note = ref(''); const view = ref('html'); const loading = ref(true)
const c = computed(() => r.value.composite || {})
const q = computed(() => r.value.data_quality || {})
const rs = computed(() => r.value.research_status || {})
const rc = computed(() => r.value.reconcile || {})
const html = computed(() => md2html(r.value.markdown || ''))
const phaseFg = computed(() => phaseColor(((r.value.sentiment || {}).phase || {}).phase))

async function load(force = false) {
  loading.value = true
  try {
    r.value = await api.report('', force)
    note.value = r.value.note || ''
  } catch (e) { toast('生成报告失败：' + e.message) } finally { loading.value = false }
}
async function saveNote() {
  try { await api.saveNote(r.value.date, note.value); toast('笔记已保存到本地') }
  catch (e) { toast('保存失败：' + e.message) }
}
function dl() { download(`A股复盘报告_${r.value.date || 'latest'}.md`, r.value.markdown || '') }
async function copyMd() {
  try { await navigator.clipboard.writeText(r.value.markdown || ''); toast('Markdown 已复制到剪贴板') }
  catch (e) { toast('复制失败，请切换到「原文」手动选择') }
}
onMounted(() => load(false))
</script>