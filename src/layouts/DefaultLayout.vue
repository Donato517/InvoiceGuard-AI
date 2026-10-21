<!--
  @component DefaultLayout
  @description 前台預設版型：頁首 + 內容 + 頁尾。路由未指定 meta.layout 時使用。
  @slot default - 頁面內容
-->
<script setup>
import AppFooter from '@/components/layout/AppFooter.vue'
import AppHeader from '@/components/layout/AppHeader.vue'
</script>

<template>
  <div class="default-layout">
    <AppHeader />
    <main class="default-layout__main container">
      <slot />
    </main>
    <AppFooter />
  </div>
</template>

<style scoped>
.default-layout {
  display: flex;
  flex-direction: column;
  min-height: 100vh;
}

.default-layout__main {
  flex: 1;
  padding-block: var(--space-6);
}
</style>
