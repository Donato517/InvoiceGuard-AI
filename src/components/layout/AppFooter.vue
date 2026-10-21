<!--
  @component AppFooter
  @description 前台頁尾：版權資訊。
-->
<script setup>
const currentYear = new Date().getFullYear()
</script>

<template>
  <footer class="app-footer">
    <div class="container">© {{ currentYear }} InvoiceGuard AI</div>
  </footer>
</template>

<style scoped>
.app-footer {
  padding-block: var(--space-4);
  font-size: var(--font-size-sm);
  color: var(--color-text-muted);
  border-top: 1px solid var(--color-border);
}
</style>
