/* Ariya Connect — service worker.
   Cachet ALLEEN de app-schil. API-antwoorden worden nooit gecachet:
   een oude accustand tonen alsof hij vers is, is precies wat deze app niet mag doen. */

const CACHE = 'ariya-schil-v2';

const SCHIL = [
  './',
  './index.html',
  './style.css',
  './app.js',
  './mock-api.js',
  './manifest.json',
  './icon.svg'
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE)
      .then((cache) => cache.addAll(SCHIL))
      .then(() => self.skipWaiting())
      .catch(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys()
      .then((namen) => Promise.all(namen.filter((n) => n !== CACHE).map((n) => caches.delete(n))))
      .then(() => self.clients.claim())
  );
});

function isApi(url) {
  return url.pathname.includes('/api/');
}

self.addEventListener('fetch', (event) => {
  const verzoek = event.request;

  // Alles behalve GET gaat rechtstreeks naar het netwerk.
  if (verzoek.method !== 'GET') return;

  const url = new URL(verzoek.url);

  // API en vreemde herkomsten: nooit cachen, nooit uit de cache beantwoorden.
  if (url.origin !== self.location.origin || isApi(url)) return;

  // De pagina zelf: eerst het netwerk (zo krijg je updates meteen),
  // met de cache als vangnet wanneer je geen bereik hebt.
  if (verzoek.mode === 'navigate') {
    event.respondWith(
      fetch(verzoek)
        .then((antwoord) => {
          const kopie = antwoord.clone();
          caches.open(CACHE).then((cache) => cache.put('./index.html', kopie)).catch(() => {});
          return antwoord;
        })
        .catch(() => caches.match('./index.html').then((c) => c || Response.error()))
    );
    return;
  }

  // Schilbestanden: eerst de cache, daarna het netwerk.
  event.respondWith(
    caches.match(verzoek).then((gevonden) => {
      if (gevonden) return gevonden;
      return fetch(verzoek).then((antwoord) => {
        if (antwoord && antwoord.ok && antwoord.type === 'basic') {
          const kopie = antwoord.clone();
          caches.open(CACHE).then((cache) => cache.put(verzoek, kopie)).catch(() => {});
        }
        return antwoord;
      });
    })
  );
});
