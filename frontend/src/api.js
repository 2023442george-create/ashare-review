import axios from 'axios'

const http = axios.create({ baseURL: '/api', timeout: 120000 })

http.interceptors.response.use(
  r => r.data,
  e => {
    const msg = (e && e.response && e.response.data && e.response.data.detail) || (e && e.message) || '网络错误'
    return Promise.reject(new Error(msg))
  }
)

export const api = {
  health: () => http.get('/health'),
  refresh: (kind = 'all') => http.post('/refresh', null, { params: { kind } }),

  marketOverview: (force = false) => http.get('/market/overview', { params: { force } }),
  kline: (symbol, days = 120) => http.get('/market/kline', { params: { symbol, days } }),
  margin: () => http.get('/market/margin'),
  hsgt: () => http.get('/market/hsgt'),

  sentiment: (date = '', force = false) => http.get('/sentiment', { params: { date, force } }),
  sentimentHistory: (days = 60) => http.get('/sentiment/history', { params: { days } }),

  limitPool: (kind = 'zt', date = '') => http.get('/limitup', { params: { kind, date } }),
  ladder: (date = '') => http.get('/limitup/ladder', { params: { date } }),

  sectors: (kind = 'industry', sort = 'pct', limit = 40) => http.get('/sectors', { params: { kind, sort, limit } }),
  mainline: () => http.get('/sectors/mainline'),
  sectorProbe: (kind = 'industry', pz = 3) => http.get('/sectors/probe', { params: { kind, pz } }),
  stockflow: (limit = 50) => http.get('/sectors/stockflow', { params: { limit } }),

  lhb: (date = '') => http.get('/lhb', { params: { date } }),
  lhbFocus: (date = '') => http.get('/lhb/focus', { params: { date } }),

  global: (force = false) => http.get('/global', { params: { force } }),

  // ---- 宏观水位：估值分位 / ERP / 国债 / 资金 / ETF 份额 / 温度分 ----
  macro: (force = false) => http.get('/macro/overview', { params: { force } }),
  macroHistory: (days = 250) => http.get('/macro/history', { params: { days } }),
  macroProbe: () => http.get('/macro/probe'),
  news: (p = {}) => http.get('/news', { params: Object.assign({ limit: 100 }, p) }),

  screener: (strategy = 'first_board', date = '') => http.get('/screener', { params: { strategy, date } }),
  strategies: () => http.get('/screener/strategies'),

  auction: (strategy = 'first_board', force = false) => http.get('/auction', { params: { strategy, force } }),

  report: (date = '', force = false) => http.get('/report', { params: { date, force } }),
  saveNote: (date, content) => http.post('/report/note', { date, content }),
  getNote: (date = '') => http.get('/report/note', { params: { date } }),

  watchlist: () => http.get('/watchlist'),
  addWatch: (code, name, tag) => http.post('/watchlist', { code, name, tag }),
  delWatch: (code) => http.delete('/watchlist/' + code),

  // ---- 研究：结果账本 / 对账 / 参数与制度 ----
  trackStatus: () => http.get('/track/status'),
  trackFreeze: (date = '') => http.post('/track/freeze', null, { params: { date } }),
  trackSettle: (date = '', strategy = '') => http.post('/track/settle', null, { params: { date, strategy } }),
  trackRecord: (strategy = 'first_board', horizon = 1, include_untradable = false) =>
    http.get('/track/record', { params: { strategy, horizon, include_untradable } }),
  trackMatrix: () => http.get('/track/matrix'),
  trackSignals: (date = '', strategy = '') => http.get('/track/signals', { params: { date, strategy } }),
  reconcile: (date = '') => http.get('/reconcile', { params: { date } }),
  researchParams: () => http.get('/research/params'),
  researchRegime: (date = '') => http.get('/research/regime', { params: { date } }),
  researchTrials: (limit = 200) => http.get('/research/trials', { params: { limit } }),

  sources: () => http.get('/settings/sources'),
  saveSources: (payload) => http.post('/settings/sources', payload),
  indicators: () => http.get('/meta/indicators'),
}

export default http