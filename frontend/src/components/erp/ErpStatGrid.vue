<script setup lang="ts">
export interface ErpStatItem {
  label: string;
  value: string | number;
  hint?: string;
}

defineProps<{
  items: ErpStatItem[];
}>();
</script>

<template>
  <div class="erp-stat-grid">
    <article v-for="item in items" :key="item.label" class="erp-stat-card">
      <span class="erp-stat-card__label">{{ item.label }}</span>
      <strong class="erp-stat-card__value">{{ item.value }}</strong>
      <small v-if="item.hint" class="erp-stat-card__hint">{{ item.hint }}</small>
    </article>
  </div>
</template>
