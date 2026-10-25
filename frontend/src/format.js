// 数字/时间格式化：A股口径（红涨绿跌、亿/万单位）
export const nz = v => (v === null || v === undefined || v === '' || Number.isNaN(Number(v)) ? null : Number(v))

export function num(v, d = 2) {
  const n = nz(v)
  if (n === null) return '—'
  return n.toLocaleString('zh-CN', { minimumFractionDigits: d, maximumFractionDigits: d })
}
export function yi(v, d = 2) {
  const n = nz(v)
  if (n === null) return '—'
  return (n / 1e8).toLocaleString('zh-CN', { minimumFractionDigits: d, maximumFractionDigits: d })
}
export function money(v, d = 2) {
  const n = nz(v)
  if (n === null) return '—'
  const a = Math.abs(n)
  if (a >= 1e8) return (n / 1e8).toFixed(d) + '亿'
  if (a >= 1e4) return (n / 1e4).toFixed(d) + '万'
  return n.toFixed(0)
}
export function pct(v, d = 2, sign = true) {
  const n = nz(v)
  if (n === null) return '—'
  return (sign && n > 0 ? '+' : '') + n.toFixed(d) + '%'
}
export function signed(v, d = 2) {
  const n = nz(v)
  if (n === null) return '—'
  return (n > 0 ? '+' : '') + n.toFixed(d)
}
export function cls(v) {
  const n = nz(v)
  if (n === null || n === 0) return 'flat'
  return n > 0 ? 'up' : 'down'
}
export function hhmmss(v) {
  if (!v) return '—'
  const s = String(v).replace(/\D/g, '')
  if (s.length === 6) return s.slice(0, 2) + ':' + s.slice(2, 4) + ':' + s.slice(4)
  return String(v)
}
export function shortTime(t) {
  if (!t) return ''
  const s = String(t)
  return s.length > 11 ? s.slice(5, 16) : s
}
export function scoreColor(s) {
  if (s >= 85) return '#ff3b3b'
  if (s >= 70) return '#ff7a45'
  if (s >= 55) return '#ffb020'
  if (s >= 40) return '#a0a8b8'
  if (s >= 25) return '#4c9aff'
  return '#36cfc9'
}
export function phaseColor(p) {
  return { 冰点: '#36cfc9', 修复: '#4c9aff', 发酵: '#ff7a45', 分歧: '#a0a8b8', 高潮: '#ff3b3b', 退潮: '#7c5cff' }[p] || '#8d9bb1'
}
export function download(filename, text) {
  const blob = new Blob([text], { type: 'text/markdown;charset=utf-8' })
  const a = document.createElement('a')
  a.href = URL.createObjectURL(blob)
  a.download = filename
  a.click()
  URL.revokeObjectURL(a.href)
}
// 极简 markdown 渲染（表格/标题/列表/引用/加粗），避免引入额外依赖
export function md2html(md) {
  if (!md) return ''
  const esc = s => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
  const lines = esc(md).split('\n')
  let html = '', inTable = false, inList = false
  const inline = s => s.replace(/\*\*(.+?)\*\*/g, '<b>$1</b>').replace(/\*(.+?)\*/g, '<i>$1</i>')
  for (const raw of lines) {
    const line = raw.trimEnd()
    if (/^\|.*\|$/.test(line)) {
      const cells = line.slice(1, -1).split('|').map(c => c.trim())
      if (/^[-: ]+$/.test(cells.join(''))) continue
      if (!inTable) { html += '<table>'; inTable = true }
      const tag = cells[0] && /^-+$/.test(cells[0]) ? 'td' : 'td'
      html += '<tr>' + cells.map(c => '<' + tag + '>' + inline(c) + '</' + tag + '>').join('') + '</tr>'
      continue
    }
    if (inTable) { html += '</table>'; inTable = false }
    if (/^#{1,4} /.test(line)) {
      const lv = line.match(/^#+/)[0].length
      if (inList) { html += '</ul>'; inList = false }
      html += '<h' + lv + '>' + inline(line.replace(/^#+ /, '')) + '</h' + lv + '>'
    } else if (/^> /.test(line)) {
      html += '<blockquote>' + inline(line.slice(2)) + '</blockquote>'
    } else if (/^[-*] /.test(line)) {
      if (!inList) { html += '<ul>'; inList = true }
      html += '<li>' + inline(line.slice(2)) + '</li>'
    } else if (/^---+$/.test(line)) {
      html += '<hr style="border:none;border-top:1px solid #232d40;margin:14px 0">'
    } else if (line === '') {
      if (inList) { html += '</ul>'; inList = false }
    } else {
      if (inList) { html += '</ul>'; inList = false }
      html += '<p style="margin:4px 0">' + inline(line) + '</p>'
    }
  }
  if (inTable) html += '</table>'
  if (inList) html += '</ul>'
  return html
}