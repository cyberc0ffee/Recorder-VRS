<template>
  <span class="status-pill" :class="variant">
    <span class="status-dot"></span>
    {{ label }}
  </span>
</template>

<script setup>
defineProps({
  label: {
    type: String,
    required: true
  },
  variant: {
    type: String,
    default: "neutral"
  }
});
</script>

