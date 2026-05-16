import { createRouter, createWebHistory } from 'vue-router'
import Home from '../views/Home.vue'
import Process from '../views/MainView.vue'
import SimulationView from '../views/SimulationView.vue'
import SimulationRunView from '../views/SimulationRunView.vue'
import ReportView from '../views/ReportView.vue'
import InteractionView from '../views/InteractionView.vue'
import LoginView from '../views/LoginView.vue'
import ForgotPasswordView from '../views/ForgotPasswordView.vue'
import ResetPasswordView from '../views/ResetPasswordView.vue'
import SetPasswordView from '../views/SetPasswordView.vue'
import AdminView from '../views/AdminView.vue'
import authState, { isAdmin } from '../store/auth'

const routes = [
  // Públiques
  { path: '/login',                 name: 'Login',          component: LoginView,          meta: { public: true } },
  { path: '/forgot-password',       name: 'ForgotPassword', component: ForgotPasswordView, meta: { public: true } },
  { path: '/reset-password/:token', name: 'ResetPassword',  component: ResetPasswordView,  meta: { public: true }, props: true },
  { path: '/accept-invite/:token',  name: 'AcceptInvite',   component: SetPasswordView,    meta: { public: true }, props: true },

  // Privades
  { path: '/',                               name: 'Home',          component: Home },
  { path: '/process/:projectId',             name: 'Process',       component: Process,          props: true },
  { path: '/simulation/:simulationId',       name: 'Simulation',    component: SimulationView,   props: true },
  { path: '/simulation/:simulationId/start', name: 'SimulationRun', component: SimulationRunView, props: true },
  { path: '/report/:reportId',               name: 'Report',        component: ReportView,       props: true },
  { path: '/interaction/:reportId',          name: 'Interaction',   component: InteractionView,  props: true },

  // Admin only
  { path: '/admin',      redirect: '/admin/users' },
  { path: '/admin/:tab', name: 'Admin', component: AdminView, props: true, meta: { requiresAdmin: true } },
]

const router = createRouter({ history: createWebHistory(), routes })

router.beforeEach((to, from, next) => {
  if (to.meta?.public) return next()
  if (!authState.isAuthenticated) return next({ name: 'Login', query: { redirect: to.fullPath } })
  if (to.meta?.requiresAdmin && !isAdmin.value) return next({ name: 'Home' })
  if (to.name === 'Login') return next({ name: 'Home' })
  next()
})

export default router
