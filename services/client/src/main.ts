import { createApp } from "vue";
import { createPinia } from "pinia";
import App from "./App.vue";
import { router } from "./router";
import { useStore } from "./store";
import "./style.css";

const app = createApp(App);
app.use(createPinia());
app.use(router);

const store = useStore();
store.setTheme(store.theme);
store.loadMe();

app.mount("#app");
