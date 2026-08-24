<script setup lang="ts">
defineProps<{
  title: string;
  description?: string;
}>();
</script>

<template>
  <header class="erp-page-header">
    <div>
      <h2 class="erp-page-header__title">{{ title }}</h2>
      <p v-if="description" class="erp-page-header__desc">{{ description }}</p>
    </div>
    <div v-if="$slots.actions" class="erp-page-header__actions">
      <slot name="actions" />
    </div>
  </header>
</template>
