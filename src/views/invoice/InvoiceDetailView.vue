<!--
  @component InvoiceDetailView
  @description 發票詳情：發票資料、明細、AI 風險分數與判斷理由。
  @route /invoices/:id （name: invoice-detail，需登入）
-->
<script setup>
defineProps({
  /** 發票 ID（由路由參數 :id 傳入） */
  id: { type: String, required: true },
})

// TODO(JerryChien): 以 fetchInvoice(id) 載入資料，金額 / 日期使用 utils/format.js 顯示
</script>

<template>
  <section class="invoice-detail-view">
    <h1>發票詳情 #{{ id }}</h1>
  </section>
</template>
