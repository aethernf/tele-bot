// Cloudflare Worker – Multi-Device Limit System (Lua Response)
const REPO_OWNER = "aethernf"; 
const REPO_NAME = "worker";
const BRANCH = "main";

export default {
  async fetch(request, env, ctx) {
    if (request.method !== "POST") return new Response("Invalid Method", { status: 405 });

    try {
      const text = await request.text();
      const params = new URLSearchParams(text);
      const userKey = params.get("key");
      const userHWID = params.get("hwid");

      if (!userKey || !userHWID) {
        return new Response('return { status = "error", message = "Missing Params" }');
      }

      // 1. Fetch Keylist from GitHub
      const rawUrl = `https://raw.githubusercontent.com/${REPO_OWNER}/${REPO_NAME}/${BRANCH}/keylist.lua`;
      const resp = await fetch(rawUrl, { cf: { cacheTtl: 30 } });
      if (!resp.ok) return new Response('return { status = "error", message = "DB Error" }');

      const luaContent = await resp.text();

      // 2. Find Key Data and Max Devices Limit
      const keyPattern = new RegExp(`\\["${userKey}"\\]\\s*=\\s*\\{([^}]+)\\}`, 's');
      const match = luaContent.match(keyPattern);

      if (!match) return new Response('return { status = "error", message = "Key Not Found" }');

      const details = match[1];
      if (details.includes('valid = false')) return new Response('return { status = "error", message = "Key Blocked" }');

      // Extract expiry (YYYY-MM-DD) and enforce it: key valid THROUGH expiry day
      const expMatch = details.match(/expiry\s*=\s*"(\d{4}-\d{2}-\d{2})"/);
      const expiryStr = expMatch ? expMatch[1] : "";
      if (expiryStr) {
        const parts = expiryStr.split("-").map(Number);
        const expEnd = Date.UTC(parts[0], parts[1] - 1, parts[2]) + 86400000;
        if (Date.now() >= expEnd) {
          return new Response(`return { status = "error", message = "Key Expired (${expiryStr})" }`);
        }
      }

      // Extract limit from keylist (Default is 1 if not specified)
      const limitMatch = details.match(/max_devices\s*=\s*(\d+)/);
      const maxDevices = limitMatch ? parseInt(limitMatch[1]) : 1;

      // 3. MULTI-DEVICE HWID LOGIC (Using Cloudflare KV)
      if (env.HWID_DB) {
        let hwidData = await env.HWID_DB.get(userKey);
        let hwidList = hwidData ? JSON.parse(hwidData) : [];

        // Check if current device is already in the list
        if (!hwidList.includes(userHWID)) {
          // New device detected! Check limit
          if (hwidList.length < maxDevices) {
            hwidList.push(userHWID);
            await env.HWID_DB.put(userKey, JSON.stringify(hwidList));
          } else {
            // Limit reached
            return new Response(`return { status = "error", message = "Limit Reached (${maxDevices} Devices Only)" }`);
          }
        }
      }

      // SUCCESS
      return new Response(`return { status = "success", message = "Active", limit = ${maxDevices}, expiry = "${expiryStr}" }`, {
        headers: { "Content-Type": "text/plain" }
      });

    } catch (err) {
      return new Response(`return { status = "error", message = "Server Error: ${err.message}" }`);
    }
  }
};
