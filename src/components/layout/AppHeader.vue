<!--
  @component AppHeader
  @description 前台頁首：Logo 與主要導覽連結。
-->
<template>
  <header class="app-header">
    <nav class="app-header__nav container">
      <RouterLink :to="{ name: 'home' }" class="app-header__logo">InvoiceGuard AI</RouterLink>
      <RouterLink :to="{ name: 'invoice-list' }">我的發票</RouterLink>
      <RouterLink :to="{ name: 'invoice-upload' }">上傳發票</RouterLink>
    </nav>
  </header>
</template>

<style scoped>
.app-header {
  background-color: var(--color-bg);
  border-bottom: 1px solid var(--color-border);
}

.app-header__nav {
  display: flex;
  align-items: center;
  gap: var(--space-6);
  height: 64px;
}

.app-header__logo {
  margin-right: auto;
  font-size: var(--font-size-lg);
  font-weight: 700;
}
</style>
