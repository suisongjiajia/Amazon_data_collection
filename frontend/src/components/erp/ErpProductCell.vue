<script setup lang="ts">
defineProps<{
  imageUrl?: string | null;
  title?: string | null;
  subtitle?: string | null;
  size?: "md" | "lg";
}>();
</script>

<template>
  <div class="erp-product" :class="`erp-product--${size ?? 'md'}`">
    <div class="erp-product__thumb" :class="{ 'is-placeholder': !imageUrl }">
      <img v-if="imageUrl" :src="imageUrl" :alt="title || '商品'" />
      <span v-else>无图</span>
    </div>
    <div class="erp-product__copy">
      <strong class="erp-product__title">{{ title || "未命名" }}</strong>
      <span v-if="subtitle" class="erp-product__subtitle">{{ subtitle }}</span>
    </div>
  </div>
</template>
