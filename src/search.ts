import { $ } from "./shared";

const MAX_RESULTS = 8;
/** lower case, no accents or punctuation: "Sri Muktsar Sahib" ~ "sri muktsar", "Kachchh" ~ "kachchh" */
const norm = (s: string) => s.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase().replace(/[^a-z0-9]+/g, " ").trim();

/** District search box: type a district or state name, pick with click or arrow keys + Enter. */
export function createSearch(gj: any, onPick: (id: string) => void) {
  const input = $<HTMLInputElement>("search"), list = $<HTMLUListElement>("search-results");
  const items = gj.features.map((f: any) => ({
    id: f.properties.id as string, name: f.properties.name as string, state: f.properties.state as string,
    n: norm(f.properties.name), s: norm(f.properties.state),
  })).sort((a: any, b: any) => a.name.localeCompare(b.name));
  let shown: typeof items = [];
  let active = -1;

  function matches(q: string) {
    if (!q) return [];
    const starts = items.filter((it: any) => it.n.startsWith(q) || it.n.split(" ").some((w: string) => w.startsWith(q)));
    const inName = items.filter((it: any) => !starts.includes(it) && it.n.includes(q));
    const inState = items.filter((it: any) => !starts.includes(it) && !inName.includes(it) && it.s.startsWith(q));
    return [...starts, ...inName, ...inState].slice(0, MAX_RESULTS);
  }

  function render() {
    list.replaceChildren(...shown.map((it: any, i: number) => {
      const li = document.createElement("li");
      li.id = `search-opt-${i}`;
      li.setAttribute("role", "option");
      li.setAttribute("aria-selected", String(i === active));
      li.innerHTML = "<span></span><small></small>";
      li.children[0].textContent = it.name;
      li.children[1].textContent = it.state;
      li.addEventListener("mousedown", (e) => { e.preventDefault(); pick(i); }); // before the input blurs
      return li;
    }));
    const q = norm(input.value);
    list.hidden = !q;
    if (q && !shown.length) list.innerHTML = '<li class="empty">No district found</li>';
    input.setAttribute("aria-expanded", String(!list.hidden));
    if (active >= 0) input.setAttribute("aria-activedescendant", `search-opt-${active}`);
    else input.removeAttribute("aria-activedescendant");
  }

  function pick(i: number) {
    const it = shown[i];
    if (!it) return;
    input.value = `${it.name}, ${it.state}`;
    shown = []; active = -1; list.hidden = true;
    input.setAttribute("aria-expanded", "false");
    onPick(it.id);
  }

  input.addEventListener("input", () => { shown = matches(norm(input.value)); active = shown.length ? 0 : -1; render(); });
  input.addEventListener("keydown", (e) => {
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      if (!shown.length) return;
      e.preventDefault();
      active = (active + (e.key === "ArrowDown" ? 1 : shown.length - 1)) % shown.length;
      render();
    } else if (e.key === "Enter") {
      e.preventDefault();
      pick(active >= 0 ? active : 0);
    } else if (e.key === "Escape") {
      list.hidden = true; input.setAttribute("aria-expanded", "false");
    }
  });
  input.addEventListener("blur", () => { list.hidden = true; input.setAttribute("aria-expanded", "false"); });
  input.addEventListener("focus", () => { if (shown.length) { list.hidden = false; input.setAttribute("aria-expanded", "true"); } });
}
