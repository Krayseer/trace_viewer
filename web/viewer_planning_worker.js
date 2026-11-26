import {loadPyodide} from "./runtime/pyodide.mjs";

const runtime = new URL("./runtime/", import.meta.url);
let solver;

async function openSolver() {
  const [python, response] = await Promise.all([
    loadPyodide({indexURL: runtime.href}),
    fetch(new URL("application.zip", runtime)),
  ]);
  if (!response.ok) throw new Error("Не удалось загрузить расчётное ядро.");
  await python.loadPackage("scipy");
  python.unpackArchive(await response.arrayBuffer(), "zip", {extractDir: "/trace_app"});
  python.runPython("import sys; sys.path.insert(0, '/trace_app')");
  const backend = python.pyimport("server.planning_api");
  try {
    return backend.solve_json.copy();
  } finally {
    backend.destroy();
  }
}

self.addEventListener("message", async ({data}) => {
  try {
    solver ??= openSolver();
    const solve = await solver;
    self.postMessage(JSON.parse(solve(data)));
  } catch (error) {
    console.error(error);
    self.postMessage([500, {error: "Не удалось выполнить расчёт в браузере. Повторите попытку."}]);
    self.close();
  }
});
