import { createRouter, createWebHashHistory } from 'vue-router'

const routes = [
  { path: '/', redirect: '/dashboard' },
  { path: '/dashboard', name: 'dashboard', component: () => import('./views/Dashboard.vue'), meta: { title: '复盘总览', ico: '◎', grp: '盘面' } },
  { path: '/sentiment', name: 'sentiment', component: () => import('./views/Sentiment.vue'), meta: { title: '情绪周期', ico: '♥', grp: '盘面' } },
  { path: '/limitup', name: 'limitup', component: () => import('./views/LimitUp.vue'), meta: { title: '涨停复盘', ico: '▲', grp: '盘面' } },
  { path: '/sectors', name: 'sectors', component: () => import('./views/Sectors.vue'), meta: { title: '板块主线', ico: '▤', grp: '资金' } },
  { path: '/lhb', name: 'lhb', component: () => import('./views/Lhb.vue'), meta: { title: '龙虎榜', ico: '★', grp: '资金' } },
  { path: '/global', name: 'global', component: () => import('./views/Global.vue'), meta: { title: '外围市场', ico: '⊕', grp: '外部' } },
  { path: '/macro', name: 'macro', component: () => import('./views/Macro.vue'), meta: { title: '宏观水位', ico: '◈', grp: '外部' } },
  { path: '/news', name: 'news', component: () => import('./views/News.vue'), meta: { title: '快讯资讯', ico: '✎', grp: '外部' } },
  { path: '/screener', name: 'screener', component: () => import('./views/Screener.vue'), meta: { title: '游资选股器', ico: '⌕', grp: '决策' } },
  { path: '/auction', name: 'auction', component: () => import('./views/Auction.vue'), meta: { title: '次日竞价确认', ico: '⚡', grp: '决策' } },
  { path: '/report', name: 'report', component: () => import('./views/Report.vue'), meta: { title: '复盘报告', ico: '▣', grp: '决策' } },
  { path: '/research', name: 'research', component: () => import('./views/Research.vue'), meta: { title: '证据与验证', ico: '⚖', grp: '验证' } },
  { path: '/settings', name: 'settings', component: () => import('./views/Settings.vue'), meta: { title: '数据源设置', ico: '⚙', grp: '决策' } },
]

export const router = createRouter({ history: createWebHashHistory(), routes })
export default router