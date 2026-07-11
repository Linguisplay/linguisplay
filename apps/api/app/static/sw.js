// 🔔 LinguisPlay service worker (活世界 P3): 角色的话推到现实世界.
// 只做两件事: 收推送弹通知, 点通知回游戏 — 不缓存不代理 (小水管服务器, 缓存交给浏览器).
self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (e) => e.waitUntil(self.clients.claim()));

self.addEventListener("push", (e) => {
  let d = {};
  try { d = e.data ? e.data.json() : {}; } catch (err) {}
  e.waitUntil(self.registration.showNotification(d.title || "LinguisPlay", {
    body: d.body || "",
    icon: "/icon-192.png",
    badge: "/icon-192.png",
    tag: d.tag || "lp",
    data: { url: d.url || "/play" },
  }));
});

self.addEventListener("notificationclick", (e) => {
  e.notification.close();
  const url = (e.notification.data && e.notification.data.url) || "/play";
  e.waitUntil(self.clients.matchAll({ type: "window", includeUncontrolled: true })
    .then((ws) => {
      for (const w of ws) {
        if ("focus" in w) { try { w.navigate(url); } catch (err) {} return w.focus(); }
      }
      return self.clients.openWindow(url);
    }));
});
