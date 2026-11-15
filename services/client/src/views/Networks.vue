<script setup lang="ts">
import { computed, onMounted, reactive, ref } from "vue";
import { api } from "../api";
import { useStore } from "../store";

const store = useStore();

interface NetView {
  name: string; ssid: string; security: string; priority: number; scan_ssid: number;
  notes: string; template_name: string; template_version: number | null;
  variables: Record<string, string>;
  credential: { fingerprint: string; version: number; created_at: string } | null;
}
interface TemplateRow { name: string; active_version: number | null; }

const nets = ref<NetView[]>([]);
const templates = ref<TemplateRow[]>([]);
const loading = ref(true);

async function load() {
  loading.value = true;
  [nets.value, templates.value] = await Promise.all([
    api.get<NetView[]>("/networks"),
    api.get<TemplateRow[]>("/templates"),
  ]);
  loading.value = false;
}
onMounted(load);

const ageDays = (iso: string) => Math.floor((Date.now() - new Date(iso).getTime()) / 86400000);

// --- Network create/edit modal ---
const showForm = ref(false);
const editing = ref<string | null>(null);
const form = reactive({
  name: "", ssid: "", security: "wpa-psk", priority: 0, scan_ssid: 0,
  notes: "", template_name: "", variablesText: "",
});

function openCreate() {
  editing.value = null;
  Object.assign(form, { name: "", ssid: "", security: "wpa-psk", priority: 0, scan_ssid: 0, notes: "", template_name: templates.value[0]?.name ?? "", variablesText: "" });
  showForm.value = true;
}
function openEdit(n: NetView) {
  editing.value = n.name;
  Object.assign(form, {
    name: n.name, ssid: n.ssid, security: n.security, priority: n.priority,
    scan_ssid: n.scan_ssid, notes: n.notes, template_name: n.template_name,
    variablesText: Object.entries(n.variables).map(([k, v]) => `${k}=${v}`).join("\n"),
  });
  showForm.value = true;
}

function parseVars(text: string): Record<string, string> {
  const out: Record<string, string> = {};
  for (const line of text.split("\n")) {
    const t = line.trim();
    if (!t) continue;
    const i = t.indexOf("=");
    if (i > 0) out[t.slice(0, i).trim()] = t.slice(i + 1).trim();
  }
  return out;
}

async function saveNetwork() {
  const body = {
    name: form.name, ssid: form.ssid, security: form.security,
    priority: Number(form.priority), scan_ssid: Number(form.scan_ssid) as 0 | 1,
    notes: form.notes, template_name: form.template_name, variables: parseVars(form.variablesText),
  };
  try {
    if (editing.value) {
      const { name, ...patch } = body;
      await api.put(`/networks/${editing.value}`, patch);
    } else {
      await api.post("/networks", body);
    }
    store.toast("ok", "Network saved");
    showForm.value = false;
    await load();
  } catch (e) {
    store.toast("err", (e as Error).message);
  }
}

async function removeNetwork(n: NetView) {
  if (!confirm(`Delete network '${n.name}'? This also deletes its stored credentials.`)) return;
  try {
    await api.del(`/networks/${n.name}`);
    store.toast("ok", "Network deleted");
    await load();
  } catch (e) {
    store.toast("err", (e as Error).message);
  }
}

// --- Credential modal (write-only) ---
const showCred = ref(false);
const credNet = ref<NetView | null>(null);
const cred = reactive({ passphrase: "", confirm: "", identity: "", password: "", client_cert: "", private_key: "", ca_cert: "" });
const credType = computed(() => credNet.value?.security ?? "");

function openCred(n: NetView) {
  credNet.value = n;
  Object.assign(cred, { passphrase: "", confirm: "", identity: "", password: "", client_cert: "", private_key: "", ca_cert: "" });
  showCred.value = true;
}

const credMismatch = computed(() =>
  credType.value === "wpa-psk" ? cred.passphrase !== cred.confirm :
  credType.value === "wpa-eap-peap-mschapv2" ? false : false,
);

async function saveCred() {
  if (!credNet.value) return;
  let body: Record<string, string> = {};
  if (credType.value === "wpa-psk") body = { passphrase: cred.passphrase };
  else if (credType.value === "wpa-eap-peap-mschapv2") body = { identity: cred.identity, password: cred.password };
  else if (credType.value === "eap-tls") body = { client_cert: cred.client_cert, private_key: cred.private_key, ca_cert: cred.ca_cert };
  try {
    const r = await api.put<{ version: number; fingerprint: string }>(`/networks/${credNet.value.name}/credential`, body);
    store.toast("ok", `Credential saved - v${r.version}, fp ${r.fingerprint}`);
    showCred.value = false;
    await load();
  } catch (e) {
    store.toast("err", (e as Error).message);
  }
}
</script>

<template>
  <div class="spread">
    <div><h1>Networks</h1><p class="muted">Wireless networks and their write-only credentials.</p></div>
    <button class="btn-primary" :disabled="store.isReadOnly" @click="openCreate">+ Add network</button>
  </div>

  <div class="card table-wrap">
    <table>
      <thead><tr>
        <th>Name</th><th>SSID</th><th>Type</th><th>Credential</th><th>Template</th><th></th>
      </tr></thead>
      <tbody>
        <tr v-for="n in nets" :key="n.name">
          <td><strong>{{ n.name }}</strong><div class="muted mono">prio {{ n.priority }} · scan {{ n.scan_ssid }}</div></td>
          <td>{{ n.ssid }}</td>
          <td class="mono">{{ n.security }}</td>
          <td>
            <template v-if="n.credential">
              <span class="badge badge-active">v{{ n.credential.version }}</span>
              <span class="mono muted"> fp {{ n.credential.fingerprint }}</span>
              <div class="muted" :class="{ 'badge-warn': ageDays(n.credential.created_at) > 180 }">
                {{ ageDays(n.credential.created_at) }}d old
              </div>
            </template>
            <span v-else-if="n.security === 'open'" class="muted">none (open)</span>
            <span v-else class="badge badge-warn">not set</span>
          </td>
          <td>{{ n.template_name }} <span class="muted">v{{ n.template_version ?? "-" }}</span></td>
          <td class="row" style="gap: 6px; justify-content: flex-end">
            <button class="btn-sm" :disabled="store.isReadOnly || n.security === 'open'" @click="openCred(n)">
              {{ n.credential ? "Rotate" : "Set credential" }}
            </button>
            <button class="btn-sm" :disabled="store.isReadOnly" @click="openEdit(n)">Edit</button>
            <button class="btn-sm btn-danger" :disabled="store.isReadOnly" @click="removeNetwork(n)">Delete</button>
          </td>
        </tr>
        <tr v-if="!loading && !nets.length"><td colspan="6" class="muted">No networks yet.</td></tr>
      </tbody>
    </table>
  </div>

  <!-- Network form modal -->
  <div v-if="showForm" class="modal-backdrop" @click.self="showForm = false">
    <div class="modal">
      <h2 style="margin-top:0">{{ editing ? "Edit" : "Add" }} network</h2>
      <label>Name (unique)</label>
      <input v-model="form.name" :disabled="!!editing" placeholder="mwireless" />
      <label>SSID</label>
      <input v-model="form.ssid" placeholder="MWireless" />
      <label>Security type</label>
      <select v-model="form.security" :disabled="!!editing">
        <option value="wpa-psk">WPA-PSK (personal)</option>
        <option value="wpa-eap-peap-mschapv2">WPA-EAP PEAP/MSCHAPv2</option>
        <option value="eap-tls">EAP-TLS</option>
        <option value="open">Open</option>
      </select>
      <div class="row" style="gap: 16px">
        <div style="flex:1"><label>Priority</label><input type="number" v-model="form.priority" /></div>
        <div style="flex:1"><label>Hidden (scan_ssid)</label>
          <select v-model="form.scan_ssid"><option :value="0">0 - broadcast</option><option :value="1">1 - hidden</option></select>
        </div>
      </div>
      <label>Template</label>
      <select v-model="form.template_name">
        <option v-for="t in templates" :key="t.name" :value="t.name">{{ t.name }}</option>
      </select>
      <label>Extra template variables (non-secret, key=value per line)</label>
      <textarea v-model="form.variablesText" rows="3" class="code" placeholder="ca_cert=/etc/ssl/certs/umich.pem"></textarea>
      <label>Notes</label>
      <input v-model="form.notes" />
      <div class="row" style="justify-content: flex-end; margin-top: 16px; gap: 8px">
        <button @click="showForm = false">Cancel</button>
        <button class="btn-primary" @click="saveNetwork">Save</button>
      </div>
    </div>
  </div>

  <!-- Credential modal (write-only) -->
  <div v-if="showCred" class="modal-backdrop" @click.self="showCred = false">
    <div class="modal">
      <h2 style="margin-top:0">Set credential · {{ credNet?.name }}</h2>
      <p class="hint">Secrets are write-only. After saving you will see only a fingerprint - never the value.</p>

      <template v-if="credType === 'wpa-psk'">
        <label>Passphrase (8–63 chars, or 64-hex raw PSK)</label>
        <input type="password" v-model="cred.passphrase" />
        <label>Confirm passphrase</label>
        <input type="password" v-model="cred.confirm" />
        <div v-if="credMismatch" class="err-hint">Passphrases do not match.</div>
      </template>

      <template v-else-if="credType === 'wpa-eap-peap-mschapv2'">
        <label>Identity</label>
        <input v-model="cred.identity" placeholder="pssid-probe" />
        <label>Password</label>
        <input type="password" v-model="cred.password" />
        <p class="hint">Stored encrypted; rendered as <span class="mono">password=hash:&lt;NT hash&gt;</span> - never clear text.</p>
      </template>

      <template v-else-if="credType === 'eap-tls'">
        <label>Client certificate (PEM)</label>
        <textarea v-model="cred.client_cert" class="code" rows="4"></textarea>
        <label>Private key (PEM)</label>
        <textarea v-model="cred.private_key" class="code" rows="4"></textarea>
        <label>CA certificate path or PEM (optional)</label>
        <input v-model="cred.ca_cert" />
      </template>

      <div class="row" style="justify-content: flex-end; margin-top: 16px; gap: 8px">
        <button @click="showCred = false">Cancel</button>
        <button class="btn-primary" :disabled="credMismatch" @click="saveCred">Save credential</button>
      </div>
    </div>
  </div>
</template>
