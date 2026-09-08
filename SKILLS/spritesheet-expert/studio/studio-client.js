let connection;

export function session() {
  if (!connection) connection = fetch('/api/session').then(async response => {
    if (!response.ok) throw new Error('Start Studio with serve_item_studio.py to open a workspace.');
    return response.json();
  });
  return connection;
}

export async function request(path, payload, {raw = false, headers = {}} = {}) {
  const current = await session();
  const options = {headers: {'X-Workspace-Id': current.workspace.id, ...headers}};
  if (payload !== undefined) Object.assign(options, {
    method: 'POST', body: raw ? payload : JSON.stringify(payload),
    headers: {...options.headers, 'X-Studio-Token': current.token,
      ...(!raw ? {'Content-Type': 'application/json'} : {})},
  });
  const response = await fetch(path, options);
  if (!response.ok) throw new Error((await response.json()).error || `HTTP ${response.status}`);
  return response.json();
}
