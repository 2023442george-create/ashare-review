<template>
  <section class="panel">
    <header class="panel-hd" v-if="title || $slots.extra">
      <h3>{{ title }}<span class="sub" v-if="sub">{{ sub }}</span></h3>
      <div class="row"><slot name="extra" /></div>
    </header>
    <div class="panel-bd" :class="{ tight, nopad }">
      <div v-if="loading" class="loading"><span class="spin"></span> 加载中…</div>
      <div v-else-if="error" class="err">{{ error }}</div>
      <div v-else-if="empty" class="empty">{{ emptyText }}</div>
      <slot v-else />
    </div>
  </section>
</template>

<script setup>
defineProps({
  title: String, sub: String, loading: Boolean, error: String,
  empty: Boolean, emptyText: { type: String, default: '暂无数据（可能是非交易时段或数据源不可用）' },
  tight: Boolean, nopad: Boolean,
})
</script>