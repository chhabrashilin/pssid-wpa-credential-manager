<script setup lang="ts">
import { onMounted, reactive, ref } from "vue";
import { api } from "../api";

interface Event { ts: string; actor: string; actor_type: string; action: string; object: string; meta: Record<string, unknown>; }

const events = ref<Event[]>([]);
const filters = reactive({ actor: "", action: "", object: "", from: "", to: "" });

function qs() {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(filters)) if (v) p.set(k, v);
  return p.toString();
}
async function load() { events.value = await api.get<Event[]>(`/audit?${qs()}`); }
onMounted(load);

function exportCsv() { window.open(`/api/v1/audit/export.csv?${qs()}`, "_blank"); }
</script>

<template>
  <h1>Audit log</h1>
  <p class="muted">Append-only record of every sensitive action. Read-only for everyone.</p>

  <div class="card">
    <div class="grid" style="grid-template-columns: repeat(auto-fill, minmax(150px, 1fr))">
      <div><label>Actor</label><input v-model="filters.actor" /></div>
      <div><label>Action</label><input v-model="filters.action" placeholder="credential.rotate" /></div>
      <div><label>Object</label><input v-model="filters.object" /></div>
      <div><label>From</label><input type="date" v-model="filters.from" /></div>
      <div><label>To</label><input type="date" v-model="filters.to" /></div>
    </div>
    <div class="row" style="gap:8px; margin-top:12px">
      <button class="btn-primary" @click="load">Filter</button>
      <button @click="exportCsv">Export CSV</button>
    </div>
  </div>

  <div class="card table-wrap">
    <table>
      <thead><tr><th>When</th><th>Actor</th><th>Type</th><th>Action</th><th>Object</th><th>Meta</th></tr></thead>
      <tbody>
        <tr v-for="(e, i) in events" :key="i">
          <td class="mono">{{ new Date(e.ts).toLocaleString() }}</td>
          <td>{{ e.actor }}</td>
          <td>{{ e.actor_type }}</td>
          <td class="mono">{{ e.action }}</td>
          <td>{{ e.object }}</td>
          <td class="mono muted" style="font-size:11px">{{ JSON.stringify(e.meta) }}</td>
        </tr>
        <tr v-if="!events.length"><td colspan="6" class="muted">No events.</td></tr>
      </tbody>
    </table>
  </div>
</template>
