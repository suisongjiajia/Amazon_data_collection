<script setup lang="ts">
withDefaults(
  defineProps<{
    variant?: "primary" | "secondary" | "ghost" | "danger";
    size?: "sm" | "md";
    disabled?: boolean;
  }>(),
  {
    variant: "primary",
    size: "md",
    disabled: false,
  },
);
</script>

<template>
  <button
    type="button"
    class="erp-btn"
    :class="[`erp-btn--${variant}`, `erp-btn--${size}`]"
    :disabled="disabled"
  >
    <slot />
  </button>
</template>
