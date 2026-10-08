// Client-side paging for admin tables whose rows are server-rendered
// (player profile creatures / Auguments, trade market tables).
// Hides the rows outside the current page; the per-page choice (100-200) is
// remembered per table in localStorage.

const TABLE_PER_PAGE_MIN = 100;
const TABLE_PER_PAGE_MAX = 200;
const TABLE_PER_PAGE_OPTIONS = [100, 150, 200];

function makeTablePager(cfg) {
  const rows = Array.prototype.slice.call(document.querySelectorAll(cfg.rowClass));
  const perPageSelect = document.getElementById(cfg.perPageId);
  const prevBtn = document.getElementById(cfg.prevId);
  const nextBtn = document.getElementById(cfg.nextId);
  const pageInfo = document.getElementById(cfg.pageInfoId);
  const showing = document.getElementById(cfg.showingId);
  const master = document.getElementById(cfg.masterId);
  const storageKey = 'cwk.playerTable.' + cfg.name + '.perPage';

  let query = '';
  let page = 1;
  let perPage = cfg.defaultPerPage || TABLE_PER_PAGE_OPTIONS[0];
  try {
    const stored = parseInt(localStorage.getItem(storageKey), 10);
    if (TABLE_PER_PAGE_OPTIONS.indexOf(stored) !== -1) perPage = stored;
  } catch (e) { /* storage unavailable */ }
  if (perPageSelect) perPageSelect.value = String(perPage);

  function matches() {
    if (!query) return rows;
    return rows.filter(function (row) {
      const cell = row.querySelector(cfg.cellClass);
      return cell ? cell.textContent.toLowerCase().indexOf(query) !== -1 : false;
    });
  }

  function syncMaster(onPage) {
    if (!master) return;
    const checked = onPage.filter(function (row) {
      const cb = row.querySelector(cfg.cbClass);
      return cb && cb.checked;
    }).length;
    master.checked = onPage.length > 0 && checked === onPage.length;
    master.indeterminate = checked > 0 && checked < onPage.length;
  }

  function render() {
    const list = matches();
    const pages = Math.max(1, Math.ceil(list.length / perPage));
    if (page > pages) page = pages;
    if (page < 1) page = 1;
    const start = (page - 1) * perPage;
    const onPage = list.slice(start, start + perPage);
    const visible = new Set(onPage);
    rows.forEach(function (row) {
      row.style.display = visible.has(row) ? '' : 'none';
    });

    if (pageInfo) pageInfo.textContent = 'Page ' + page + ' of ' + pages;
    if (showing) {
      showing.textContent = list.length
        ? 'Showing ' + (start + 1) + '-' + (start + onPage.length) + ' of ' + list.length
        : (rows.length ? 'No matching rows' : '');
    }
    if (prevBtn) prevBtn.classList.toggle('hidden', page <= 1);
    if (nextBtn) nextBtn.classList.toggle('hidden', page >= pages);
    syncMaster(onPage);
  }

  if (perPageSelect) {
    perPageSelect.addEventListener('change', function () {
      const value = parseInt(perPageSelect.value, 10) || cfg.defaultPerPage || TABLE_PER_PAGE_MIN;
      perPage = Math.min(TABLE_PER_PAGE_MAX, Math.max(TABLE_PER_PAGE_MIN, value));
      page = 1;
      try { localStorage.setItem(storageKey, String(perPage)); } catch (e) {}
      render();
    });
  }
  if (prevBtn) {
    prevBtn.addEventListener('click', function () {
      if (page > 1) { page -= 1; render(); }
    });
  }
  if (nextBtn) {
    nextBtn.addEventListener('click', function () {
      page += 1;
      render();
    });
  }

  render();

  return {
    setQuery: function (value) {
      query = (value || '').toLowerCase().trim();
      page = 1;
      render();
    },
    sync: render,
  };
}
