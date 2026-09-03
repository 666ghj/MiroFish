import { createRouter, createWebHistory } from 'vue-router'
import Home from '../views/Home.vue'
import Process from '../views/MainView.vue'
import SimulationView from '../views/SimulationView.vue'
import SimulationRunView from '../views/SimulationRunView.vue'
import ReportView from '../views/ReportView.vue'
import InteractionView from '../views/InteractionView.vue'
import StoryTimelineView from '../views/StoryTimelineView.vue'
import GodModeView from '../views/GodModeView.vue'
import WorldBuilderView from '../views/WorldBuilderView.vue'

const routes = [
  {
    path: '/',
    name: 'Home',
    component: Home
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
    path: '/story/:simulationId',
    name: 'Story',
    component: StoryTimelineView,
    props: true
  },
  {
    path: '/godmode/:simulationId',
    name: 'GodMode',
    component: GodModeView,
    props: true
  },
  {
    path: '/world/:simulationId',
    name: 'World',
    component: WorldBuilderView,
    props: true
  }
]

const router = createRouter({
  history: createWebHistory(),
  routes
})

export default router
