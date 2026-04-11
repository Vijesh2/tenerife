const ROUTES_URL = "/data/processed/routes.geojson";
const TENERIFE_CENTER = [28.2916, -16.6291];

const routeLayers = new Map();
const routeVisibility = new Map();
const routeColors = new Map();
let selectedRouteId = null;
let routesGeoJson = null;

const ROUTE_PALETTE = [
  "#d9271e",
  "#1769aa",
  "#178a62",
  "#8c5a00",
  "#7a3db8",
  "#c23a7a",
  "#007f89",
  "#6d7f00",
  "#a64018",
  "#3f6fc4",
  "#10823d",
  "#8f2f2f",
];

const map = L.map("map", {
  zoomControl: true,
  scrollWheelZoom: true,
}).setView(TENERIFE_CENTER, 10);

L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
  maxZoom: 19,
  attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
}).addTo(map);

const routeListEl = document.querySelector("#route-list");
const routeDetailEl = document.querySelector("#route-detail");
const mapStatusEl = document.querySelector("#map-status");
const appLayoutEl = document.querySelector(".app-layout");
const routesPanelEl = document.querySelector(".routes-panel");
const routeResizerEl = document.querySelector("#route-resizer");
const toggleAllRoutesEl = document.querySelector("#toggle-all-routes");

function propsFor(feature) {
  return feature && feature.properties ? feature.properties : {};
}

function routeIdFor(feature, fallbackIndex = 0) {
  const props = propsFor(feature);
  return props.route_id || props.id || `route-${fallbackIndex}`;
}

function routeName(props) {
  return props.name || props.route_name || props.route_id || "Unnamed route";
}

function routeNumber(props, fallbackIndex) {
  const source = `${props.name || ""} ${props.route_id || ""}`;
  const match = source.match(/\bTRF[_\s-]*(\d+)\b/i) || source.match(/\b(\d+)\b/);
  return match ? match[1] : String(fallbackIndex + 1);
}

function routeShortId(feature, fallbackIndex) {
  return `TRF_${routeNumber(propsFor(feature), fallbackIndex)}`;
}

function colorForRoute(routeId, fallbackIndex = 0) {
  if (!routeColors.has(routeId)) {
    routeColors.set(routeId, ROUTE_PALETTE[fallbackIndex % ROUTE_PALETTE.length]);
  }
  return routeColors.get(routeId);
}

function styleForRoute(routeId, state = "default") {
  const color = colorForRoute(routeId);
  const styles = {
    default: { weight: 4, opacity: 0.74 },
    hover: { weight: 6, opacity: 0.95 },
    selected: { weight: 9, opacity: 1 },
  };

  return {
    color,
    weight: styles[state].weight,
    opacity: styles[state].opacity,
    lineCap: "round",
    lineJoin: "round",
  };
}

function numberOrNull(value) {
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

function formatKm(value) {
  const number = numberOrNull(value);
  return number === null ? "Distance unknown" : `${number.toFixed(1)} km`;
}

function formatMeters(value, fallback = "Unknown") {
  const number = numberOrNull(value);
  return number === null ? fallback : `${Math.round(number).toLocaleString()} m`;
}

function titleCase(value) {
  if (!value) return "Unknown";
  return String(value).replaceAll("_", " ").replace(/\b\w/g, (char) => char.toUpperCase());
}

function escapeHtml(value) {
  return String(value == null ? "" : value).replace(/[&<>"']/g, (char) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#039;",
  })[char]);
}

function routeMeta(props) {
  return `${formatKm(props.distance_km)} · ${formatMeters(props.elevation_gain_m, "Gain unknown")}`;
}

function setStatus(message) {
  renderRouteKey(message);
}

function visibleRouteEntries() {
  if (!routesGeoJson || !Array.isArray(routesGeoJson.features)) return [];
  return routesGeoJson.features
    .map((feature, index) => {
      const routeId = routeIdFor(feature, index);
      return { feature, index, routeId };
    })
    .filter((entry) => routeVisibility.get(entry.routeId) !== false);
}

function renderRouteKey(message) {
  if (!mapStatusEl) return;
  const entries = visibleRouteEntries();
  const key = entries.length
    ? entries.map(({ feature, index, routeId }) => `
        <div class="route-key-row">
          <span class="route-key-dot" style="--route-color: ${escapeHtml(colorForRoute(routeId, index))}"></span>
          <span class="route-key-id">${escapeHtml(routeShortId(feature, index))}</span>
          <span class="route-key-stat">${escapeHtml(formatKm(propsFor(feature).distance_km))}</span>
          <span class="route-key-stat">${escapeHtml(formatMeters(propsFor(feature).elevation_gain_m, "Unknown"))}</span>
        </div>
      `).join("")
    : '<span>No routes visible</span>';

  mapStatusEl.innerHTML = `
    <strong>Tenerife</strong>
    <span>${escapeHtml(message || `${entries.length} routes visible`)}</span>
    <div class="route-key">${key}</div>
  `;
}

function clamp(value, min, max) {
  return Math.min(Math.max(value, min), max);
}

function routePanelLimits() {
  const viewportHeight = window.innerHeight || document.documentElement.clientHeight;
  return {
    min: 86,
    max: Math.max(160, Math.round(viewportHeight * 0.55)),
  };
}

function setRoutePanelHeight(height) {
  if (!appLayoutEl) return;
  const limits = routePanelLimits();
  const nextHeight = clamp(height, limits.min, limits.max);
  appLayoutEl.style.setProperty("--route-list-height", `${nextHeight}px`);
  window.requestAnimationFrame(() => map.invalidateSize(false));
}

function currentRoutePanelHeight() {
  return routesPanelEl ? routesPanelEl.getBoundingClientRect().height : 150;
}

function setupRouteResizer() {
  if (!routeResizerEl || !routesPanelEl) return;

  let startY = 0;
  let startHeight = 0;
  let pointerId = null;

  function beginResize(event) {
    pointerId = event.pointerId;
    startY = event.clientY;
    startHeight = currentRoutePanelHeight();
    routeResizerEl.setPointerCapture(pointerId);
    document.body.classList.add("is-resizing-routes");
  }

  function resize(event) {
    if (pointerId === null) return;
    const delta = startY - event.clientY;
    setRoutePanelHeight(startHeight + delta);
  }

  function endResize() {
    if (pointerId === null) return;
    pointerId = null;
    document.body.classList.remove("is-resizing-routes");
    map.invalidateSize(false);
  }

  routeResizerEl.addEventListener("pointerdown", beginResize);
  routeResizerEl.addEventListener("pointermove", resize);
  routeResizerEl.addEventListener("pointerup", endResize);
  routeResizerEl.addEventListener("pointercancel", endResize);

  routeResizerEl.addEventListener("keydown", (event) => {
    if (event.key === "ArrowUp") {
      event.preventDefault();
      setRoutePanelHeight(currentRoutePanelHeight() + 24);
    }
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setRoutePanelHeight(currentRoutePanelHeight() - 24);
    }
    if (event.key === "Home") {
      event.preventDefault();
      setRoutePanelHeight(routePanelLimits().max);
    }
    if (event.key === "End") {
      event.preventDefault();
      setRoutePanelHeight(routePanelLimits().min);
    }
  });

  window.addEventListener("resize", () => setRoutePanelHeight(currentRoutePanelHeight()));
}

function renderRouteList(features) {
  if (!features.length) {
    routeListEl.innerHTML = '<p class="detail-muted">No routes found in the GeoJSON file.</p>';
    return;
  }

  routeListEl.innerHTML = features.map((feature, index) => {
    const props = propsFor(feature);
    const routeId = routeIdFor(feature, index);
    const color = colorForRoute(routeId, index);
    return `
      <div class="route-row" role="button" tabindex="0" data-route-id="${escapeHtml(routeId)}" style="--route-color: ${escapeHtml(color)}">
        <input class="route-toggle" type="checkbox" checked aria-label="Show ${escapeHtml(routeName(props))} on map">
        <span class="route-badge" aria-label="Route ${escapeHtml(routeNumber(props, index))}">${escapeHtml(routeNumber(props, index))}</span>
        <span class="route-name">${escapeHtml(routeName(props))}</span>
        <span class="route-cell"><strong>${escapeHtml(formatKm(props.distance_km))}</strong></span>
        <span class="route-cell"><strong>${escapeHtml(formatMeters(props.elevation_gain_m, "Unknown"))}</strong></span>
      </div>
    `;
  }).join("");

  routeListEl.querySelectorAll("[data-route-id]").forEach((button) => {
    const checkbox = button.querySelector(".route-toggle");

    checkbox.addEventListener("click", (event) => event.stopPropagation());
    checkbox.addEventListener("change", () => setRouteVisible(button.dataset.routeId, checkbox.checked));

    button.addEventListener("click", () => selectRoute(button.dataset.routeId, { showIfHidden: true }));
    button.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        selectRoute(button.dataset.routeId, { showIfHidden: true });
      }
    });
  });
}

function renderDetail(feature) {
  if (!feature) {
    routeDetailEl.className = "route-detail empty";
    routeDetailEl.textContent = "Select a route to see the basic stats.";
    return;
  }

  const props = propsFor(feature);
  routeDetailEl.className = "route-detail compact";
  routeDetailEl.innerHTML = `
    <h2>${escapeHtml(routeName(props))}</h2>
    <div class="detail-grid">
      ${detailStat("Distance", formatKm(props.distance_km))}
      ${detailStat("Gain", formatMeters(props.elevation_gain_m))}
    </div>
  `;
}

function detailStat(label, value) {
  return `
    <div class="detail-stat">
      <span class="detail-label">${escapeHtml(label)}</span>
      <span class="detail-value">${escapeHtml(value)}</span>
    </div>
  `;
}

function featureByRouteId(routeId) {
  if (!routesGeoJson || !Array.isArray(routesGeoJson.features)) return null;
  return routesGeoJson.features.find((feature, index) => routeIdFor(feature, index) === routeId);
}

function updateListSelection(routeId) {
  routeListEl.querySelectorAll("[data-route-id]").forEach((button) => {
    const isSelected = button.dataset.routeId === routeId;
    button.classList.toggle("is-selected", isSelected);
    if (isSelected) button.scrollIntoView({ block: "nearest" });
  });
}

function updateCheckbox(routeId, visible) {
  const checkbox = routeListEl.querySelector(`[data-route-id="${escapeAttributeSelector(routeId)}"] .route-toggle`);
  if (checkbox) checkbox.checked = visible;
}

function escapeAttributeSelector(value) {
  return String(value).replace(/\\/g, "\\\\").replace(/"/g, '\\"');
}

function resetLayerStyles() {
  routeLayers.forEach((layer, routeId) => {
    layer.setStyle(styleForRoute(routeId, routeId === selectedRouteId ? "selected" : "default"));
    if (routeId === selectedRouteId) layer.bringToFront();
  });
}

function fitFeature(feature) {
  const props = propsFor(feature);

  if (Array.isArray(props.bbox) && props.bbox.length >= 4) {
    const [west, south, east, north] = props.bbox.map(Number);
    if ([west, south, east, north].every(Number.isFinite)) {
      map.fitBounds([[south, west], [north, east]], { padding: [28, 28], animate: false });
      return;
    }
  }

  const layer = routeLayers.get(routeIdFor(feature));
  if (layer && layer.getBounds && layer.getBounds().isValid()) {
    map.fitBounds(layer.getBounds(), { padding: [28, 28], animate: false });
  }
}

function setRouteVisible(routeId, visible) {
  const layer = routeLayers.get(routeId);
  if (!layer) return;

  routeVisibility.set(routeId, visible);
  updateCheckbox(routeId, visible);

  if (visible) {
    layer.addTo(map);
    resetLayerStyles();
    setStatus(`${visibleRouteCount()} routes visible`);
    updateToggleAllButton();
    return;
  }

  layer.closePopup();
  layer.removeFrom(map);
  setStatus(`${visibleRouteCount()} routes visible`);
  updateToggleAllButton();
}

function visibleRouteCount() {
  return [...routeVisibility.values()].filter(Boolean).length;
}

function updateToggleAllButton() {
  if (!toggleAllRoutesEl) return;
  const hasVisibleRoutes = visibleRouteCount() > 0;
  toggleAllRoutesEl.textContent = hasVisibleRoutes ? "Deselect all" : "Select all";
  toggleAllRoutesEl.setAttribute("aria-pressed", String(hasVisibleRoutes));
}

function setAllRoutesVisible(visible) {
  routeLayers.forEach((_layer, routeId) => setRouteVisible(routeId, visible));
  setStatus(visible ? `${visibleRouteCount()} routes visible` : "All routes hidden");
  updateToggleAllButton();
}

function selectRoute(routeId, options = {}) {
  const feature = featureByRouteId(routeId);
  if (!feature) return;

  if (options.showIfHidden && routeVisibility.get(routeId) === false) {
    setRouteVisible(routeId, true);
  }

  selectedRouteId = routeId;
  resetLayerStyles();
  updateListSelection(routeId);
  renderDetail(feature);

  const props = propsFor(feature);
  const layer = routeLayers.get(routeId);
  if (routeVisibility.get(routeId) !== false) {
    fitFeature(feature);
    if (layer) {
      layer.bindPopup(`<strong>${escapeHtml(routeName(props))}</strong><br>${escapeHtml(routeMeta(props))}`).openPopup();
    }
  }
  setStatus(`${routeName(props)} selected`);
}

function onEachRoute(feature, layer) {
  const routeId = routeIdFor(feature, routeLayers.size);
  routeLayers.set(routeId, layer);
  routeVisibility.set(routeId, true);

  layer.on({
    click: () => selectRoute(routeId),
    mouseover: () => {
      if (routeId !== selectedRouteId) layer.setStyle(styleForRoute(routeId, "hover"));
    },
    mouseout: () => {
      if (routeId !== selectedRouteId) layer.setStyle(styleForRoute(routeId));
    },
  });
}

function validFeatures(geojson) {
  return geojson && Array.isArray(geojson.features)
    ? geojson.features.filter((feature) => feature && feature.geometry)
    : [];
}

async function loadRoutes() {
  try {
    const response = await fetch(ROUTES_URL);
    if (!response.ok) throw new Error(`Route data returned ${response.status}`);

    routesGeoJson = await response.json();
    const features = validFeatures(routesGeoJson);

    renderRouteList(features);

    if (!features.length) {
      setStatus("No route features found");
      return;
    }

    L.geoJSON({ type: "FeatureCollection", features }, {
      style: (feature) => styleForRoute(routeIdFor(feature, 0)),
      onEachFeature: onEachRoute,
    }).addTo(map);

    const firstRouteId = routeIdFor(features[0], 0);
    selectRoute(firstRouteId);
    setStatus(`${features.length} routes loaded`);
    updateToggleAllButton();
  } catch (error) {
    console.error(error);
    routeListEl.innerHTML = '<p class="detail-muted">Could not load route data.</p>';
    routeDetailEl.className = "route-detail empty";
    routeDetailEl.textContent = "Check that data/processed/routes.geojson exists and contains valid GeoJSON.";
    setStatus("Route data unavailable");
  }
}

loadRoutes();
setupRouteResizer();

if (toggleAllRoutesEl) {
  toggleAllRoutesEl.addEventListener("click", () => {
    setAllRoutesVisible(visibleRouteCount() === 0);
  });
}
