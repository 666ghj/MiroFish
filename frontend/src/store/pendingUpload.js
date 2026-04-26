/**
 * 临时存储待上传的文件和需求
 * 用于首页点击启动引擎后立即跳转，在Process页面再进行API调用
 */
import { reactive } from 'vue'

const state = reactive({
  files: [],
  simulationRequirement: '',
  isPending: false,
  importOntologyMode: false,
  ontologyFile: null
})

export function setPendingUpload(files, requirement, importOntologyMode = false, ontologyFile = null) {
  state.files = files
  state.simulationRequirement = requirement
  state.isPending = true
  state.importOntologyMode = importOntologyMode
  state.ontologyFile = ontologyFile
}

export function getPendingUpload() {
  return {
    files: state.files,
    simulationRequirement: state.simulationRequirement,
    isPending: state.isPending,
    importOntologyMode: state.importOntologyMode,
    ontologyFile: state.ontologyFile
  }
}

export function clearPendingUpload() {
  state.files = []
  state.simulationRequirement = ''
  state.isPending = false
  state.importOntologyMode = false
  state.ontologyFile = null
}

export default state
