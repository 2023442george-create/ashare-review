<template>
  <div class="stat" :class="{ hl }">
    <div class="k">
      {{ label }}
      <span v-if="help" class="help" :title="help">?</span>
      <slot name="badge" />
    </div>
    <div class="v mono" :class="colorClass" :style="colorStyle">{{ value }}</div>
    <div class="d" v-if="desc">{{ desc }}</div>
    <div class="bar" v-if="bar !== null" style="margin-top:6px">
      <i :style="{ width: Math.max(0, Math.min(100, bar)) + '%', background: barColor }"></i>
    </div>
    <slot />
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { cls as c } from '../format'

const p = defineProps({
  label: String, value: [String, Number], desc: String, help: String,
  hl: Boolean, bar: { default: null }, barColor: { type: String, default: '' },
  sign: { type: Boolean, default: false }, color: String,
})
const colorClass = computed(() => (p.color ? '' : p.sign ? c(String(p.value).replace(/[+%,]/g, '')) : ''))
const colorStyle = computed(() => (p.color ? { color: p.color } : {}))
</script>