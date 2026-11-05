<script setup lang="ts">
import { onMounted, reactive, ref } from "vue";
import { api } from "../api";
import { useStore } from "../store";

const store = useStore();

interface Token { id: string; name: string; scopes: string[]; expires_at: string; last_used_at: string | null; status: string; }
interface Bundle { name: string; }

const tokens = ref<Token[]>([]);
const bundles = ref<Bundle[]>([]);
const showForm = ref(false);
const form = reactive({ name: "", scopes: [] as string[], expires_in_days: 365 });
const createdValue = ref<string | null>(null);

async function load() {
  [tokens.value, bundles.value] = await Promise.all([
    api.get<Token[]>("/tokens"),
    api.get<Bundle[]>("/bundles"),
  ]);
}
onMounted(load);

async function create() {
  try {
    const r = await api.post<Token & { token: string }>("/tokens", {
      name: form.name, scopes: form.scopes, expires_in_days: Number(form.expires_in_days),
    });
    createdValue.value = r.token; // shown ONCE
    showForm.value = false;
    Object.assign(form, { name: "", scopes: [], expires_in_days: 365 });
    await load();
  } catch (e) { store.toast("err", (e as Error).message); }
}

async function revoke(t: Token) {
  if (!confirm(`Revoke token '${t.name}'? Machines using it will lose access immediately.`)) return;
  try { await api.del(`/tokens/${t.id}`); store.toast("ok", "Revoked"); await load(); }
  catch (e) { store.toast("err", (e as Error).message); }
}

function copy(v: string) { navigator.clipboard.writeText(v); store.toast("ok", "Copied"); }
</script>

<template>
  <div class="spread">
    <div><h1>Machine tokens</h1><p class="muted">Scoped, read-only, expiring tokens for provisioning to pull renders.</p></div>
    <button class="btn-primary" :disabled="store.isReadOnly" @click="showForm = true">+ New token</button>
  </div>

  <div v-if="createdValue" class="card">
    <strong>Token created - copy it now. It will never be shown again.</strong>
    <div class="token-value" style="margin-top:8px">{{ createdValue }}</div>
    <div class="row" style="margin-top:8px; gap:8px">
      <button class="btn-sm" @click="copy(createdValue!)">Copy</button>
      <button class="btn-sm" @click="createdValue = null">Done</button>
    </div>
  </div>

  <div class="card table-wrap">
    <table>
      <thead><tr><th>Name</th><th>Scopes</th><th>Status</th><th>Expires</th><th>Last used</th><th></th></tr></thead>
      <tbody>
        <tr v-for="t in tokens" :key="t.id">
          <td><strong>{{ t.name }}</strong><div class="muted mono" style="font-size:11px">{{ t.id }}</div></td>
          <td>{{ t.scopes.join(", ") }}</td>
          <td><span class="badge" :class="t.status === 'active' ? 'badge-active' : 'badge-super'">{{ t.status }}</span></td>
          <td class="mono">{{ new Date(t.expires_at).toLocaleDateString() }}</td>
          <td class="mono">{{ t.last_used_at ? new Date(t.last_used_at).toLocaleString() : "never" }}</td>
          <td style="text-align:right"><button class="btn-sm btn-danger" :disabled="store.isReadOnly || t.status !== 'active'" @click="revoke(t)">Revoke</button></td>
        </tr>
        <tr v-if="!tokens.length"><td colspan="6" class="muted">No tokens.</td></tr>
      </tbody>
    </table>
  </div>

  <div v-if="showForm" class="modal-backdrop" @click.self="showForm = false">
    <div class="modal">
      <h2 style="margin-top:0">New machine token</h2>
      <label>Name</label>
      <input v-model="form.name" placeholder="campus-probes-ansible" />
      <label>Bundle scopes</label>
      <div class="card" style="padding:10px; max-height:200px; overflow:auto">
        <label v-for="b in bundles" :key="b.name" class="row" style="font-weight:400; margin:4px 0">
          <input type="checkbox" style="width:auto" :value="b.name" v-model="form.scopes" /> {{ b.name }}
        </label>
        <p v-if="!bundles.length" class="muted">Create a bundle first.</p>
      </div>
      <label>Expires in (days)</label>
      <input type="number" v-model="form.expires_in_days" />
      <div class="row" style="justify-content:flex-end; margin-top:16px; gap:8px">
        <button @click="showForm = false">Cancel</button>
        <button class="btn-primary" :disabled="!form.name || !form.scopes.length" @click="create">Create</button>
      </div>
    </div>
  </div>
</template>
