export async function apiGet(path) {
  const res = await fetch(path, { headers: { Accept: "application/json" } });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const msg = data?.error || `Request failed (${res.status})`;
    const detail = data?.detail ? ` - ${data.detail}` : "";
    throw new Error(`${msg}${detail}`);
  }
  return data;
}

export async function apiPost(path, payload) {
  const res = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify(payload),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const msg = data?.error || `Request failed (${res.status})`;
    const detail = data?.detail ? ` - ${data.detail}` : "";
    throw new Error(`${msg}${detail}`);
  }
  return data;
}


