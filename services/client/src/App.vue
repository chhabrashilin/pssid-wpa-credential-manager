<script setup lang="ts">
import { computed } from "vue";
import { useStore } from "./store";

const store = useStore();
const toggleTheme = () => store.setTheme(store.theme === "dark" ? "light" : "dark");
const roleLabel = computed(() => {
  if (!store.me) return "…";
  if (store.me.role === "write") return `write · ${store.me.actor}`;
  if (store.me.role === "read") return `read-only · ${store.me.actor}`;
  return "no access";
});
</script>

<template>
  <div class="layout">
    <aside class="sidebar">
      <div class="brand">
        pSSID CredMgr
        <small>wpa_supplicant secrets</small>
      </div>
      <nav class="nav">
        <RouterLink to="/">Dashboard</RouterLink>
        <RouterLink to="/networks">Networks</RouterLink>
        <RouterLink to="/templates">Templates</RouterLink>
        <RouterLink to="/bundles">Bundles</RouterLink>
        <RouterLink to="/tokens">Tokens</RouterLink>
        <RouterLink to="/audit">Audit</RouterLink>
        <RouterLink to="/settings">Settings</RouterLink>
      </nav>
    </aside>

    <main class="main">
      <div class="topbar">
        <div class="muted">Signed in: <strong>{{ roleLabel }}</strong></div>
        <button class="btn-sm" @click="toggleTheme">
          {{ store.theme === "dark" ? "☀ Light" : "🌙 Dark" }}
        </button>
      </div>

      <div v-if="store.isReadOnly" class="banner banner-warn">
        Read-only access — you can browse everything but cannot make changes, and
        secret values and token values are never shown.
      </div>

      <RouterView />
    </main>

    <div class="toasts">
      <div v-for="t in store.toasts" :key="t.id" class="toast" :class="t.kind">
        {{ t.text }}
      </div>
    </div>
  </div>
</template>
