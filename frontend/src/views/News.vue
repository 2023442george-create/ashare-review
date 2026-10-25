<template>
  <div class="stack">
    <div class="grid" style="grid-template-columns:1fr 320px">
      <Panel nopad tight>
        <div class="panel-hd">
          <h3>7×24 快讯<span class="sub">{{ items.length }} 条 · 已聚合去重</span></h3>
          <div class="row">
            <input class="inp" style="width:150px" v-model="kw" placeholder="关键词搜索，如：存储" @keyup.enter="load" />
            <select class="inp" v-model="src" @change="load">
              <option value="">全部来源</option>
              <option v-for="s in sourceList" :key="s" :value="s">{{ s }}</option>
            </select>
            <span class="tag gray" v-if="data.meta">耗时 {{ Math.round(data.meta.elapsed_ms || 0) }}ms</span>
          </div>
        </div>
        <div class="panel-bd">
          <div class="row-wrap" style="margin-bottom:10px">
            <span class="pill" :class="{ active: tag === '' }" @click="tag = ''">全部</span>
            <span class="pill" v-for="t in (data.tag_stat || []).slice(0, 12)" :key="t.tag"
                  :class="{ active: tag === t.tag }" @click="tag = t.tag">{{ t.tag }} {{ t.count }}</span>
          </div>
          <div style="max-height:calc(100vh - 250px);overflow-y:auto">
            <div class="news-item" :class="{ imp: n.important }" v-for="(n, i) in items" :key="i">
              <div class="t">
                <span class="tag red tiny" v-if="n.important">重要</span>
                <a v-if="n.url" :href="n.url" target="_blank" rel="noopener" style="color:#e8eef7">{{ n.title }}</a>
                <span v-else>{{ n.title }}</span>
              </div>
              <div class="t small muted" v-if="n.summary && n.summary !== n.title" style="margin-top:3px;white-space:normal">{{ n.summary }}</div>
              <div class="m">
                <span>{{ shortTime(n.time) }}</span><span class="src">{{ n.source }}</span>
                <span class="tag gray" v-for="t in (n.tags || []).slice(0, 3)" :key="t">{{ t }}</span>
                <span class="tag blue tiny" v-for="c in (n.codes || []).slice(0, 3)" :key="c">{{ c }}</span>
              </div>
            </div>
            <div v-if="!items.length" class="empty">没有匹配的快讯</div>
          </div>
        </div>
      </Panel>

      <div class="stack">
        <Panel title="消息面热词" sub="今天资金在炒什么">
          <div class="row-wrap">
            <span class="tag purple" v-for="w in (data.hot_words || [])" :key="w.word"
                  style="font-size:12px;padding:4px 9px;cursor:pointer" @click="kw = w.word; load()">
              {{ w.word }} <b>{{ w.count }}</b>
            </span>
          </div>
        </Panel>
        <Panel title="数据源状态" sub="多源聚合，任一源不可用自动降级">
          <div v-for="s in (data.sources_tried || [])" :key="s" class="between small" style="padding:5px 0;border-bottom:1px dashed #232d40">
            <span>{{ nameOf(s) }}</span>
            <span class="tag" :class="(data.sources_ok || []).includes(s) ? 'green' : 'gray'">
              {{ (data.sources_ok || []).includes(s) ? '正常' : '不可用' }}
            </span>
          </div>
          <div class="small dim" style="margin-top:8px;line-height:1.7">
            财联社接口需要签名，若不可用会自动使用华尔街见闻 / 东财 / 新浪。
          </div>
        </Panel>
        <Panel title="游资读消息的方法" sub="">
          <div class="small muted" style="line-height:1.9">
            1. 只关心<b style="color:#ffb020">能映射到板块/个股</b>的消息，纯宏观口水话忽略；<br />
            2. 区分<b>新催化</b>（首次出现，可做首板）与<b>旧闻发酵</b>（已炒过，只做补涨或回避）；<br />
            3. 消息要和<b>当日涨停结构</b>对照：有消息+有涨停=主线确认；有消息无涨停=资金不认可；<br />
            4. 盘后重大政策/产业消息，次日竞价看<b>高开幅度与承接量</b>决定是否参与。
          </div>
        </Panel>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import Panel from '../components/Panel.vue'
import { api } from '../api'
import { shortTime } from '../format'

const data = ref({}); const kw = ref(''); const src = ref(''); const tag = ref('')
const items = computed(() => data.value.items || [])
const sourceList = ['华尔街见闻', '东方财富', '新浪财经', '财联社']
const nameOf = s => ({ wallstcn: '华尔街见闻', eastmoney: '东方财富', sina: '新浪财经', cls: '财联社', mock: '样例数据' }[s] || s)
async function load() {
  try { data.value = await api.news({ limit: 120, keyword: kw.value, source: src.value, tag: tag.value }) }
  catch (e) { data.value = {} }
}
watch(tag, load)
onMounted(load)
</script>