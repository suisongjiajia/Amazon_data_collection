<script setup lang="ts">
defineProps<{
  message?: string;
}>();
</script>

<template>
  <div class="erp-empty">
    <div class="erp-empty__icon">—</div>
    <p class="erp-empty__text">{{ message ?? "暂无数据" }}</p>
    <slot />
  </div>
</template>
