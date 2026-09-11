// 本地/CI 默认前端配置。部署时由 deploy/render-frontend-config.py 生成真正的 web/config.js。
window.ZOUSEEKING_API_BASE_URL = window.ZOUSEEKING_API_BASE_URL || "https://zouseeking-api-staging.onrender.com";
window.ZOUSEEKING_SUPABASE_URL = window.ZOUSEEKING_SUPABASE_URL || "";
window.ZOUSEEKING_SUPABASE_ANON_KEY = window.ZOUSEEKING_SUPABASE_ANON_KEY || "";
window.ZOUSEEKING_RELEASE_SCOPE = window.ZOUSEEKING_RELEASE_SCOPE || Object.freeze({
  phase: "consumer_intake_preview",
  businessOperations: false,
  adminOperations: false,
});
