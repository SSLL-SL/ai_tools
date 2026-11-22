(function () {
  'use strict';

  var $ = function (id) { return document.getElementById(id); };
  var storage = {
    get: function (key, fallback) { try { var value = localStorage.getItem('tvesla:' + key); return value === null ? fallback : value; } catch (e) { return fallback; } },
    set: function (key, value) { try { localStorage.setItem('tvesla:' + key, value); return true; } catch (e) { return false; } },
    remove: function (key) { try { localStorage.removeItem('tvesla:' + key); } catch (e) {} },
    json: function (key, fallback) { try { return JSON.parse(this.get(key, '')); } catch (e) { return fallback; } }
  };
  var routes = { inicio: 'home', iptv: 'iptv', streaming: 'streaming', mapas: 'maps', radio: 'radio', luz: 'energy', juegos: 'games', privacidad: 'privacy' };
  var pageByRoute = { home: 'page-home', iptv: 'page-iptv', streaming: 'page-streaming', maps: 'page-maps', radio: 'page-radio', energy: 'page-energy', games: 'page-games', privacy: 'page-privacy' };
  var toastTimer = null;
  var activeIptvTab = 'url';
  var pendingM3U = '';
  var channels = [];
  var channelFavorites = storage.json('channel-favorites', {});
  var favoriteOnly = false;
  var currentChannel = null;
  var currentM3U = null;
  var epgById = {};
  var hlsInstance = null;
  var radioTag = 'popular';
  var radioItems = [];
  var radioFavorites = storage.json('radio-favorites', {});
  var radioItem = null;
  var radioRequest = 0;
  var energyData = { today: null, tomorrow: null };
  var selectedEnergyDay = 'today';
  var romDatabase = null;
  var emulatorBlobUrl = null;
  var emulatorScriptPending = false;
  var recentItems = storage.json('recent', []);

  function toast(message) {
    var el = $('toast');
    el.textContent = message;
    el.classList.add('show');
    window.clearTimeout(toastTimer);
    toastTimer = window.setTimeout(function () { el.classList.remove('show'); }, 3000);
  }

  function escapeHTML(value) {
    return String(value == null ? '' : value).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }

  function openPage(name) {
    if (!pageByRoute[name]) name = 'home';
    Object.keys(pageByRoute).forEach(function (page) {
      $(pageByRoute[page]).classList.toggle('hidden', page !== name);
    });
    if (name === 'radio' && !radioItems.length) loadRadioStations();
    if (name === 'energy' && !energyData.today) loadEnergyData('today');
    if (name === 'games') renderGames();
    if (name === 'home') { renderRecents(); updateRadioMini(); }
    window.scrollTo(0, 0);
  }

  function routeFromHash() {
    var route = (window.location.hash || '#inicio').slice(1).toLowerCase();
    openPage(routes[route] || 'home');
  }
  window.addEventListener('hashchange', routeFromHash);
  document.addEventListener('click', function (event) {
    var pageButton = event.target.closest('[data-page]');
    if (pageButton) {
      event.preventDefault();
      var name = pageButton.getAttribute('data-page');
      var route = Object.keys(routes).filter(function (key) { return routes[key] === name; })[0];
      window.location.hash = route || 'inicio';
      return;
    }
    if (event.target.closest('[data-back]')) { window.location.hash = 'inicio'; return; }
    var full = event.target.closest('[data-fullscreen]');
    if (full) { toggleFullscreen(); }
  });

  function toggleFullscreen() {
    var doc = document;
    var active = doc.fullscreenElement || doc.webkitFullscreenElement;
    if (active) {
      (doc.exitFullscreen || doc.webkitExitFullscreen).call(doc);
      return;
    }
    var request = doc.documentElement.requestFullscreen || doc.documentElement.webkitRequestFullscreen;
    if (request) {
      try { var promise = request.call(doc.documentElement); if (promise && promise.catch) promise.catch(function () { toast('El navegador no permite la pantalla completa aquí.'); }); }
      catch (e) { toast('El navegador no permite la pantalla completa aquí.'); }
    } else if ($('tv-video') && $('tv-video').webkitEnterFullscreen) $('tv-video').webkitEnterFullscreen();
    else toast('Tu navegador no permite poner esta página en pantalla completa.');
  }

  /* Preferencias de interfaz */
  function applyTheme() {
    var light = storage.get('theme', 'light') !== 'dark';
    document.documentElement.setAttribute('data-theme', light ? 'light' : 'dark');
    var themeColor = document.querySelector('meta[name="theme-color"]');
    if (themeColor) themeColor.setAttribute('content', light ? '#ffffff' : '#090a0d');
    $('theme-toggle').innerHTML = '<svg class="icon"><use href="#i-' + (light ? 'sun' : 'moon') + '"/></svg>';
    $('theme-toggle').title = light ? 'Usar tema oscuro' : 'Usar tema claro';
  }
  $('theme-toggle').addEventListener('click', function () {
    storage.set('theme', storage.get('theme', 'light') === 'light' ? 'dark' : 'light');
    applyTheme();
  });
  applyTheme();

  /* Plataformas de streaming */
  var platforms = [
    ['Netflix', 'netflix.com', 'https://www.netflix.com'], ['Prime Video', 'primevideo.com', 'https://www.primevideo.com'], ['Disney+', 'disneyplus.com', 'https://www.disneyplus.com'],
    ['HBO Max', 'hbomax.com', 'https://play.hbomax.com'], ['Movistar Plus+', 'movistarplus.es', 'https://www.movistarplus.es'], ['SkyShowtime', 'skyshowtime.com', 'https://www.skyshowtime.com'],
    ['Apple TV+', 'tv.apple.com', 'https://tv.apple.com'], ['Filmin', 'filmin.es', 'https://www.filmin.es'], ['DAZN', 'dazn.com', 'https://www.dazn.com'],
    ['RTVE Play', 'rtve.es', 'https://www.rtve.es/play/'], ['Pluto TV', 'pluto.tv', 'https://pluto.tv/es'], ['Atresplayer', 'atresplayer.com', 'https://www.atresplayer.com'],
    ['Mitele', 'mitele.es', 'https://www.mitele.es'], ['Rakuten TV', 'rakuten.tv', 'https://www.rakuten.tv/es'], ['3Cat', '3cat.cat', 'https://www.3cat.cat'],
    ['Twitch', 'twitch.tv', 'https://www.twitch.tv'], ['YouTube', 'youtube.com', 'https://www.youtube.com'], ['Plex', 'plex.tv', 'https://app.plex.tv/desktop'],
    ['Emby', 'emby.media', 'https://app.emby.media']
  ];
  function platformIcon(domain) { return 'https://www.google.com/s2/favicons?sz=96&domain=' + encodeURIComponent(domain); }
  function renderPlatforms(query) {
    var grid = $('stream-grid');
    var q = (query || '').trim().toLowerCase();
    var filtered = platforms.filter(function (p) { return p[0].toLowerCase().indexOf(q) !== -1; });
    grid.innerHTML = filtered.map(function (p) {
      return '<a class="stream-card" href="' + p[2] + '" target="_blank" rel="noopener" data-platform="' + escapeHTML(p[0]) + '"><img loading="lazy" src="' + platformIcon(p[1]) + '" alt=""><b>' + escapeHTML(p[0]) + '</b><svg class="icon stream-arrow"><use href="#i-external"/></svg></a>';
    }).join('');
    grid.querySelectorAll('img').forEach(function (img) { img.addEventListener('error', function () { img.style.visibility = 'hidden'; }); });
  }
  renderPlatforms('');
  $('stream-search').addEventListener('input', function () { renderPlatforms(this.value); });
  $('stream-grid').addEventListener('click', function (event) {
    var card = event.target.closest('[data-platform]');
    if (card) addRecent({ type: 'platform', name: card.getAttribute('data-platform'), href: card.href });
  });

  /* Directorio de mapas, navegación y carga eléctrica */
  var mapServices = [
    { name: 'Google Maps', domain: 'maps.google.com', url: 'https://maps.google.com', detail: 'Mapas, tráfico y lugares', category: 'navigation', categoryName: 'Navegación' },
    { name: 'Apple Maps', domain: 'maps.apple.com', url: 'https://maps.apple.com', detail: 'Mapas y navegación', category: 'navigation', categoryName: 'Navegación' },
    { name: 'Waze', domain: 'waze.com', url: 'https://www.waze.com/live-map/', detail: 'Rutas con tráfico en tiempo real', category: 'navigation', categoryName: 'Navegación' },
    { name: 'OpenStreetMap', domain: 'openstreetmap.org', url: 'https://www.openstreetmap.org', detail: 'Mapa colaborativo del mundo', category: 'navigation', categoryName: 'Navegación' },
    { name: 'HERE WeGo', domain: 'wego.here.com', url: 'https://wego.here.com', detail: 'Mapas y planificación de rutas', category: 'navigation', categoryName: 'Navegación' },
    { name: 'Bing Maps', domain: 'bing.com', url: 'https://www.bing.com/maps', detail: 'Mapas, indicaciones y tráfico', category: 'navigation', categoryName: 'Navegación' },
    { name: 'Tesla Superchargers', domain: 'tesla.com', url: 'https://www.tesla.com/findus', detail: 'Localiza Superchargers Tesla', category: 'charging', categoryName: 'Carga eléctrica' },
    { name: 'A Better Routeplanner', domain: 'abetterrouteplanner.com', url: 'https://abetterrouteplanner.com', detail: 'Planifica rutas para vehículos eléctricos', category: 'charging', categoryName: 'Carga eléctrica' },
    { name: 'PlugShare', domain: 'plugshare.com', url: 'https://www.plugshare.com', detail: 'Encuentra cargadores y comparte reseñas', category: 'charging', categoryName: 'Carga eléctrica' },
    { name: 'ChargeFinder', domain: 'chargefinder.com', url: 'https://chargefinder.com', detail: 'Mapa de estaciones de carga', category: 'charging', categoryName: 'Carga eléctrica' }
  ];
  var activeMapFilter = 'all';
  function renderMaps(query) {
    var q = (query || '').trim().toLowerCase();
    var visible = mapServices.filter(function (item) {
      var matchesText = !q || (item.name + ' ' + item.detail + ' ' + item.categoryName).toLowerCase().indexOf(q) !== -1;
      return matchesText && (activeMapFilter === 'all' || item.category === activeMapFilter);
    });
    $('map-grid').innerHTML = visible.map(function (item) {
      return '<a class="map-card" href="' + item.url + '" target="_blank" rel="noopener" data-map-name="' + escapeHTML(item.name) + '"><span class="map-card-icon"><img loading="lazy" src="' + platformIcon(item.domain) + '" alt=""></span><span class="map-card-copy"><strong>' + escapeHTML(item.name) + '</strong><small>' + escapeHTML(item.detail) + '</small></span><span class="map-card-type">' + escapeHTML(item.categoryName) + '</span><svg class="icon map-card-arrow"><use href="#i-external"/></svg></a>';
    }).join('') || '<div class="map-empty">No hay mapas que coincidan con la búsqueda.</div>';
    $('map-grid').querySelectorAll('img').forEach(function (img) { img.addEventListener('error', function () { img.style.visibility = 'hidden'; }); });
  }
  renderMaps('');
  $('map-search').addEventListener('input', function () { renderMaps(this.value); });
  $('map-filters').addEventListener('click', function (event) {
    var button = event.target.closest('[data-map-filter]'); if (!button) return;
    activeMapFilter = button.getAttribute('data-map-filter');
    this.querySelectorAll('.filter-pill').forEach(function (pill) { pill.classList.toggle('active', pill === button); });
    renderMaps($('map-search').value);
  });

  /* Recientes y buscador general */
  function addRecent(item) {
    recentItems = recentItems.filter(function (entry) { return (entry.type + ':' + (entry.key || entry.href)) !== (item.type + ':' + (item.key || item.href)); });
    recentItems.unshift(item);
    recentItems = recentItems.slice(0, 4);
    storage.set('recent', JSON.stringify(recentItems));
    renderRecents();
  }
  function renderRecents() {
    var valid = recentItems.filter(function (entry) { return entry.type !== 'channel' || channels.some(function (c) { return c.key === entry.key; }); });
    var box = $('recent-card');
    box.classList.toggle('hidden', !valid.length);
    $('recent-list').innerHTML = valid.map(function (entry) {
      return '<button class="recent-entry" data-recent-type="' + escapeHTML(entry.type) + '" data-key="' + escapeHTML(entry.key || '') + '" data-href="' + escapeHTML(entry.href || '') + '">' + (entry.type === 'channel' ? '▣ ' : '▶ ') + escapeHTML(entry.name) + '</button>';
    }).join('');
  }
  $('recent-list').addEventListener('click', function (event) {
    var item = event.target.closest('.recent-entry');
    if (!item) return;
    if (item.getAttribute('data-recent-type') === 'platform') window.open(item.getAttribute('data-href'), '_blank', 'noopener');
    else {
      var channel = channels.filter(function (c) { return c.key === item.getAttribute('data-key'); })[0];
      if (!channel) { window.location.hash = 'iptv'; return; }
      window.location.hash = 'iptv';
      setTimeout(function () { playChannel(channel); }, 50);
    }
  });
  $('clear-recents').addEventListener('click', function () { recentItems = []; storage.set('recent', '[]'); renderRecents(); });

  function renderGlobalSearch() {
    var query = $('global-search').value.trim().toLowerCase();
    var box = $('global-results');
    if (!query) { box.classList.add('hidden'); box.innerHTML = ''; return; }
    var results = [];
    channels.forEach(function (channel) {
      if (results.length < 8 && channel.name.toLowerCase().indexOf(query) !== -1) results.push({ label: channel.name, detail: channel.group, kind: 'channel', key: channel.key });
    });
    platforms.forEach(function (platform) {
      if (platform[0].toLowerCase().indexOf(query) !== -1) results.push({ label: platform[0], detail: 'Plataforma de streaming', kind: 'platform', href: platform[2] });
    });
    mapServices.forEach(function (item) {
      if (item.name.toLowerCase().indexOf(query) !== -1) results.push({ label: item.name, detail: item.categoryName, kind: 'map', href: item.url });
    });
    ['IPTV', 'Streaming', 'Mapas', 'Radio', 'Precio de la luz', 'Videojuegos'].forEach(function (title) {
      if (title.toLowerCase().indexOf(query) !== -1) results.push({ label: title, detail: 'Abrir sección', kind: 'route', route: { 'Precio de la luz': 'luz', 'Videojuegos': 'juegos', 'IPTV': 'iptv', 'Streaming': 'streaming', 'Mapas': 'mapas', 'Radio': 'radio' }[title] });
    });
    box.innerHTML = results.length ? results.slice(0, 12).map(function (r, index) {
      return '<button class="global-result" data-kind="' + r.kind + '" data-key="' + escapeHTML(r.key || '') + '" data-href="' + escapeHTML(r.href || '') + '" data-route="' + escapeHTML(r.route || '') + '"><span class="result-type">' + (r.kind === 'channel' ? 'TV' : r.kind === 'platform' ? '▶' : r.kind === 'map' ? '⌖' : '↗') + '</span><span><b>' + escapeHTML(r.label) + '</b><small>' + escapeHTML(r.detail) + '</small></span><svg class="icon"><use href="#i-right"/></svg></button>';
    }).join('') : '<div class="global-no-results">No encontramos resultados. Añade una lista IPTV para buscar canales.</div>';
    box.classList.remove('hidden');
  }
  $('global-search').addEventListener('input', renderGlobalSearch);
  $('global-results').addEventListener('click', function (event) {
    var row = event.target.closest('.global-result'); if (!row) return;
    var kind = row.getAttribute('data-kind');
    if (kind === 'route') window.location.hash = row.getAttribute('data-route');
    else if (kind === 'platform' || kind === 'map') window.open(row.getAttribute('data-href'), '_blank', 'noopener');
    else {
      var channel = channels.filter(function (c) { return c.key === row.getAttribute('data-key'); })[0];
      window.location.hash = 'iptv'; if (channel) setTimeout(function () { playChannel(channel); }, 50);
    }
    $('global-search').value = ''; renderGlobalSearch();
  });
  $('global-search').addEventListener('keydown', function (event) { if (event.key === 'Escape') { this.value = ''; renderGlobalSearch(); this.blur(); } });
  document.addEventListener('keydown', function (event) { if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') { event.preventDefault(); $('global-search').focus(); } });

  /* IPTV: lectura M3U local o remota, grupos, favoritos, EPG y reproducción */
  $('iptv-tabs').addEventListener('click', function (event) {
    var tab = event.target.closest('[data-tab]'); if (!tab) return;
    activeIptvTab = tab.getAttribute('data-tab');
    this.querySelectorAll('.tab').forEach(function (el) { el.classList.toggle('active', el === tab); });
    document.querySelectorAll('.iptv-panel').forEach(function (panel) { panel.classList.toggle('hidden', panel.getAttribute('data-panel') !== activeIptvTab); });
    $('iptv-message').textContent = '';
  });
  $('iptv-file').addEventListener('change', function () {
    var file = this.files && this.files[0]; if (!file) return;
    $('iptv-file-name').textContent = file.name;
    file.text().then(function (text) { pendingM3U = text; }).catch(function () { $('iptv-message').textContent = 'No se pudo leer este archivo.'; });
  });

  function getAttribute(line, key) {
    var escaped = key.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    var quoted = new RegExp('(?:^|\\s)' + escaped + '="([^"]*)"', 'i').exec(line);
    if (quoted) return quoted[1].trim();
    var unquoted = new RegExp('(?:^|\\s)' + escaped + '=([^\\s,]*)', 'i').exec(line);
    return unquoted ? unquoted[1].trim() : '';
  }
  function parseM3U(text) {
    var lines = String(text || '').replace(/^\uFEFF/, '').split(/\r?\n/);
    var parsed = [], info = null;
    for (var i = 0; i < lines.length; i++) {
      var line = lines[i].trim();
      if (!line) continue;
      if (line.indexOf('#EXTINF:') === 0) {
        var comma = line.indexOf(',');
        info = {
          name: comma === -1 ? 'Canal ' + (parsed.length + 1) : line.slice(comma + 1).trim(),
          group: getAttribute(line, 'group-title') || 'Sin categoría',
          logo: getAttribute(line, 'tvg-logo'),
          tvg: getAttribute(line, 'tvg-id') || getAttribute(line, 'tvg-name')
        };
      } else if (line.charAt(0) !== '#') {
        if (info) {
          parsed.push({ id: parsed.length, name: info.name || 'Canal', group: info.group || 'Sin categoría', logo: info.logo, tvg: info.tvg, src: line, key: (info.tvg || '') + '|' + info.name + '|' + info.group });
          info = null;
        } else if (/^https?:\/\//i.test(line)) {
          parsed.push({ id: parsed.length, name: 'Canal ' + (parsed.length + 1), group: 'Sin categoría', logo: '', tvg: '', src: line, key: '|' + line + '|' + parsed.length });
        }
      }
    }
    return parsed;
  }
  function setIptvMessage(text, type) {
    $('iptv-message').textContent = text || '';
    $('iptv-message').classList.toggle('success', type === 'success');
  }
  function sourceFromForm() {
    if (activeIptvTab === 'file') {
      if (!pendingM3U) throw new Error('Elige un archivo M3U para continuar.');
      return { type: 'text', text: pendingM3U, epg: '' };
    }
    if (activeIptvTab === 'xtream') {
      var host = $('xtream-host').value.trim().replace(/\/+$/, '');
      var user = $('xtream-user').value.trim(); var pass = $('xtream-pass').value;
      if (!host || !user || !pass) throw new Error('Completa el servidor, el usuario y la contraseña.');
      var url = new URL(host + '/get.php');
      url.searchParams.set('username', user); url.searchParams.set('password', pass); url.searchParams.set('type', 'm3u_plus'); url.searchParams.set('output', 'ts');
      return { type: 'url', url: url.toString(), epg: '', label: new URL(host).hostname };
    }
    var listUrl = $('iptv-url').value.trim();
    if (!listUrl) throw new Error('Pega el enlace de tu lista M3U.');
    try { new URL(listUrl); } catch (e) { throw new Error('El enlace no parece una URL válida.'); }
    return { type: 'url', url: listUrl, epg: $('iptv-epg-url').value.trim(), label: new URL(listUrl).hostname };
  }
  function fetchM3U(source) {
    if (source.type === 'text') return Promise.resolve(source.text);
    return fetch(source.url, { cache: 'no-store' }).then(function (response) {
      if (!response.ok) throw new Error('El servidor respondió con error (' + response.status + ').');
      return response.text();
    }).catch(function (error) {
      if (error instanceof TypeError) throw new Error('El proveedor no permite cargar la lista desde este navegador (CORS o conexión bloqueada). Prueba subiendo el archivo M3U.');
      throw error;
    });
  }
  function loadPlaylist(source) {
    setIptvMessage('Cargando y leyendo la lista…');
    $('iptv-load').disabled = true;
    fetchM3U(source).then(function (text) {
      var parsed = parseM3U(text);
      if (!parsed.length) throw new Error('No se encontraron canales. Comprueba que el archivo contiene una lista M3U válida.');
      currentM3U = source;
      channels = parsed;
      currentChannel = null;
      epgById = {};
      if (!storage.set('playlist', JSON.stringify(source))) setIptvMessage('La lista se cargó, pero es demasiado grande para guardarla permanentemente en este navegador.', 'success');
      else setIptvMessage(parsed.length + ' canales listos.', 'success');
      renderChannels();
      $('iptv-setup').classList.add('hidden');
      $('iptv-player').classList.remove('hidden');
      $('channel-count').textContent = parsed.length;
      $('video-title').textContent = 'Elige un canal para empezar';
      var categoryCount = Object.keys(parsed.reduce(function (all, channel) { all[channel.group] = 1; return all; }, {})).length;
      $('video-status').textContent = parsed.length + ' canales · ' + categoryCount + ' categorías';
      $('video-empty').classList.remove('is-playing');
      if (source.epg) loadEPG(source.epg);
    }).catch(function (error) {
      setIptvMessage(error.message || 'No se pudo cargar la lista.');
      if (!$('iptv-player').classList.contains('hidden')) { $('video-status').textContent = error.message || 'No se pudo actualizar la lista.'; toast(error.message || 'No se pudo actualizar la lista.'); }
    }).then(function () { $('iptv-load').disabled = false; });
  }
  $('iptv-load').addEventListener('click', function () {
    try { loadPlaylist(sourceFromForm()); } catch (error) { setIptvMessage(error.message); }
  });
  $('iptv-tdt').addEventListener('click', function () {
    setIptvMessage('Conectando con la lista pública de TDT…');
    $('iptv-tdt').disabled = true;
    loadPlaylist({ type: 'url', url: 'https://www.tdtchannels.com/lists/tv.m3u8', epg: '', label: 'TDT en abierto' });
    var check = window.setInterval(function () {
      if (!$('iptv-load').disabled) { $('iptv-tdt').disabled = false; window.clearInterval(check); }
    }, 250);
  });
  $('iptv-refresh').addEventListener('click', function () { if (currentM3U) loadPlaylist(currentM3U); });
  $('iptv-change-list').addEventListener('click', function () { stopVideo(); $('iptv-player').classList.add('hidden'); $('iptv-setup').classList.remove('hidden'); });
  $('iptv-clear').addEventListener('click', function () {
    if (!window.confirm('¿Borrar la lista guardada en este navegador?')) return;
    stopVideo(); currentM3U = null; channels = []; storage.remove('playlist'); storage.remove('channel-favorites'); channelFavorites = {}; $('iptv-player').classList.add('hidden'); $('iptv-setup').classList.remove('hidden'); setIptvMessage(''); renderRecents();
  });
  $('iptv-file').addEventListener('dragover', function (event) { event.preventDefault(); });
  document.querySelector('.file-drop').addEventListener('dragover', function (event) { event.preventDefault(); this.classList.add('dragging'); });
  document.querySelector('.file-drop').addEventListener('dragleave', function () { this.classList.remove('dragging'); });
  document.querySelector('.file-drop').addEventListener('drop', function (event) {
    event.preventDefault(); this.classList.remove('dragging'); var file = event.dataTransfer.files && event.dataTransfer.files[0]; if (!file) return;
    file.text().then(function (text) { pendingM3U = text; $('iptv-file-name').textContent = file.name; activeIptvTab = 'file'; document.querySelector('[data-tab="file"]').click(); });
  });
  function renderChannels() {
    var groups = [];
    channels.forEach(function (channel) { if (groups.indexOf(channel.group) === -1) groups.push(channel.group); });
    groups.sort(function (a, b) { return a.localeCompare(b, 'es'); });
    var previous = $('channel-group').value;
    $('channel-group').innerHTML = '<option value="">Todos los grupos</option>' + groups.map(function (group) { return '<option value="' + escapeHTML(group) + '">' + escapeHTML(group) + '</option>'; }).join('');
    if (groups.indexOf(previous) !== -1) $('channel-group').value = previous;
    var query = $('channel-search').value.trim().toLowerCase();
    var groupFilter = $('channel-group').value;
    var visible = channels.filter(function (channel) {
      return (!groupFilter || channel.group === groupFilter) && (!query || channel.name.toLowerCase().indexOf(query) !== -1) && (!favoriteOnly || !!channelFavorites[channel.key]);
    });
    $('channel-list').innerHTML = visible.length ? visible.map(function (channel, index) {
      var logo = channel.logo ? '<img class="channel-logo" loading="lazy" src="' + escapeHTML(channel.logo) + '" alt="" onerror="this.remove()">' : '<span class="channel-letter">' + escapeHTML(channel.name.charAt(0).toUpperCase()) + '</span>';
      return '<div class="channel-row ' + (currentChannel && currentChannel.key === channel.key ? 'active' : '') + '">' + logo + '<button class="channel-play" data-key="' + escapeHTML(channel.key) + '"><span class="channel-copy"><strong>' + escapeHTML(channel.name) + '</strong><small>' + escapeHTML(channel.group) + '</small></span></button><button class="channel-fav ' + (channelFavorites[channel.key] ? 'on' : '') + '" data-fav-key="' + escapeHTML(channel.key) + '" aria-label="Marcar ' + escapeHTML(channel.name) + ' como favorita">' + (channelFavorites[channel.key] ? '★' : '☆') + '</button></div>';
    }).join('') : '<div class="channel-empty">' + (favoriteOnly && !Object.keys(channelFavorites).length ? 'Todavía no tienes canales favoritos. Toca la estrella de un canal.' : 'No hay canales que coincidan con la búsqueda.') + '</div>';
    $('channel-list').querySelectorAll('.channel-logo').forEach(function (img) { img.addEventListener('error', function () { this.remove(); }); });
    $('channel-count').textContent = channels.length;
  }
  $('channel-search').addEventListener('input', renderChannels);
  $('channel-group').addEventListener('change', renderChannels);
  $('show-favs').addEventListener('click', function () { favoriteOnly = !favoriteOnly; this.classList.toggle('button-primary', favoriteOnly); renderChannels(); });
  $('channel-list').addEventListener('click', function (event) {
    var fav = event.target.closest('[data-fav-key]');
    if (fav) { var key = fav.getAttribute('data-fav-key'); if (channelFavorites[key]) delete channelFavorites[key]; else channelFavorites[key] = true; storage.set('channel-favorites', JSON.stringify(channelFavorites)); renderChannels(); return; }
    var play = event.target.closest('[data-key]'); if (!play) return;
    var channel = channels.filter(function (item) { return item.key === play.getAttribute('data-key'); })[0]; if (channel) playChannel(channel);
  });

  function loadEPG(url) {
    fetch(url).then(function (response) { if (!response.ok) throw new Error(); return response.text(); }).then(function (xml) {
      var parsed = new DOMParser().parseFromString(xml, 'application/xml');
      if (parsed.querySelector('parsererror')) throw new Error();
      epgById = {};
      Array.prototype.forEach.call(parsed.querySelectorAll('programme'), function (programme) {
        var id = programme.getAttribute('channel'); if (!id) return;
        var title = programme.querySelector('title'); if (!title) return;
        (epgById[id] || (epgById[id] = [])).push({ start: xmltvTime(programme.getAttribute('start')), end: xmltvTime(programme.getAttribute('stop')), title: title.textContent.trim() });
      });
      renderChannels(); updateProgramNow();
    }).catch(function () { toast('La lista cargó, pero no se pudo leer la guía XMLTV desde este navegador.'); });
  }
  function xmltvTime(value) {
    var match = /^(\d{4})(\d{2})(\d{2})(\d{2})(\d{2})(\d{2})\s*([+-]\d{4})?/.exec(value || '');
    if (!match) return 0;
    var date = match[1] + '-' + match[2] + '-' + match[3] + 'T' + match[4] + ':' + match[5] + ':' + match[6] + (match[7] ? match[7].slice(0, 3) + ':' + match[7].slice(3) : 'Z');
    return new Date(date).getTime();
  }
  function updateProgramNow() {
    if (!currentChannel || !currentChannel.tvg || !epgById[currentChannel.tvg]) { $('program-now').textContent = ''; return; }
    var now = Date.now();
    var item = epgById[currentChannel.tvg].filter(function (p) { return p.start <= now && p.end > now; })[0];
    $('program-now').textContent = item ? 'Ahora: ' + item.title : '';
  }
  function playChannel(channel) {
    if (radioItem) stopRadio();
    currentChannel = channel;
    $('now-playing').textContent = channel.name;
    $('video-title').textContent = channel.name;
    $('video-status').textContent = channel.group;
    $('video-empty').classList.remove('is-playing');
    $('tv-video').classList.remove('hidden');
    $('video-status').textContent = 'Conectando con el canal…';
    $('tv-video').classList.remove('audio-only'); $('video-audio').classList.remove('active');
    updateProgramNow(); renderChannels();
    addRecent({ type: 'channel', key: channel.key, name: channel.name, group: channel.group });
    startVideo(channel.src);
  }
  function stopVideo() {
    if (hlsInstance) { try { hlsInstance.destroy(); } catch (e) {} hlsInstance = null; }
    var video = $('tv-video');
    try { video.pause(); } catch (e) {}
    video.removeAttribute('src'); video.load(); video.classList.add('hidden');
    $('video-empty').classList.remove('is-playing');
  }
  function loadScript(url) {
    return new Promise(function (resolve, reject) {
      var script = document.createElement('script'); script.src = url; script.onload = resolve; script.onerror = reject; document.head.appendChild(script);
    });
  }
  function startVideo(url) {
    stopVideo();
    var video = $('tv-video'); video.classList.remove('hidden');
    var canNativeHls = video.canPlayType('application/vnd.apple.mpegurl');
    if (canNativeHls) { video.src = url; video.play().catch(function () { $('video-status').textContent = 'Pulsa reproducir para iniciar el canal.'; }); return; }
    if (window.Hls && window.Hls.isSupported()) { attachHls(url); return; }
    loadScript('https://cdn.jsdelivr.net/npm/hls.js@latest').then(function () {
      if (window.Hls && window.Hls.isSupported()) attachHls(url);
      else { video.src = url; video.play().catch(function () { $('video-status').textContent = 'Este formato no se puede reproducir en este navegador.'; }); }
    }).catch(function () { video.src = url; video.play().catch(function () { $('video-status').textContent = 'El navegador no admite este formato de canal.'; }); });
  }
  function attachHls(url) {
    hlsInstance = new window.Hls({ maxBufferLength: 20, liveSyncDurationCount: 3 });
    hlsInstance.loadSource(url); hlsInstance.attachMedia($('tv-video'));
    hlsInstance.on(window.Hls.Events.MANIFEST_PARSED, function () { $('tv-video').play().catch(function () { $('video-status').textContent = 'Pulsa reproducir para iniciar el canal.'; }); });
    hlsInstance.on(window.Hls.Events.ERROR, function (event, data) { if (data.fatal) $('video-status').textContent = 'No se pudo reproducir. Comprueba el canal o contacta con tu proveedor.'; });
  }
  $('tv-video').addEventListener('playing', function () { $('video-empty').classList.add('is-playing'); $('video-status').textContent = 'En directo'; });
  $('tv-video').addEventListener('error', function () { $('video-empty').classList.remove('is-playing'); $('video-status').textContent = 'Este canal no responde en el navegador. Prueba otro canal.'; });
  $('video-audio').addEventListener('click', function () { $('tv-video').classList.toggle('audio-only'); this.classList.toggle('active'); });
  $('video-fullscreen').addEventListener('click', function () { var shell = document.querySelector('.video-shell'); var req = shell.requestFullscreen || shell.webkitRequestFullscreen; if (req) req.call(shell); else toggleFullscreen(); });

  var savedPlaylist = storage.json('playlist', null);
  if (savedPlaylist) {
    fetchM3U(savedPlaylist).then(function (text) {
      channels = parseM3U(text); currentM3U = savedPlaylist;
      if (!channels.length) return;
      renderChannels(); $('iptv-setup').classList.add('hidden'); $('iptv-player').classList.remove('hidden');
      $('video-status').textContent = channels.length + ' canales guardados'; $('channel-count').textContent = channels.length;
      if (savedPlaylist.epg) loadEPG(savedPlaylist.epg);
    }).catch(function () { storage.remove('playlist'); });
  }

  /* Radio: directorio público Radio Browser, favoritos locales y reproductor persistente */
  function updateRadioMini() {
    var active = !!radioItem;
    $('radio-mini').classList.toggle('hidden', !active);
    $('radio-stop').classList.toggle('hidden', !active);
    if (active) { $('radio-mini-name').textContent = radioItem.name; $('radio-now-name').textContent = radioItem.name; $('radio-now-detail').textContent = radioItem.tags || 'Radio en directo'; }
    else { $('radio-now-name').textContent = 'Elige una emisora'; $('radio-now-detail').textContent = 'Tu próxima banda sonora está aquí.'; }
  }
  function loadRadioStations() {
    var query = $('radio-search').value.trim();
    var myRequest = ++radioRequest;
    $('radio-message').textContent = 'Buscando emisoras…';
    if (radioTag === 'favorites' && !query) {
      radioItems = Object.keys(radioFavorites).map(function (id) { return radioFavorites[id]; });
      $('radio-message').textContent = radioItems.length ? '' : 'Aún no tienes favoritas. Toca la estrella de una emisora para guardarla.';
      renderRadio(); return;
    }
    var params = new URLSearchParams({ countrycode: 'ES', limit: '48', order: 'clickcount', reverse: 'true', hidebroken: 'true', is_https: 'true' });
    if (query) params.set('name', query);
    else if (radioTag !== 'popular' && radioTag !== 'favorites') params.set('tag', radioTag);
    fetch('https://de1.api.radio-browser.info/json/stations/search?' + params.toString()).then(function (response) {
      if (!response.ok) throw new Error('El directorio de emisoras no está disponible en este momento.');
      return response.json();
    }).then(function (data) {
      if (myRequest !== radioRequest) return;
      radioItems = data.filter(function (item) { return item.url_resolved && /^https:\/\//i.test(item.url_resolved); }).map(function (item) {
        return { id: item.stationuuid, name: item.name, url: item.url_resolved, logo: item.favicon, tags: (item.tags || '').split(',').slice(0, 2).join(' · ') || 'Radio de España' };
      });
      $('radio-message').textContent = radioItems.length ? '' : 'No encontramos emisoras con esa búsqueda.';
      renderRadio();
    }).catch(function (error) {
      if (myRequest !== radioRequest) return;
      $('radio-message').textContent = error.message + ' Comprueba tu conexión.';
      radioItems = []; renderRadio();
    });
  }
  function renderRadio() {
    $('radio-grid').innerHTML = radioItems.map(function (station) {
      var logo = station.logo ? '<img class="radio-logo" loading="lazy" src="' + escapeHTML(station.logo) + '" alt="" onerror="this.remove()">' : '<span class="radio-fallback">♫</span>';
      return '<div class="radio-card ' + (radioItem && radioItem.id === station.id ? 'playing' : '') + '" data-radio-id="' + escapeHTML(station.id) + '">' + logo + '<span class="radio-copy"><strong>' + escapeHTML(station.name) + '</strong><small>' + escapeHTML(station.tags) + '</small></span><button class="channel-fav ' + (radioFavorites[station.id] ? 'on' : '') + '" data-radio-fav="' + escapeHTML(station.id) + '" aria-label="Favorita">' + (radioFavorites[station.id] ? '★' : '☆') + '</button><span class="radio-play"><svg class="icon"><use href="#i-play"/></svg></span></div>';
    }).join('') || '<div class="channel-empty">No hay emisoras para mostrar.</div>';
  }
  function playRadio(station) {
    radioItem = station; var audio = $('radio-audio'); audio.src = station.url;
    audio.play().then(function () { $('radio-message').textContent = ''; }).catch(function () { $('radio-message').textContent = 'No se pudo iniciar esta emisora. Prueba con otra.'; });
    updateRadioMini(); renderRadio();
  }
  function stopRadio() { radioItem = null; $('radio-audio').pause(); $('radio-audio').removeAttribute('src'); $('radio-audio').load(); updateRadioMini(); renderRadio(); }
  $('radio-grid').addEventListener('click', function (event) {
    var fav = event.target.closest('[data-radio-fav]');
    if (fav) {
      event.stopPropagation(); var id = fav.getAttribute('data-radio-fav'); var station = radioItems.filter(function (item) { return item.id === id; })[0];
      if (radioFavorites[id]) delete radioFavorites[id]; else if (station) radioFavorites[id] = station;
      storage.set('radio-favorites', JSON.stringify(radioFavorites));
      if (radioTag === 'favorites') loadRadioStations(); else renderRadio(); return;
    }
    var card = event.target.closest('[data-radio-id]'); if (card) { var item = radioItems.filter(function (station) { return station.id === card.getAttribute('data-radio-id'); })[0]; if (item) playRadio(item); }
  });
  $('radio-filters').addEventListener('click', function (event) {
    var button = event.target.closest('[data-tag]'); if (!button) return;
    radioTag = button.getAttribute('data-tag'); this.querySelectorAll('.filter-pill').forEach(function (pill) { pill.classList.toggle('active', pill === button); });
    $('radio-search').value = ''; loadRadioStations();
  });
  var radioSearchTimer;
  $('radio-search').addEventListener('input', function () {
    window.clearTimeout(radioSearchTimer); radioSearchTimer = window.setTimeout(function () { if ($('radio-search').value.trim()) { radioTag = 'popular'; $('radio-filters').querySelectorAll('.filter-pill').forEach(function (pill) { pill.classList.toggle('active', pill.getAttribute('data-tag') === 'popular'); }); } loadRadioStations(); }, 450);
  });
  $('radio-stop').addEventListener('click', stopRadio); $('radio-stop-mini').addEventListener('click', stopRadio);
  $('radio-audio').addEventListener('error', function () { if (radioItem) $('radio-message').textContent = 'La emisora no responde. Prueba con otra.'; });

  /* Precio horario PVPC de Red Eléctrica, publicado con CORS abierto. */
  function dateKey(date) { return date.getFullYear() + '-' + String(date.getMonth() + 1).padStart(2, '0') + '-' + String(date.getDate()).padStart(2, '0'); }
  function loadEnergyData(day) {
    var targetDay = day || selectedEnergyDay;
    selectedEnergyDay = targetDay;
    var date = new Date(); if (targetDay === 'tomorrow') date.setDate(date.getDate() + 1);
    var start = dateKey(date); var endDate = new Date(date); endDate.setDate(endDate.getDate() + 1);
    $('energy-message').textContent = 'Consultando los precios horarios del mercado…';
    $('current-label').textContent = 'Consultando el mercado…';
    var params = new URLSearchParams({ start_date: start + 'T00:00', end_date: dateKey(endDate) + 'T00:00', time_trunc: 'hour' });
    var url = 'https://apidatos.ree.es/es/datos/mercados/precios-mercados-tiempo-real?' + params.toString();
    fetch(url).then(function (response) { if (!response.ok) throw new Error('No se han podido consultar los precios del mercado.'); return response.json(); }).then(function (data) {
      var pvpc = (data.included || []).filter(function (item) { return item.id === '1001' || item.type === 'PVPC'; })[0];
      var values = pvpc && pvpc.attributes ? pvpc.attributes.values || [] : [];
      var points = [];
      for (var i = 0; i < values.length; i++) {
        var value = values[i];
        if (value.value == null || !value.datetime || value.datetime.slice(0, 10) !== start) continue;
        var time = new Date(value.datetime);
        points.push({ hour: Number(value.datetime.slice(11, 13)), price: Number(value.value), date: time, end: time.getTime() + 60 * 60 * 1000 });
      }
      if (!points.length) throw new Error(targetDay === 'tomorrow' ? 'Los precios de mañana aún no están publicados.' : 'No hay precios PVPC publicados para esta fecha.');
      energyData[targetDay] = points;
      $('energy-message').textContent = 'Precio PVPC horario publicado por Red Eléctrica de España, en €/kWh y sin impuestos.';
      if (selectedEnergyDay === targetDay) renderEnergy();
    }).catch(function (error) {
      if (selectedEnergyDay !== targetDay) return;
      $('energy-message').textContent = error.message + ' Prueba a actualizar más tarde.';
      $('current-label').textContent = 'Datos no disponibles ahora'; $('best-window').textContent = 'Sin datos'; $('best-detail').textContent = 'Vuelve a intentarlo dentro de un rato.';
      $('energy-chart').innerHTML = '<div class="channel-empty">No se pudo conectar con la fuente de precios.</div>';
    });
  }
  function renderEnergy() {
    var points = energyData[selectedEnergyDay]; if (!points || !points.length) return;
    var values = points.map(function (point) { return point.price; });
    var min = Math.min.apply(null, values); var max = Math.max.apply(null, values);
    var threshold = (max - min) / 3;
    var now = Date.now();
    var current = selectedEnergyDay === 'today' ? points.filter(function (point) { return point.date.getTime() <= now && point.end > now; })[0] : null;
    $('current-price').textContent = current ? (current.price / 1000).toFixed(3).replace('.', ',') + ' €/kWh' : (min / 1000).toFixed(3).replace('.', ',') + ' €/kWh';
    $('current-label').textContent = current ? 'Precio PVPC ahora · ' + String(current.hour).padStart(2, '0') + ':00–' + String((current.hour + 1) % 24).padStart(2, '0') + ':00' : 'Precio más bajo del día seleccionado';
    var hours = Number($('charge-hours').value) || 4;
    var first = 0; var lowest = Infinity;
    for (var i = 0; i <= points.length - hours; i++) {
      if (selectedEnergyDay === 'today' && points[i].end <= now) continue;
      var total = 0;
      for (var j = 0; j < hours; j++) total += points[i + j].price;
      if (total < lowest) { lowest = total; first = i; }
    }
    var bestHours = {}; if (lowest < Infinity) for (var best = 0; best < hours; best++) bestHours[points[first + best].hour] = true;
    $('best-window').textContent = lowest < Infinity ? String(points[first].hour).padStart(2, '0') + ':00 – ' + String((points[first + hours - 1].hour + 1) % 24).padStart(2, '0') + ':00' : 'Sin tramo disponible';
    $('best-detail').textContent = lowest < Infinity ? hours + ' h · ' + (lowest / 1000).toFixed(3).replace('.', ',') + ' €/kWh de media (PVPC)' : 'No quedan suficientes horas en este día.';
    $('energy-chart').innerHTML = points.map(function (point) {
      var level = point.price <= min + threshold ? 'cheap' : point.price >= max - threshold ? 'expensive' : 'mid';
      var height = max === min ? 55 : 12 + ((point.price - min) / (max - min)) * 78;
      return '<div class="energy-bar ' + level + (current && point.hour === current.hour ? ' current' : '') + (bestHours[point.hour] ? ' best' : '') + '" style="height:' + height + '%"><small>' + (point.price / 1000).toFixed(3).replace('.', ',') + ' €/kWh</small><span>' + String(point.hour).padStart(2, '0') + 'h</span></div>';
    }).join('');
  }
  $('energy-days').addEventListener('click', function (event) {
    var button = event.target.closest('[data-day]'); if (!button) return;
    selectedEnergyDay = button.getAttribute('data-day'); this.querySelectorAll('.filter-pill').forEach(function (pill) { pill.classList.toggle('active', pill === button); });
    if (energyData[selectedEnergyDay]) renderEnergy(); else loadEnergyData(selectedEnergyDay);
  });
  $('charge-hours').addEventListener('change', renderEnergy);
  $('energy-refresh').addEventListener('click', function () { energyData[selectedEnergyDay] = null; loadEnergyData(selectedEnergyDay); });

  /* Biblioteca local de ROMs (IndexedDB) y emulador cargado a petición */
  var dbRequest = window.indexedDB ? indexedDB.open('tvesla-local-games', 1) : null;
  if (dbRequest) {
    dbRequest.onupgradeneeded = function () { var db = dbRequest.result; if (!db.objectStoreNames.contains('roms')) db.createObjectStore('roms', { keyPath: 'id' }); };
    dbRequest.onsuccess = function () { romDatabase = dbRequest.result; renderGames(); };
    dbRequest.onerror = function () { toast('El navegador no permite guardar ROMs localmente.'); };
  }
  function romTransaction(mode) { return romDatabase.transaction(['roms'], mode).objectStore('roms'); }
  function getRoms() {
    return new Promise(function (resolve) {
      if (!romDatabase) { resolve([]); return; }
      var request = romTransaction('readonly').getAll(); request.onsuccess = function () { resolve(request.result || []); }; request.onerror = function () { resolve([]); };
    });
  }
  function romSystem(filename) {
    var extension = filename.toLowerCase().split('.').pop();
    var map = { nes: ['nes', 'NES'], sfc: ['snes', 'SNES'], smc: ['snes', 'SNES'], md: ['segaMD', 'Mega Drive'], gen: ['segaMD', 'Mega Drive'], gb: ['gb', 'Game Boy'], gbc: ['gb', 'Game Boy Color'], gba: ['gba', 'Game Boy Advance'], iso: ['psx', 'PlayStation'], pbp: ['psx', 'PlayStation'], chd: ['psx', 'PlayStation'], n64: ['n64', 'Nintendo 64'], z64: ['n64', 'Nintendo 64'], v64: ['n64', 'Nintendo 64'] };
    return map[extension] || null;
  }
  function renderGames() {
    getRoms().then(function (items) {
      $('game-count').textContent = items.length;
      $('game-empty').classList.toggle('hidden', !!items.length);
      $('saved-games').innerHTML = items.map(function (game) {
        return '<div class="game-row"><span class="game-icon"><svg class="icon"><use href="#i-game"/></svg></span><span class="game-copy"><strong>' + escapeHTML(game.name) + '</strong><span>' + escapeHTML(game.systemName) + ' · ' + (game.size / (1024 * 1024)).toFixed(1) + ' MB</span></span><button class="button button-primary" data-launch-rom="' + escapeHTML(game.id) + '"><svg class="icon"><use href="#i-play"/></svg> Jugar</button><button class="delete-game" data-delete-rom="' + escapeHTML(game.id) + '" aria-label="Borrar juego"><svg class="icon"><use href="#i-trash"/></svg></button></div>';
      }).join('');
    });
  }
  $('add-rom').addEventListener('click', function () { $('rom-file').click(); });
  $('rom-file').addEventListener('change', function () {
    var file = this.files && this.files[0]; this.value = ''; if (!file) return;
    var system = romSystem(file.name);
    if (!system) { toast('Este formato no está reconocido. Elige una ROM de NES, SNES, Mega Drive, Game Boy, GBA, PlayStation o N64.'); return; }
    if (!romDatabase) { toast('Este navegador no admite el almacenamiento local de juegos.'); return; }
    var game = { id: Date.now().toString(36) + Math.random().toString(36).slice(2, 7), name: file.name.replace(/\.[^.]+$/, ''), system: system[0], systemName: system[1], size: file.size, blob: file, added: Date.now() };
    var request = romTransaction('readwrite').put(game);
    request.onsuccess = function () { renderGames(); toast('Juego guardado solo en este dispositivo.'); };
    request.onerror = function () { toast('No se pudo guardar el archivo. Puede ser demasiado grande para este navegador.'); };
  });
  $('saved-games').addEventListener('click', function (event) {
    var remove = event.target.closest('[data-delete-rom]');
    if (remove) { var request = romTransaction('readwrite').delete(remove.getAttribute('data-delete-rom')); request.onsuccess = renderGames; return; }
    var launch = event.target.closest('[data-launch-rom]'); if (!launch) return;
    getRoms().then(function (items) { var game = items.filter(function (item) { return item.id === launch.getAttribute('data-launch-rom'); })[0]; if (game) launchGame(game); });
  });
  function launchGame(game) {
    if (emulatorBlobUrl) URL.revokeObjectURL(emulatorBlobUrl);
    emulatorBlobUrl = URL.createObjectURL(game.blob);
    $('emulator-title').textContent = game.name;
    $('emulator-shell').classList.remove('hidden');
    $('emulator').innerHTML = '';
    window.EJS_player = '#emulator'; window.EJS_gameUrl = emulatorBlobUrl; window.EJS_core = game.system;
    window.EJS_pathtodata = 'https://cdn.emulatorjs.org/stable/data/'; window.EJS_startOnLoaded = true;
    var old = document.querySelector('script[data-emulatorjs]'); if (old) old.remove();
    var script = document.createElement('script'); script.src = window.EJS_pathtodata + 'loader.js'; script.setAttribute('data-emulatorjs', 'true');
    script.onerror = function () { toast('No se pudo descargar el emulador. Comprueba tu conexión.'); };
    document.head.appendChild(script);
    $('emulator-shell').scrollIntoView({ behavior: 'smooth', block: 'center' });
  }
  $('close-emulator').addEventListener('click', function () {
    $('emulator-shell').classList.add('hidden'); $('emulator').innerHTML = '';
    if (emulatorBlobUrl) { URL.revokeObjectURL(emulatorBlobUrl); emulatorBlobUrl = null; }
  });

  /* Iniciar con lista guardada y rutas actuales */
  renderRecents();
  if (window.location.hash) routeFromHash(); else openPage('home');
  if (currentM3U) updateRadioMini();
  window.setInterval(updateProgramNow, 30000);
})();
