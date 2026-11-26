// Drill-down grouping for the gallery: Type › Base model › your folders.
// Pure functions only (no DOM), so node can test them; gallery.js renders.
(function (root) {
  'use strict';

  const LEVEL_LABELS = ['Type', 'Base model'];
  const NAME_ORDER = new Intl.Collator(undefined, { sensitivity: 'base', numeric: true });

  // A model's place in the tree: [type, base model, ...folders below the base folder].
  function pathOf(model) {
    return [model.type || 'Unknown', model.base_model || 'Unknown', ...(model.group_path || [])];
  }

  function within(model, at) {
    const path = pathOf(model);
    return at.every((step, i) => path[i] === step);
  }

  function levelLabel(depth) {
    return LEVEL_LABELS[depth] || 'Folder';
  }

  // One level of the tree below `at`. A path that no longer exists (a filter
  // emptied it, a folder was renamed) falls back to its deepest existing part;
  // a level with a single group and no models of its own is skipped. Returns the
  // effective path (`at`) and how much of it the caller asked for (`asked`).
  function buildLevel(models, at) {
    const path = (at || []).slice();
    while (path.length && !models.some(m => within(m, path))) path.pop();
    const asked = path.length;
    for (;;) {
      const depth = path.length;
      const groups = new Map();
      const direct = [];
      models.forEach(m => {
        if (!within(m, path)) return;
        const p = pathOf(m);
        if (p.length > depth) {
          if (!groups.has(p[depth])) groups.set(p[depth], []);
          groups.get(p[depth]).push(m);
        } else {
          direct.push(m);
        }
      });
      if (groups.size === 1 && !direct.length) {
        path.push(groups.keys().next().value);
        continue;
      }
      return {
        at: path,
        asked,
        label: levelLabel(depth),
        groups: Array.from(groups, ([name, list]) => ({ name, models: list })),
        direct,
        total: direct.length + Array.from(groups.values()).reduce((n, l) => n + l.length, 0)
      };
    }
  }

  // The path one level up from what is shown: past every auto-skipped step, or
  // going "up" would land on the same level again.
  function parentPath(models, level) {
    const up = level.at.slice(0, -1);
    while (up.length && buildLevel(models, up).at.length >= level.at.length) up.pop();
    return up;
  }

  function dateValue(iso) {
    const t = iso ? Date.parse(iso) : NaN;
    return Number.isNaN(t) ? 0 : t;
  }

  function sortValue(model, sort) {
    switch (sort) {
      case 'downloads': return Number(model.stats && model.stats.downloads) || 0;
      case 'rating': return Number(model.stats && model.stats.rating) || 0;
      default: return dateValue(model[sort]);
    }
  }

  // Group order: by name, or by the group's best value of the active sort key
  // (newest-first sorts groups by their newest model).
  function sortGroups(groups, sort, dir) {
    const mul = dir === 'asc' ? 1 : -1;
    const byName = (a, b) => NAME_ORDER.compare(String(a.name), String(b.name));
    if (sort === 'name') return groups.slice().sort((a, b) => mul * byName(a, b));
    const best = new Map(groups.map(g => [g, Math.max(0, ...g.models.map(m => sortValue(m, sort)))]));
    return groups.slice().sort((a, b) => (best.get(a) - best.get(b)) * mul || byName(a, b));
  }

  const TILE_HEALTH = ['update', 'misplaced', 'duplicate', 'other_bases'];

  // What a group tile shows: count, size on disk, newest addition, health counts
  // and up to four previews (images before videos, newest first).
  function tileStats(models) {
    const health = {};
    TILE_HEALTH.forEach(f => { health[f] = 0; });
    let size = 0;
    let newest = '';
    models.forEach(m => {
      size += Number(m.file_size) || 0;
      if (m.file_modified && dateValue(m.file_modified) > dateValue(newest)) newest = m.file_modified;
      (m.health || []).forEach(f => { if (f in health) health[f] += 1; });
    });
    const withPreview = models.filter(m => m.preview_image_path)
      .sort((a, b) => (a.is_video === b.is_video ? 0 : a.is_video ? 1 : -1) ||
        dateValue(b.file_modified) - dateValue(a.file_modified));
    return { count: models.length, size, newest, health, previews: withPreview.slice(0, 4) };
  }

  function humanSize(bytes) {
    let v = Number(bytes) || 0;
    const units = ['B', 'KB', 'MB', 'GB', 'TB'];
    let i = 0;
    while (v >= 1024 && i < units.length - 1) { v /= 1024; i += 1; }
    return i < 2 ? `${Math.round(v)} ${units[i]}` : `${v.toFixed(1)} ${units[i]}`;
  }

  const api = { pathOf, within, levelLabel, buildLevel, parentPath, sortGroups, tileStats, humanSize, TILE_HEALTH };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  if (typeof window !== 'undefined') {
    window.CS = window.CS || {};
    window.CS.grouping = api;
  }
})(typeof globalThis !== 'undefined' ? globalThis : this);
