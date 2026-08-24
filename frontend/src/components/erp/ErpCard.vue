<script setup lang="ts">
defineProps<{
  title?: string;
  description?: string;
  padding?: "md" | "none";
}>();
</script>

<template>
  <section class="erp-card" :class="{ 'erp-card--flat': padding === 'none' }">
    <header v-if="title || $slots.actions" class="erp-card__header">
      <div>
        <h3 v-if="title" class="erp-card__title">{{ title }}</h3>
        <p v-if="description" class="erp-card__desc">{{ description }}</p>
      </div>
      <div v-if="$slots.actions" class="erp-card__actions">
        <slot name="actions" />
      </div>
    </header>
    <div class="erp-card__body">
      <slot />
    </div>
  </section>
</template>
