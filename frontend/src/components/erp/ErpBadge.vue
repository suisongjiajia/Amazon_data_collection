<script setup lang="ts">
import { getStatusMeta } from "../../utils/status";

const props = withDefaults(
  defineProps<{
    status: string;
    label?: string;
  }>(),
  {},
);

const meta = () => getStatusMeta(props.status);
</script>

<template>
  <span class="erp-badge" :data-tone="meta().tone">{{ label ?? meta().label }}</span>
</template>
