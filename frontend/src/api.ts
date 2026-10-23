// Where the replay server is. In development this is empty: the page and the server share an origin because Vite
// forwards /api and /ws to it (vite.config.ts). The deployed site is a static app on Azure Static Web Apps and the
// server is a Container App on another origin, so its build gets the server's address in VITE_API_BASE
// (https://<app>.<region>.azurecontainerapps.io, set from the GitHub repository variable API_BASE).
const base = ((import.meta.env.VITE_API_BASE as string | undefined) ?? "").trim().replace(/\/+$/, "");

/** True when the server is on another origin (the deployed site), where it also keeps viewer profiles. */
export const remoteServer = base !== "";

export const apiUrl = (path: string) => `${base}${path}`;

export const wsUrl = (path: string) =>
  base ? `${base.replace(/^http/, "ws")}${path}` : `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}${path}`;
