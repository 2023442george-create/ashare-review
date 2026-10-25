<template><span class="mono" :class="c">{{ text }}</span></template>
<script setup>
import { computed } from 'vue'
import { cls as fn, pct } from '../format'
const p = defineProps({ v: [Number, String], d: { default: 2 }, suffix: { default: '%' }, raw: Boolean })
const c = computed(() => fn(p.v))
const text = computed(() => {
  if (p.v === null || p.v === undefined || p.v === '') return '—'
  if (p.raw) return (Number(p.v) > 0 ? '+' : '') + Number(p.v).toFixed(p.d) + p.suffix
  return pct(p.v, p.d)
})
</script>