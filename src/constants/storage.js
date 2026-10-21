/**
 * @file 瀏覽器儲存鍵名
 * @description 集中管理 localStorage / sessionStorage 的鍵名，避免字串散落各處。
 *   一律加上 ig_ 前綴，避免與同網域其他程式衝突。
 */
export const STORAGE_KEYS = Object.freeze({
  ACCESS_TOKEN: 'ig_access_token',
})
