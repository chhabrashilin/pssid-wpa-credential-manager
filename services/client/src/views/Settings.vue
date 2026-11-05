<script setup lang="ts">
import { onMounted, ref } from "vue";
import { api } from "../api";
import { useStore } from "../store";

const store = useStore();

interface Settings {
  rotation_warn_days: number; kek_version: number; sso_enabled: boolean;
  open_write: boolean; role_map: Record<string, string>; version: string;
}

const s = ref<Settings | null>(null);
const rotationDays = ref(180);

async function load() {
  s.value = await api.get<Settings>("/settings");
  rotationDays.value = s.value.rotation_warn_days;
}
onMounted(load);

async function save() {
  try {
    await api.put("/settings", { rotation_warn_days: Number(rotationDays.value) });
    store.toast("ok", "Settings saved");
    await load();
  } catch (e) { store.toast("err", (e as Error).message); }
}
</script>

<template>
  <h1>Settings</h1>
  <template v-if="s">
    <div class="card">
      <h2 style="margin-top:0">Rotation policy</h2>
      <label>Warn when a credential is older than (days)</label>
      <div class="row" style="max-width: 320px">
        <input type="number" v-model="rotationDays" :disabled="store.isReadOnly" />
        <button class="btn-primary" :disabled="store.isReadOnly" @click="save">Save</button>
      </div>
    </div>

    <div class="card">
      <h2 style="margin-top:0">Access control (read-only view)</h2>
      <p>SSO: <span class="badge" :class="s.sso_enabled ? 'badge-active' : 'badge-super'">{{ s.sso_enabled ? "enabled" : "disabled" }}</span>
        <span v-if="!s.sso_enabled"> · OPEN_WRITE: <span class="badge" :class="s.open_write ? 'badge-warn' : 'badge-super'">{{ s.open_write ? "true (writable lab mode)" : "false (read-only)" }}</span></span>
      </p>
      <label>Group → role mapping</label>
      <div class="table-wrap">
        <table>
          <thead><tr><th>OIDC group</th><th>Role</th></tr></thead>
          <tbody>
            <tr v-for="(role, group) in s.role_map" :key="group"><td class="mono">{{ group }}</td><td>{{ role }}</td></tr>
            <tr v-if="!Object.keys(s.role_map).length"><td colspan="2" class="muted">No mapping configured.</td></tr>
          </tbody>
        </table>
      </div>
    </div>

    <div class="card">
      <h2 style="margin-top:0">About</h2>
      <p>pSSID Credential Manager <span class="mono">v{{ s.version }}</span> · KEK version {{ s.kek_version }}</p>
      <p class="hint">Derived credential forms (psk hex, NT hash) are still network-equivalent secrets - the rendered file is never "safe to share". Rotation is the real mitigation.</p>
    </div>
  </template>
</template>
