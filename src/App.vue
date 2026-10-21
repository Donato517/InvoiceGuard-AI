<!--
  @component App
  @description 根元件：依路由 meta.layout 套用對應版型，頁面內容由 RouterView 呈現。
-->
<script setup>
import { computed } from 'vue'
import { useRoute } from 'vue-router'

import BlankLayout from '@/layouts/BlankLayout.vue'
import DefaultLayout from '@/layouts/DefaultLayout.vue'

const LAYOUTS = { default: DefaultLayout, blank: BlankLayout }

const route = useRoute()

// 路由未指定 layout 時使用預設版型
const currentLayout = computed(() => LAYOUTS[route.meta.layout] ?? DefaultLayout)
</script>

<template>
  <component :is="currentLayout">
    <RouterView />
  </component>
</template>
