<!--
  @component LoginView
  @description 登入頁：帳號密碼登入，成功後導回 query.redirect 指定的頁面（預設首頁）。
  @route /login （name: login，layout: blank）
-->
<script setup>
// TODO(JerryChien): 表單驗證 → 呼叫 api/modules/auth.js login() → userStore.setToken() → 導頁
</script>

<template>
  <section class="login-view">
    <h1>登入</h1>
  </section>
</template>

<style scoped>
.login-view {
  width: 100%;
  max-width: 400px;
}
</style>
