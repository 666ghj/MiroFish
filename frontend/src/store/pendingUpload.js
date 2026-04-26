/**
 * Temporary storage for files and simulation requirement.
 * - simulationRequirement: persisted to sessionStorage (survives refresh within the tab)
 * - files: in-memory only (File objects are not JSON-serializable)
 */
import { reactive } from 'vue'

const state = reactive({
  files: [],
  simulationRequirement: sessionStorage.getItem('pendingRequirement') || '',
  isPending: sessionStorage.getItem('pendingIsPending') === 'true',
  importOntologyMode: false,
  ontologyFile: null,
})

export function setPendingUpload(files, requirement, importOntologyMode = false, ontologyFile = null) {
  state.files = files
  state.simulationRequirement = requirement
  state.isPending = true
  state.importOntologyMode = importOntologyMode
  state.ontologyFile = ontologyFile
  sessionStorage.setItem('pendingRequirement', requirement)
  sessionStorage.setItem('pendingIsPending', 'true')
}

export function getPendingUpload() {
  return {
    files: state.files,
    simulationRequirement: state.simulationRequirement,
    isPending: state.isPending,
    importOntologyMode: state.importOntologyMode,
    ontologyFile: state.ontologyFile,
  }
}

export function clearPendingUpload() {
  state.files = []
  state.simulationRequirement = ''
  state.isPending = false
  state.importOntologyMode = false
  state.ontologyFile = null
  sessionStorage.removeItem('pendingRequirement')
  sessionStorage.removeItem('pendingIsPending')
}

export default state
