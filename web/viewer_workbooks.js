export async function openWorkbookApi(key) {
  const worker = new Worker(new URL("./viewer_workbooks_worker.js", import.meta.url), {type: "module"});
  const pending = new Map();
  let nextId = 0;
  let workerError;

  worker.addEventListener("message", ({data: {id, payload, error}}) => {
    const request = pending.get(id);
    pending.delete(id);
    if (error) request.reject(new Error(error));
    else request.resolve(payload);
  });
  worker.addEventListener("error", () => {
    workerError = new Error("Не удалось запустить обработку XLS. Обновите страницу.");
    for (const request of pending.values()) request.reject(workerError);
    pending.clear();
    worker.terminate();
  });

  function send(message) {
    if (workerError) return Promise.reject(workerError);
    return new Promise((resolve, reject) => {
      const id = ++nextId;
      pending.set(id, {resolve, reject});
      worker.postMessage({id, ...message});
    });
  }

  try {
    await send({key});
  } catch (error) {
    worker.terminate();
    throw error;
  }
  return (path, query) => send({path, query: JSON.stringify(Object.fromEntries(new URLSearchParams(query)))});
}
