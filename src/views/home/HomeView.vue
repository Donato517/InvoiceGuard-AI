<!--
  @component HomeView
  @description 前台首頁：產品介紹與「上傳發票」入口。
  @route / （name: home）
-->
<template>
  <section class="home-view">
    <h1>InvoiceGuard AI</h1>
    <p>上傳發票，AI 協助檢查風險。</p>
    <RouterLink :to="{ name: 'invoice-upload' }">開始上傳</RouterLink>
  </section>
</template>

<style scoped>
.home-view {
  display: grid;
  gap: var(--space-4);
}
</style>
