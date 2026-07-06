import { defineStore } from "pinia";
import { api } from "./api";

interface Me {
  actor: string;
  role: "read" | "write" | null;
  sso_enabled: boolean;
}

interface Toast {
  id: number;
  kind: "ok" | "err";
  text: string;
}

let toastId = 0;

export const useStore = defineStore("app", {
  state: () => ({
    me: null as Me | null,
    theme: (localStorage.getItem("theme") as "light" | "dark") ?? "light",
    toasts: [] as Toast[],
  }),
  getters: {
    canWrite: (s): boolean => s.me?.role === "write",
    isReadOnly: (s): boolean => s.me?.role !== "write",
  },
  actions: {
    async loadMe() {
      try {
        this.me = await api.get<Me>("/me");
      } catch {
        this.me = { actor: "unknown", role: null, sso_enabled: false };
      }
    },
    toast(kind: "ok" | "err", text: string) {
      const t = { id: ++toastId, kind, text };
      this.toasts.push(t);
      setTimeout(() => {
        this.toasts = this.toasts.filter((x) => x.id !== t.id);
      }, 4000);
    },
    setTheme(theme: "light" | "dark") {
      this.theme = theme;
      localStorage.setItem("theme", theme);
      document.documentElement.setAttribute("data-theme", theme);
    },
  },
});
