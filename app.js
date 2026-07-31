(() => {
  "use strict";

  const API_MINIMUM = 40;
  const PAGE_SIZE = 24;
  const STUDIOS = ["全部", "迪士尼动画", "皮克斯", "漫威", "星球大战", "二十世纪影业", "真人电影", "纪录片"];
  const STUDIO_KEYWORDS = {
    "皮克斯": /pixar|toy story|cars|incredibles|finding nemo|inside out|coco|up\b|soul|turning red/i,
    "漫威": /marvel|avengers|iron man|thor|captain america|black panther|guardians|spider-man|deadpool|x-men/i,
    "星球大战": /star wars|mandalorian|andor|ahsoka|obi-wan|rogue one/i,
    "二十世纪影业": /20th century|twentieth century|avatar|alien|planet of the apes|free guy/i,
    "纪录片": /disneynature|documentary|nature|earth|ocean|chimpanzee|penguin/i,
    "真人电影": /live.action|pirates|maleficent|jungle cruise|tron|national treasure|mary poppins/i
  };

  const state = { movies: [], filtered: [], studio: "全部", query: "", sort: "featured", page: 1 };
  const $ = (selector) => document.querySelector(selector);
  const els = {
    grid: $("#movieGrid"), status: $("#status"), empty: $("#emptyState"),
    filters: $("#studioFilters"), search: $("#searchInput"), sort: $("#sortButton"),
    pagination: $("#pagination"), total: $("#totalCount"), visible: $("#visibleCount"),
    heroTotal: $("#heroTotal"), dialog: $("#movieDialog"), dialogContent: $("#dialogContent")
  };

  const text = (value, fallback = "") => String(value ?? fallback).trim();
  const safeYear = (value) => {
    const match = text(value).match(/\b(19|20)\d{2}\b/);
    return match ? Number(match[0]) : 0;
  };
  const unique = (items) => {
    const seen = new Set();
    const titlesWithKnownYears = new Set(
      items.filter((item) => Number(item.year) > 0).map((item) =>
        `${item.title_en || item.title_cn}`.toLowerCase().replace(/[^a-z0-9\u4e00-\u9fff]/g, "")
      )
    );
    return items.filter((item) => {
      const titleKey = `${item.title_en || item.title_cn}`.toLowerCase().replace(/[^a-z0-9\u4e00-\u9fff]/g, "");
      if (!Number(item.year) && titlesWithKnownYears.has(titleKey)) return false;
      const key = `${titleKey}:${item.year || "unknown"}`;
      if (!key || seen.has(key)) return false;
      seen.add(key);
      return true;
    });
  };
  const classifyStudio = (raw, title = "") => {
    const haystack = `${raw} ${title}`;
    if (STUDIOS.includes(raw)) return raw;
    for (const [studio, regex] of Object.entries(STUDIO_KEYWORDS)) {
      if (regex.test(haystack)) return studio;
    }
    return "迪士尼动画";
  };
  const normalize = (item, index = 0) => {
    const titleEn = text(item.title_en || item.title || item.name || item.originalTitle, "Unknown title");
    const titleCn = text(item.title_cn || item.chineseTitle, titleEn);
    const studioRaw = text(item.studio || item.production || item.type);
    const englishCredit = (value) => {
      const normalized = text(value);
      return !normalized || normalized === "资料暂缺" ? "Not available" : normalized;
    };
    return {
      id: text(item.id, `${titleEn}-${index}`),
      title_cn: titleCn,
      title_en: titleEn,
      year: safeYear(item.year || item.releaseDate || item.released || item.release_date),
      studio: classifyStudio(studioRaw, titleEn),
      poster_url: text(item.poster_url || item.poster || item.image || item.imageUrl),
      summary: text(item.summary || item.description || item.overview || item.plot, "暂无详细简介。"),
      director: text(item.director || item.directors, "资料暂缺"),
      cast: Array.isArray(item.cast) ? item.cast.join("、") : text(item.cast || item.actors || item.starring, "资料暂缺"),
      rating: Number.parseFloat(item.rating || item.imdbRating || item.score) || 0,
      runtime: text(item.runtime || item.duration, "—")
      ,source: text(item.source)
      ,source_url: text(item.source_url)
      ,featured_rank: Number(item.featured_rank) || 0
      ,title_cn_source: text(item.title_cn_source)
      ,director_cn: text(item.director_cn || item.director, "资料暂缺")
      ,director_en: englishCredit(item.director_en || item.director)
      ,cast_cn: text(item.cast_cn || item.cast, "资料暂缺")
      ,cast_en: englishCredit(item.cast_en || item.cast)
      ,summary_cn: text(item.summary_cn || item.summary, "暂无中文简介。")
      ,summary_en: text(item.summary_en || item.summary, "No English synopsis available.")
    };
  };

  async function fetchJSON(url, timeout = 8000) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeout);
    try {
      const response = await fetch(url, { signal: controller.signal });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      return await response.json();
    } finally { clearTimeout(timer); }
  }

  async function fetchDisneyCharacterFilms() {
    const films = new Set();
    let url = "https://api.disneyapi.dev/character?page=1&pageSize=100";
    for (let page = 0; page < 3 && url; page += 1) {
      const payload = await fetchJSON(url);
      const characters = Array.isArray(payload.data) ? payload.data : [];
      characters.forEach((character) => {
        [...(character.films || []), ...(character.tvShows || [])].forEach((title) => films.add(title));
      });
      url = typeof payload.info?.nextPage === "string" ? payload.info.nextPage : null;
    }
    return [...films].map((title, index) => normalize({
      id: `disney-${index}`, title_en: title, title_cn: title,
      studio: classifyStudio("", title), summary: "来自 Disney API 的角色关联影视作品。"
    }, index));
  }

  async function fetchDisneyMoviesAPI() {
    const payload = await fetchJSON("https://apidisneymovies.bsite.net/api/v1/movies/all?details=true");
    const list = Array.isArray(payload) ? payload : (payload.movies || payload.data || []);
    return list.map(normalize);
  }

  async function loadLocal() {
    if (location.protocol !== "file:") {
      try {
        const payload = await fetchJSON("data/movies.json", 4000);
        if (Array.isArray(payload) && payload.length) return payload.map(normalize);
      } catch (error) {
        console.warn("JSON fallback unavailable; using embedded offline mirror.", error.message);
      }
    }
    return (window.__LOCAL_MOVIES__ || []).map(normalize);
  }

  async function loadMovies() {
    const local = await loadLocal();
    if (local.length) {
      state.movies = unique(local);
      showStatus("loading", "本地片库已就绪", `已先载入 ${local.length} 部精选作品，正在尝试同步公开数据源…`, true);
      applyFilters();
    }
    let apiMovies = [];
    const failures = [];
    try {
      apiMovies = await fetchDisneyCharacterFilms();
      if (apiMovies.length < API_MINIMUM) throw new Error(`仅返回 ${apiMovies.length} 条`);
    } catch (error) {
      failures.push(`Disney API：${error.message}`);
      try {
        apiMovies = await fetchDisneyMoviesAPI();
        if (apiMovies.length < API_MINIMUM) throw new Error(`仅返回 ${apiMovies.length} 条`);
      } catch (backupError) {
        failures.push(`备用 API：${backupError.message}`);
        apiMovies = [];
      }
    }
    // The encyclopedia catalog is richer than the character API and contains
    // verified bilingual titles. Keep it authoritative once it is complete;
    // remote results remain useful only when the local catalog is small.
    const combined = local.length >= 800 ? local : [...apiMovies, ...local];
    state.movies = unique(combined).map((movie, index) => ({ ...movie, id: `${movie.id}-${index}` }));
    if (!state.movies.length) throw new Error("远程接口与本地数据均不可用");
    if (failures.length) {
      showStatus("warning", "已启用本地精选片库", `远程数据源暂时不可用；当前仍可浏览、搜索与筛选 ${state.movies.length} 部作品。`, false);
      setTimeout(() => { if (els.status.classList.contains("warning")) els.status.hidden = true; }, 6500);
    } else {
      els.status.hidden = true;
    }
    applyFilters();
  }

  function showStatus(type, title, message, spinner = false) {
    els.status.hidden = false;
    els.status.className = `status ${type}`;
    els.status.innerHTML = `${spinner ? '<span class="loader"></span>' : '<span aria-hidden="true">✦</span>'}<div><strong>${title}</strong><small>${message}</small></div>`;
  }

  function renderFilters() {
    els.filters.innerHTML = STUDIOS.map((studio) =>
      `<button class="filter-pill${studio === state.studio ? " active" : ""}" type="button" data-studio="${studio}">${studio}</button>`
    ).join("");
  }

  function applyFilters() {
    const query = state.query.toLocaleLowerCase();
    state.filtered = state.movies
      .filter((movie) => state.studio === "全部" || movie.studio === state.studio)
      .filter((movie) => `${movie.title_cn} ${movie.title_en}`.toLocaleLowerCase().includes(query))
      .sort((a, b) => {
        if (state.sort === "featured") {
          const rankA = a.featured_rank || Number.MAX_SAFE_INTEGER;
          const rankB = b.featured_rank || Number.MAX_SAFE_INTEGER;
          return rankA - rankB || b.year - a.year || a.title_en.localeCompare(b.title_en);
        }
        return state.sort === "desc"
          ? (b.year - a.year || a.title_en.localeCompare(b.title_en))
          : (a.year - b.year || a.title_en.localeCompare(b.title_en));
      });
    const maxPage = Math.max(1, Math.ceil(state.filtered.length / PAGE_SIZE));
    state.page = Math.min(state.page, maxPage);
    render();
  }

  function posterMarkup(movie, className = "") {
    const fallback = `<div class="poster-fallback">${escapeHTML(movie.title_cn)}</div>`;
    if (!movie.poster_url) return fallback;
    return `${fallback}<img class="${className}" src="${escapeHTML(movie.poster_url)}" alt="${escapeHTML(movie.title_cn)} 海报" loading="lazy" onerror="this.remove()">`;
  }

  function render() {
    const start = (state.page - 1) * PAGE_SIZE;
    const pageItems = state.filtered.slice(start, start + PAGE_SIZE);
    els.grid.innerHTML = pageItems.map((movie) => `
      <article class="movie-card" tabindex="0" role="button" data-id="${escapeHTML(movie.id)}" aria-label="查看《${escapeHTML(movie.title_cn)}》详情">
        <div class="poster">
          <span class="studio-tag">${escapeHTML(movie.studio)}</span>
          ${posterMarkup(movie)}
        </div>
        <div class="card-body">
          <span class="card-year">${movie.year || "年份未知"}</span>
          <h3>${escapeHTML(movie.title_cn)}</h3>
          <span class="en-title">${escapeHTML(movie.title_en)}</span>
          <div class="card-footer"><span class="rating">${movie.rating ? movie.rating.toFixed(1) : "暂无评分"}</span><span class="details-link">查看详情 →</span></div>
        </div>
      </article>
    `).join("");
    els.empty.hidden = state.filtered.length !== 0;
    els.visible.textContent = state.filtered.length.toLocaleString("zh-CN");
    els.total.textContent = state.movies.length.toLocaleString("zh-CN");
    els.heroTotal.textContent = state.movies.length.toLocaleString("zh-CN");
    renderPagination();
  }

  function renderPagination() {
    const pages = Math.ceil(state.filtered.length / PAGE_SIZE);
    if (pages <= 1) { els.pagination.innerHTML = ""; return; }
    const candidates = [...new Set([1, state.page - 1, state.page, state.page + 1, pages].filter((page) => page >= 1 && page <= pages))];
    let last = 0;
    const parts = [`<button class="page-button" data-page="${state.page - 1}" ${state.page === 1 ? "disabled" : ""} aria-label="上一页">‹</button>`];
    candidates.forEach((page) => {
      if (page - last > 1) parts.push("<span aria-hidden='true'>…</span>");
      parts.push(`<button class="page-button${page === state.page ? " active" : ""}" data-page="${page}">${page}</button>`);
      last = page;
    });
    parts.push(`<button class="page-button" data-page="${state.page + 1}" ${state.page === pages ? "disabled" : ""} aria-label="下一页">›</button>`);
    els.pagination.innerHTML = parts.join("");
  }

  function openMovie(id) {
    const movie = state.movies.find((item) => item.id === id);
    if (!movie) return;
    const director = movie.director_en && movie.director_en !== "Not available" ? movie.director_en : "Information not available";
    const cast = movie.cast_en && movie.cast_en !== "Not available" ? movie.cast_en : "Information not available";
    const synopsis = movie.summary_en && movie.summary_en !== "No English synopsis available." ? movie.summary_en : "An English synopsis has not been added yet.";
    const availableFields = [movie.year, movie.studio, movie.runtime !== "—", director !== "Information not available", cast !== "Information not available", synopsis !== "An English synopsis has not been added yet."].filter(Boolean).length;
    const completeness = Math.round((availableFields / 6) * 100);
    els.dialogContent.innerHTML = `
      <div class="dialog-layout">
        <div class="dialog-poster">${posterMarkup(movie)}</div>
        <div class="dialog-info">
          <p class="eyebrow"><span></span>${escapeHTML(movie.studio)}</p>
          <div class="dialog-title-row"><div><h2>${escapeHTML(movie.title_cn)}</h2><p class="dialog-en" lang="en">${escapeHTML(movie.title_en)}</p></div><span class="dialog-year">${movie.year || "—"}</span></div>
          <dl class="movie-facts" lang="en">
            <div><dt>Director</dt><dd>${escapeHTML(director)}</dd></div>
            <div><dt>Cast / Voices</dt><dd>${escapeHTML(cast)}</dd></div>
            <div><dt>Studio</dt><dd>${escapeHTML(movie.studio)}</dd></div>
            <div><dt>Runtime</dt><dd>${escapeHTML(movie.runtime)}</dd></div>
            <div><dt>Rating</dt><dd>${movie.rating ? `★ ${movie.rating.toFixed(1)}` : "Not rated"}</dd></div>
          </dl>
          <section class="synopsis" aria-labelledby="synopsisTitle" lang="en"><div class="section-label-row"><h3 id="synopsisTitle">Synopsis</h3><span>${completeness}% record complete</span></div><p class="dialog-summary">${escapeHTML(synopsis)}</p></section>
          <div class="dialog-actions">${movie.source_url ? `<a class="source-link" href="${escapeHTML(movie.source_url)}" target="_blank" rel="noopener noreferrer">View source on Wikipedia ↗</a>` : ""}${movie.title_cn_source === "machine_translation" ? "<span class=\"translation-note\">Chinese title is machine-assisted</span>" : ""}</div>
        </div>
      </div>`;
    els.dialog.showModal();
  }

  function escapeHTML(value) {
    return String(value ?? "").replace(/[&<>"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;" })[char]);
  }

  els.search.addEventListener("input", (event) => { state.query = event.target.value.trim(); state.page = 1; applyFilters(); });
  els.filters.addEventListener("click", (event) => {
    const button = event.target.closest("[data-studio]");
    if (!button) return;
    state.studio = button.dataset.studio; state.page = 1; renderFilters(); applyFilters();
  });
  els.sort.addEventListener("click", () => {
    state.sort = state.sort === "featured" ? "desc" : state.sort === "desc" ? "asc" : "featured";
    els.sort.querySelector("span").textContent =
      state.sort === "featured" ? "排序：精选推荐" : state.sort === "desc" ? "年份：新 → 旧" : "年份：旧 → 新";
    applyFilters();
  });
  els.pagination.addEventListener("click", (event) => {
    const button = event.target.closest("[data-page]");
    if (!button || button.disabled) return;
    state.page = Number(button.dataset.page); render();
    $("#library").scrollIntoView({ behavior: "smooth", block: "start" });
  });
  els.grid.addEventListener("click", (event) => { const card = event.target.closest("[data-id]"); if (card) openMovie(card.dataset.id); });
  els.grid.addEventListener("keydown", (event) => { if (["Enter", " "].includes(event.key)) { event.preventDefault(); openMovie(event.target.closest("[data-id]")?.dataset.id); } });
  $(".dialog-close").addEventListener("click", () => els.dialog.close());
  els.dialog.addEventListener("click", (event) => { if (event.target === els.dialog) els.dialog.close(); });
  $("#backToTop").addEventListener("click", () => window.scrollTo({ top: 0, behavior: "smooth" }));
  document.addEventListener("keydown", (event) => {
    if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") { event.preventDefault(); els.search.focus(); }
  });

  renderFilters();
  loadMovies().catch((error) => {
    console.error(error);
    showStatus("error", "影片数据加载失败", "请通过本地服务器运行项目，或检查 data/movies.json 是否存在。", false);
  });
})();
