import { createRouter, createWebHistory } from "vue-router";

const routes = [
  { path: "/", name: "dashboard", component: () => import("./views/Dashboard.vue") },
  { path: "/networks", name: "networks", component: () => import("./views/Networks.vue") },
  { path: "/templates", name: "templates", component: () => import("./views/Templates.vue") },
  { path: "/bundles", name: "bundles", component: () => import("./views/Bundles.vue") },
  { path: "/tokens", name: "tokens", component: () => import("./views/Tokens.vue") },
  { path: "/audit", name: "audit", component: () => import("./views/Audit.vue") },
  { path: "/settings", name: "settings", component: () => import("./views/Settings.vue") },
];

export const router = createRouter({
  history: createWebHistory(),
  routes,
});
