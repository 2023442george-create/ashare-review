<template>
  <div ref="el" :style="{ height: typeof height === 'number' ? height + 'px' : height, width: '100%' }"></div>
</template>

<script setup>
import { onBeforeUnmount, onMounted, ref, watch, nextTick } from 'vue'
import * as echarts from 'echarts'

const props = defineProps({ option: Object, height: { default: 260 } })
const el = ref(null)
let chart = null

const BASE = {
  backgroundColor: 'transparent',
  textStyle: { color: '#8d9bb1', fontFamily: 'Consolas, PingFang SC, Microsoft YaHei, monospace', fontSize: 11 },
  grid: { left: 46, right: 16, top: 26, bottom: 26 },
  tooltip: {
    backgroundColor: 'rgba(15,20,32,.96)', borderColor: '#2e3a52', borderWidth: 1,
    textStyle: { color: '#e8eef7', fontSize: 11 }, axisPointer: { lineStyle: { color: '#2e3a52' } },
  },
}

function render() {
  if (!el.value) return
  if (!chart) chart = echarts.init(el.value, null, { renderer: 'canvas' })
  const opt = props.option
  if (!opt) return
  chart.setOption(Object.assign({}, BASE, opt), true)
}
const onResize = () => chart && chart.resize()

onMounted(async () => { await nextTick(); render(); window.addEventListener('resize', onResize) })
onBeforeUnmount(() => { window.removeEventListener('resize', onResize); chart && chart.dispose(); chart = null })
watch(() => props.option, () => render(), { deep: true })
</script>