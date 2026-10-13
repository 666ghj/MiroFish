<template>
  <div class="report-download">
    <button type="button" :disabled="disabled || downloading || !reportId" :aria-busy="downloading" @click="download">
      <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.7" aria-hidden="true">
        <path d="M12 3v12m-5-5 5 5 5-5M4 16v5h16v-5" />
      </svg>
      {{ $t(downloading ? 'reportExport.preparing' : 'reportExport.downloadPdf') }}
    </button>
    <RecoveryBanner :error="downloadError" :retry-key="`pdf:${reportId}`" :busy="downloading" :completed="downloaded"
      :auto-retry="!!reportId && !disabled" :label="$t('reportExport.retry')" @retry="download" />
  </div>
</template>
<script setup>
import { ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { downloadReportPdf } from '../api/report'
import { savePdfBlob } from '../utils/download'
import RecoveryBanner from './RecoveryBanner.vue'

const props = defineProps({ reportId: String, disabled: Boolean })
const { t } = useI18n()
const downloading = ref(false)
const downloadError = ref('')
const downloaded = ref(false)
watch(() => props.reportId, () => { downloadError.value = ''; downloaded.value = false })
const download = async () => {
  if (downloading.value || props.disabled || !props.reportId) return
  const id = props.reportId
  downloading.value = true
  downloadError.value = ''
  downloaded.value = false
  try {
    const blob = await downloadReportPdf(id)
    savePdfBlob(blob, `${id}.pdf`)
    downloaded.value = true
  } catch (error) {
    downloadError.value = error.message || t('reportExport.failed')
  } finally { downloading.value = false }
}
</script>
<style scoped>
.report-download { margin: 18px 0 8px; }
button { display: inline-flex; align-items: center; gap: 8px; padding: 10px 15px; border: 1px solid #263b45; border-radius: 6px; background: #263b45; color: white; font: inherit; font-size: 13px; cursor: pointer; }
button:hover { background: #385561; }
button:focus-visible { outline: 3px solid #85b4c0; outline-offset: 3px; }
button:disabled { opacity: .5; cursor: default; }
</style>
