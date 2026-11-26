import {loadPyodide} from "./runtime/pyodide.mjs";

let workbooks;
let planningExamples;
const planningExamplePath = /^\/api\/planning\/examples\/(march_subset_scenario|may_integration_scenario)$/;

async function readFile(path) {
  const response = await fetch(new URL(path, import.meta.url), {cache: "no-cache"});
  if (!response.ok) throw new Error("Файлы приложения недоступны. Обновите страницу.");
  return response.arrayBuffer();
}

async function decryptArchive(path, key) {
  if (!/^[0-9a-f]{64}$/i.test(key)) throw new Error("Проверьте ключ доступа.");
  const rawKey = Uint8Array.from(key.match(/../g), pair => Number.parseInt(pair, 16));
  const cryptoKey = await crypto.subtle.importKey("raw", rawKey, "AES-GCM", false, ["decrypt"]);
  const encrypted = new Uint8Array(await readFile(path));
  try {
    return await crypto.subtle.decrypt(
      {name: "AES-GCM", iv: encrypted.subarray(0, 12)}, cryptoKey, encrypted.subarray(12),
    );
  } catch (error) {
    if (error.name === "OperationError") throw new Error("Ключ доступа не подошёл.");
    throw error;
  }
}

async function openWorkbooks(key) {
  const books = await decryptArchive("./workbooks.zip.enc", key);
  const [python, application, xlrd] = await Promise.all([
    loadPyodide({indexURL: new URL("./runtime/", import.meta.url).href}),
    readFile("./runtime/application.zip"),
    readFile("./runtime/xlrd.whl"),
  ]);
  python.unpackArchive(application, "zip", {extractDir: "/trace_app"});
  python.unpackArchive(xlrd, "zip", {extractDir: "/trace_app"});
  python.unpackArchive(books, "zip", {extractDir: "/trace_books"});
  python.runPython("import sys; sys.path.insert(0, '/trace_app')");
  const backend = python.pyimport("server.browser_api");
  try {
    return {api: backend.WorkbookApi("/trace_books"), python, key};
  } finally {
    backend.destroy();
  }
}

async function readPlanningExample(name) {
  if (!planningExamples) {
    planningExamples = decryptArchive("./planning_examples.zip.enc", workbooks.key).then(archive => {
      workbooks.python.unpackArchive(archive, "zip", {extractDir: "/planning_examples"});
    }).catch(error => {
      planningExamples = null;
      throw error;
    });
  }
  await planningExamples;
  return JSON.parse(workbooks.python.FS.readFile(`/planning_examples/${name}.json`, {encoding: "utf8"}));
}

self.addEventListener("message", async ({data: {id, key, path, query}}) => {
  try {
    if (key !== undefined) {
      workbooks = await openWorkbooks(key);
      self.postMessage({id});
    } else {
      const example = planningExamplePath.exec(path)?.[1];
      if (example) {
        const payload = await readPlanningExample(example);
        self.postMessage({id, payload});
        return;
      }
      const [status, payload] = JSON.parse(workbooks.api.request(path, query));
      if (status >= 400) throw new Error(payload.error);
      self.postMessage({id, payload});
    }
  } catch (error) {
    self.postMessage({id, error: error.message});
  }
});
