<script setup lang="ts">
import { onMounted, ref } from "vue";
import { api } from "../api";
import { useStore } from "../store";

const store = useStore();

interface TemplateRow { name: string; latest_version: number; active_version: number | null; versions: number; }
interface TemplateDoc { name: string; version: number; body: string; status: string; }
interface Validation { ok: boolean; errors: string[]; warnings: string[]; }

const CONTRACT_VARS = [
  "ssid", "name", "security", "priority", "scan_ssid",
  "psk_hex", "identity", "password_nthash", "ca_cert", "client_cert", "private_key",
];
// Build the literal "{{ var }}" text in script - writing it inline in the
// template would confuse Vue's mustache parser.
const varTag = (v: string) => `{{ ${v} }}`;

const rows = ref<TemplateRow[]>([]);
const editor = ref<{ name: string; body: string; version: number | null } | null>(null);
const validation = ref<Validation | null>(null);
const creatingNew = ref(false);

async function load() { rows.value = await api.get<TemplateRow[]>("/templates"); }
onMounted(load);

async function edit(name: string) {
  const doc = await api.get<TemplateDoc>(`/templates/${name}`);
  editor.value = { name: doc.name, body: doc.body, version: doc.version };
  validation.value = null;
  creatingNew.value = false;
}
function newTemplate() {
  editor.value = { name: "", body: "network={\n    ssid=\"{{ ssid }}\"\n    scan_ssid={{ scan_ssid }}\n    priority={{ priority }}\n}\n", version: null };
  validation.value = null;
  creatingNew.value = true;
}

async function validate() {
  if (!editor.value) return;
  try {
    validation.value = await api.post<Validation>(`/templates/${editor.value.name || "draft"}/validate`, { body: editor.value.body });
  } catch (e) {
    validation.value = { ok: false, errors: [(e as Error).message], warnings: [] };
  }
}

async function saveDraft() {
  if (!editor.value) return;
  try {
    await api.post("/templates", { name: editor.value.name, body: editor.value.body });
    store.toast("ok", "Draft saved as new version");
    await load();
    await edit(editor.value.name);
  } catch (e) {
    store.toast("err", (e as Error).message);
  }
}

async function activate() {
  if (!editor.value) return;
  try {
    await api.post(`/templates/${editor.value.name}/activate`, { version: editor.value.version });
    store.toast("ok", "Template activated");
    await load();
  } catch (e) {
    store.toast("err", (e as Error).message);
  }
}
</script>

<template>
  <div class="spread">
    <div><h1>Templates</h1><p class="muted">Jinja templates rendered in a sandbox into wpa_supplicant blocks.</p></div>
    <button class="btn-primary" :disabled="store.isReadOnly" @click="newTemplate">+ New template</button>
  </div>

  <div class="card table-wrap">
    <table>
      <thead><tr><th>Name</th><th>Active</th><th>Latest</th><th>Versions</th><th></th></tr></thead>
      <tbody>
        <tr v-for="t in rows" :key="t.name">
          <td><strong>{{ t.name }}</strong></td>
          <td><span v-if="t.active_version" class="badge badge-active">v{{ t.active_version }}</span><span v-else class="muted">-</span></td>
          <td>v{{ t.latest_version }}</td>
          <td>{{ t.versions }}</td>
          <td style="text-align:right"><button class="btn-sm" @click="edit(t.name)">Open</button></td>
        </tr>
      </tbody>
    </table>
  </div>

  <div v-if="editor" class="card">
    <div class="spread">
      <h2 style="margin-top:0">{{ creatingNew ? "New template" : `Editing ${editor.name}` }}
        <span v-if="editor.version" class="muted">v{{ editor.version }}</span>
      </h2>
      <button class="btn-sm" @click="editor = null">Close</button>
    </div>

    <div class="row" style="align-items: flex-start; gap: 16px">
      <div style="flex: 3">
        <label v-if="creatingNew">Name</label>
        <input v-if="creatingNew" v-model="editor.name" placeholder="peap-mschapv2" />
        <label>Template body</label>
        <textarea v-model="editor.body" class="code" :readonly="store.isReadOnly"></textarea>
        <div class="row" style="gap: 8px; margin-top: 10px">
          <button @click="validate">Validate</button>
          <button class="btn-primary" :disabled="store.isReadOnly" @click="saveDraft">Save draft</button>
          <button :disabled="store.isReadOnly || creatingNew" @click="activate">Activate</button>
        </div>

        <div v-if="validation" style="margin-top: 12px">
          <div class="banner" :class="validation.ok ? 'banner-warn' : 'banner-warn'"
               :style="{ background: validation.ok ? 'color-mix(in srgb, var(--ok) 15%, transparent)' : '' }">
            {{ validation.ok ? "✓ Valid wpa_supplicant output" : "✗ Validation failed" }}
          </div>
          <ul v-if="validation.errors.length"><li v-for="(e,i) in validation.errors" :key="i" class="err-hint">{{ e }}</li></ul>
          <ul v-if="validation.warnings.length"><li v-for="(w,i) in validation.warnings" :key="i" class="hint">⚠ {{ w }}</li></ul>
        </div>
      </div>

      <div style="flex: 1">
        <label>Contract variables</label>
        <div class="card" style="padding: 10px">
          <div v-for="v in CONTRACT_VARS" :key="v" class="mono" style="font-size: 12px">{{ varTag(v) }}</div>
          <p class="hint">Secrets appear only in derived form (<span class="mono">psk_hex</span>, <span class="mono">password_nthash</span>) - never raw.</p>
        </div>
      </div>
    </div>
  </div>
</template>
