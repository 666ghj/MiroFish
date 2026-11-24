import { createRouter, createWebHistory } from 'vue-router'
import Home from '../views/Home.vue'
import Process from '../views/MainView.vue'
import SimulationView from '../views/SimulationView.vue'
import SimulationRunView from '../views/SimulationRunView.vue'
import ReportView from '../views/ReportView.vue'
import InteractionView from '../views/InteractionView.vue'

const routes = [
  {
    path: '/',
    name: 'Home',
    component: Home
  },
  {
    path: '/simulate',
    name: 'Simulate',
    component: () => import('../views/SimulatePage.vue'),
  },
  {
    path: '/studio',
    name: 'IdeaStudio',
    component: () => import('../views/IdeaStudio.vue'),
  },
  {
    path: '/process/:projectId',
    name: 'Process',
    component: Process,
    props: true
  },
  {
    path: '/simulation/:simulationId',
    name: 'Simulation',
    component: SimulationView,
    props: true
  },
  {
    path: '/simulation/:simulationId/start',
    name: 'SimulationRun',
    component: SimulationRunView,
    props: true
  },
  {
    path: '/report/:reportId',
    name: 'Report',
    component: ReportView,
    props: true
  },
  {
    path: '/interaction/:reportId',
    name: 'Interaction',
    component: InteractionView,
    props: true
  },
  {
    path: '/gtm/personas/:briefId',
    name: 'GTMPersonas',
    component: () => import('../views/GTMPersonasView.vue'),
    props: true
  },
  {
    path: '/gtm/messages/:briefId',
    name: 'GTMMessages',
    component: () => import('../views/GTMMessageTestingView.vue'),
    props: true
  },
  {
    path: '/gtm/report/:briefId',
    name: 'GTMReport',
    component: () => import('../views/GTMReportView.vue'),
    props: true
  }
]

const router = createRouter({
  history: createWebHistory(),
  routes
})

export default router
