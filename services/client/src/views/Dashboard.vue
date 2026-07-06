<script setup lang="ts">
import { onMounted, ref } from "vue";
import { api } from "../api";

interface Dash {
  counts: { networks: number; bundles: number; templates: number; tokens: number };
  rotation_warnings: { network_name: string; fingerprint: string; age_days: number }[];
  recent_audit: { ts: string; actor: string; action: string; object: string }[];
  health: { db: boolean; kek: boolean };
}

const d = ref<Dash | null>(null);
const err = ref("");

onMounted(async () => {
  try {
    d.value = await api.get<Dash>("/dashboard");
  } catch (e) {
    err.value = (e as Error).message;
  }
});
</script>

<template>
  <h1>Dashboard</h1>
  <p class="muted">Overview of the wireless credential registry.</p>
  <div v-if="err" class="banner banner-warn">{{ err }}</div>

  <template v-if="d">
    <div class="grid">
      <div class="stat"><div class="n">{{ d.counts.networks }}</div><div class="l">Networks</div></div>
      <div class="stat"><div class="n">{{ d.counts.bundles }}</div><div class="l">Bundles</div></div>
      <div class="stat"><div class="n">{{ d.counts.templates }}</div><div class="l">Templates</div></div>
      <div class="stat"><div class="n">{{ d.counts.tokens }}</div><div class="l">Active tokens</div></div>
    </div>

    <h2>Rotation warnings</h2>
    <div class="card">
      <p v-if="!d.rotation_warnings.length" class="muted">No credentials past the rotation threshold.</p>
      <ul v-else>
        <li v-for="w in d.rotation_warnings" :key="w.network_name">
          <strong>{{ w.network_name }}</strong> credential is {{ w.age_days }} days old
          <span class="mono muted">(fp {{ w.fingerprint }})</span>
        </li>
      </ul>
    </div>

    <h2>Health</h2>
    <div class="card row" style="gap: 20px">
      <span>Database: <span class="badge" :class="d.health.db ? 'badge-active' : 'badge-warn'">{{ d.health.db ? "up" : "down" }}</span></span>
      <span>Master key (KEK): <span class="badge" :class="d.health.kek ? 'badge-active' : 'badge-warn'">{{ d.health.kek ? "loaded" : "missing" }}</span></span>
    </div>

    <h2>Recent activity</h2>
    <div class="card table-wrap">
      <table>
        <thead><tr><th>When</th><th>Actor</th><th>Action</th><th>Object</th></tr></thead>
        <tbody>
          <tr v-for="(e, i) in d.recent_audit" :key="i">
            <td class="mono">{{ new Date(e.ts).toLocaleString() }}</td>
            <td>{{ e.actor }}</td>
            <td class="mono">{{ e.action }}</td>
            <td>{{ e.object }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </template>
</template>
