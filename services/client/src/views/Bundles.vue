<script setup lang="ts">
import { computed, onMounted, reactive, ref } from "vue";
import { api } from "../api";
import { useStore } from "../store";

const store = useStore();

interface Bundle { name: string; network_names: string[]; base_template_name?: string; render_version: number; }
interface NetView { name: string; }
interface RenderRow { version: number; fingerprint: string; rendered_by: string; rendered_at: string; }

const bundles = ref<Bundle[]>([]);
const nets = ref<NetView[]>([]);
const selected = ref<Bundle | null>(null);
const preview = ref("");
const renders = ref<RenderRow[]>([]);

async function load() {
  [bundles.value, nets.value] = await Promise.all([
    api.get<Bundle[]>("/bundles"),
    api.get<NetView[]>("/networks"),
  ]);
}
onMounted(load);

const baseUrl = computed(() => window.location.origin);
const pullUrl = computed(() => selected.value ? `${baseUrl.value}/api/v1/bundles/${selected.value.name}/render` : "");

async function select(b: Bundle) {
  selected.value = b;
  preview.value = "";
  renders.value = await api.get<RenderRow[]>(`/bundles/${b.name}/renders`);
}

// --- create/edit ---
const showForm = ref(false);
const editing = ref<string | null>(null);
const form = reactive({ name: "", network_names: [] as string[], base_template_name: "" });

function openCreate() {
  editing.value = null;
  Object.assign(form, { name: "", network_names: [], base_template_name: "" });
  showForm.value = true;
}
function openEdit(b: Bundle) {
  editing.value = b.name;
  Object.assign(form, { name: b.name, network_names: [...b.network_names], base_template_name: b.base_template_name ?? "" });
  showForm.value = true;
}
async function save() {
  const body: Record<string, unknown> = { name: form.name, network_names: form.network_names };
  if (form.base_template_name) body.base_template_name = form.base_template_name;
  try {
    if (editing.value) { const { name, ...patch } = body; await api.put(`/bundles/${editing.value}`, patch); }
    else await api.post("/bundles", body);
    store.toast("ok", "Bundle saved");
    showForm.value = false;
    await load();
  } catch (e) { store.toast("err", (e as Error).message); }
}
async function remove(b: Bundle) {
  if (!confirm(`Delete bundle '${b.name}'?`)) return;
  try { await api.del(`/bundles/${b.name}`); store.toast("ok", "Deleted"); selected.value = null; await load(); }
  catch (e) { store.toast("err", (e as Error).message); }
}

async function doPreview() {
  if (!selected.value) return;
  try { preview.value = await api.text(`/bundles/${selected.value.name}/preview`); }
  catch (e) { store.toast("err", (e as Error).message); }
}
async function doRender() {
  if (!selected.value) return;
  try {
    const r = await api.post<{ version: number; fingerprint: string }>(`/bundles/${selected.value.name}/render`);
    store.toast("ok", `Rendered v${r.version} (fp ${r.fingerprint})`);
    await select(selected.value);
    await load();
  } catch (e) { store.toast("err", (e as Error).message); }
}

const ansibleSnippet = computed(() => `- name: Pull wpa_supplicant.conf for this probe class
  ansible.builtin.get_url:
    url: "${pullUrl.value}"
    dest: /etc/wpa_supplicant/wpa_supplicant.conf
    headers:
      Authorization: "Bearer {{ credmgr_token }}"
    owner: root
    group: root
    mode: "0600"
  notify: restart wpa_supplicant`);

const curlSnippet = computed(() =>
  `curl -fsS -H "Authorization: Bearer $CREDMGR_TOKEN" \\\n  "${pullUrl.value}" -o /etc/wpa_supplicant/wpa_supplicant.conf`);

function copy(text: string) { navigator.clipboard.writeText(text); store.toast("ok", "Copied"); }
</script>

<template>
  <div class="spread">
    <div><h1>Bundles</h1><p class="muted">Sets of networks rendered into one wpa_supplicant.conf.</p></div>
    <button class="btn-primary" :disabled="store.isReadOnly" @click="openCreate">+ New bundle</button>
  </div>

  <div class="card table-wrap">
    <table>
      <thead><tr><th>Name</th><th>Networks</th><th>Base template</th><th>Render</th><th></th></tr></thead>
      <tbody>
        <tr v-for="b in bundles" :key="b.name">
          <td><strong>{{ b.name }}</strong></td>
          <td>{{ b.network_names.join(", ") || "—" }}</td>
          <td>{{ b.base_template_name || "—" }}</td>
          <td>v{{ b.render_version }}</td>
          <td class="row" style="justify-content:flex-end; gap:6px">
            <button class="btn-sm" @click="select(b)">Open</button>
            <button class="btn-sm" :disabled="store.isReadOnly" @click="openEdit(b)">Edit</button>
            <button class="btn-sm btn-danger" :disabled="store.isReadOnly" @click="remove(b)">Delete</button>
          </td>
        </tr>
      </tbody>
    </table>
  </div>

  <div v-if="selected" class="card">
    <div class="spread"><h2 style="margin-top:0">{{ selected.name }}</h2><button class="btn-sm" @click="selected = null">Close</button></div>
    <div class="row" style="gap: 8px">
      <button @click="doPreview">Preview (redacted)</button>
      <button class="btn-primary" :disabled="store.isReadOnly" @click="doRender">Render</button>
    </div>

    <pre v-if="preview" class="conf" style="margin-top: 12px">{{ preview }}</pre>

    <h2>Machine pull</h2>
    <label>Pull URL</label>
    <div class="row"><input :value="pullUrl" readonly /><button class="btn-sm" @click="copy(pullUrl)">Copy</button></div>
    <label>curl</label>
    <pre class="conf">{{ curlSnippet }}</pre>
    <label>Ansible task (installs 0600 root — placeholder token, never a real one)</label>
    <pre class="conf">{{ ansibleSnippet }}</pre>
    <button class="btn-sm" @click="copy(ansibleSnippet)">Copy Ansible task</button>

    <h2>Render history</h2>
    <div class="table-wrap">
      <table>
        <thead><tr><th>Version</th><th>Fingerprint</th><th>By</th><th>When</th></tr></thead>
        <tbody>
          <tr v-for="r in renders" :key="r.version">
            <td>v{{ r.version }}</td><td class="mono">{{ r.fingerprint }}</td>
            <td>{{ r.rendered_by }}</td><td class="mono">{{ new Date(r.rendered_at).toLocaleString() }}</td>
          </tr>
          <tr v-if="!renders.length"><td colspan="4" class="muted">Not rendered yet.</td></tr>
        </tbody>
      </table>
    </div>
  </div>

  <div v-if="showForm" class="modal-backdrop" @click.self="showForm = false">
    <div class="modal">
      <h2 style="margin-top:0">{{ editing ? "Edit" : "New" }} bundle</h2>
      <label>Name</label>
      <input v-model="form.name" :disabled="!!editing" placeholder="campus-probes" />
      <label>Networks (in priority order)</label>
      <div class="card" style="padding:10px; max-height: 220px; overflow:auto">
        <label v-for="n in nets" :key="n.name" class="row" style="font-weight:400; margin:4px 0">
          <input type="checkbox" style="width:auto" :value="n.name" v-model="form.network_names" /> {{ n.name }}
        </label>
      </div>
      <label>Base (global) template name — optional</label>
      <input v-model="form.base_template_name" placeholder="e.g. global-header" />
      <div class="row" style="justify-content:flex-end; margin-top:16px; gap:8px">
        <button @click="showForm = false">Cancel</button>
        <button class="btn-primary" @click="save">Save</button>
      </div>
    </div>
  </div>
</template>
