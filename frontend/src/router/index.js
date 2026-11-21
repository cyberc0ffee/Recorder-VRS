import { createRouter, createWebHistory } from "vue-router";

import AccountView from "../views/AccountView.vue";
import CamerasView from "../views/CamerasView.vue";
import DashboardView from "../views/DashboardView.vue";
import EventsView from "../views/EventsView.vue";
import RecordingsView from "../views/RecordingsView.vue";

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: "/", name: "dashboard", component: DashboardView },
    { path: "/cameras", name: "cameras", component: CamerasView },
    { path: "/recordings", name: "recordings", component: RecordingsView },
    { path: "/events", name: "events", component: EventsView },
    { path: "/account", name: "account", component: AccountView }
  ]
});

export default router;
