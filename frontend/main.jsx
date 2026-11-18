import React, { useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import { Plus, RefreshCw, Trash2, Rss, Newspaper, ExternalLink, AlertCircle, CheckCircle2, Clock3 } from "lucide-react";
import "./style.css";

const API = "/api";

function App() {
  const [feeds, setFeeds] = useState([]);
  const [articles, setArticles] = useState([]);
  const [url, setUrl] = useState("");
  const [days, setDays] = useState(7);
  const [selectedFeed, setSelectedFeed] = useState("all");
  const [loading, setLoading] = useState(false);
  const [adding, setAdding] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  async function request(path, options = {}) {
    const response = await fetch(`${API}${path}`, {
      headers: { "Content-Type": "application/json" },
      ...options,
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.detail || "Произошла ошибка запроса");
    return data;
  }

  async function loadFeeds() {
    const data = await request("/feeds");
    setFeeds(data);
  }

  async function loadArticles() {
    const query = new URLSearchParams({ days: String(days) });
    if (selectedFeed !== "all") query.set("feed_id", selectedFeed);
    const data = await request(`/articles?${query}`);
    setArticles(data);
  }

  async function refreshAll() {
    setLoading(true); setError(""); setNotice("");
    try {
      const result = await request("/feeds/refresh", { method: "POST" });
      await Promise.all([loadFeeds(), loadArticles()]);
      setNotice(`Обновление завершено. Новых публикаций: ${result.new_articles}.`);
      const failed = result.results.filter(x => x.error);
      if (failed.length) setError(`Не удалось обновить источников: ${failed.map(x => x.title).join(", ")}`);
    } catch (e) { setError(e.message); }
    finally { setLoading(false); }
  }

  async function addFeed(e) {
    e.preventDefault();
    if (!url.trim()) return;
    setAdding(true); setError(""); setNotice("");
    try {
      const result = await request("/feeds", { method: "POST", body: JSON.stringify({ url: url.trim() }) });
      setUrl("");
      await Promise.all([loadFeeds(), loadArticles()]);
      setNotice(`Источник «${result.title}» добавлен. Публикаций: ${result.article_count}.`);
    } catch (e) { setError(e.message); }
    finally { setAdding(false); }
  }

  async function deleteFeed(id) {
    if (!window.confirm("Удалить источник и все связанные с ним публикации?")) return;
    setError(""); setNotice("");
    try {
      await request(`/feeds/${id}`, { method: "DELETE" });
      if (String(id) === selectedFeed) setSelectedFeed("all");
      await Promise.all([loadFeeds(), loadArticles()]);
      setNotice("Источник удалён.");
    } catch (e) { setError(e.message); }
  }

  useEffect(() => { loadFeeds().catch(e => setError(e.message)); }, []);
  useEffect(() => { loadArticles().catch(e => setError(e.message)); }, [days, selectedFeed]);

  const totalArticles = useMemo(() => feeds.reduce((sum, f) => sum + f.article_count, 0), [feeds]);

  function dateLabel(value) {
    if (!value) return "Дата не указана";
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? "Дата не указана" : date.toLocaleString("ru-RU", { dateStyle: "medium", timeStyle: "short" });
  }

  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="brand"><div className="brand-icon"><Newspaper size={21}/></div><div><strong>Личные новости</strong><span>Ваш RSS-агрегатор</span></div></div>
        <button className="button primary" onClick={refreshAll} disabled={loading || feeds.length === 0}>
          <RefreshCw size={16} className={loading ? "spin" : ""}/>{loading ? "Обновляем…" : "Обновить новости"}
        </button>
      </header>

      <main className="layout">
        <aside className="sidebar">
          <section className="panel add-panel">
            <div className="section-heading"><Rss size={18}/><h2>Источники</h2></div>
            <form onSubmit={addFeed} className="add-form">
              <label htmlFor="feed-url">RSS-ссылка</label>
              <input id="feed-url" value={url} onChange={e => setUrl(e.target.value)} placeholder="https://example.com/feed.xml" />
              <button className="button primary full" disabled={adding || !url.trim()}><Plus size={16}/>{adding ? "Добавляем…" : "Добавить источник"}</button>
            </form>
            <div className="feed-summary"><span>{feeds.length} источников</span><span>{totalArticles} публикаций</span></div>
            <div className="feed-list">
              {feeds.length === 0 && <p className="muted empty-small">Добавьте первую RSS-ленту.</p>}
              {feeds.map(feed => (
                <div className={`feed-row ${String(feed.id) === selectedFeed ? "active" : ""}`} key={feed.id}>
                  <button className="feed-select" onClick={() => setSelectedFeed(String(feed.id))}>
                    <span className="feed-dot"></span><span className="feed-name">{feed.title}</span><small>{feed.article_count}</small>
                  </button>
                  <button className="icon-button delete" title="Удалить источник" onClick={() => deleteFeed(feed.id)}><Trash2 size={15}/></button>
                </div>
              ))}
            </div>
            {feeds.length > 0 && <button className="text-button" onClick={() => setSelectedFeed("all")}>Показать все источники</button>}
          </section>
          <div className="sidebar-note"><Clock3 size={15}/><span>Публикации сохраняются между запусками приложения.</span></div>
        </aside>

        <section className="content">
          <div className="page-heading">
            <div><div className="eyebrow">ЛЕНТА ПУБЛИКАЦИЙ</div><h1>Новости</h1><p>Свежие материалы из ваших источников в одном месте.</p></div>
            <div className="filters">
              <select value={days} onChange={e => setDays(Number(e.target.value))} aria-label="Период">
                <option value={1}>За 24 часа</option><option value={3}>За 3 дня</option><option value={7}>За 7 дней</option><option value={30}>За 30 дней</option><option value={90}>За 90 дней</option>
              </select>
            </div>
          </div>

          {error && <div className="alert error"><AlertCircle size={17}/><span>{error}</span></div>}
          {notice && <div className="alert success"><CheckCircle2 size={17}/><span>{notice}</span></div>}

          <div className="results-line"><span>{selectedFeed === "all" ? "Все источники" : feeds.find(f => String(f.id) === selectedFeed)?.title}</span><strong>{articles.length} публикаций</strong></div>
          {articles.length === 0 ? (
            <div className="empty-state"><div className="empty-icon"><Rss size={28}/></div><h3>Пока нет публикаций</h3><p>Добавьте RSS-источники и нажмите «Обновить новости».</p></div>
          ) : (
            <div className="article-list">
              {articles.map(article => (
                <article className="article-card" key={article.id}>
                  <div className="article-meta"><span className="source-pill">{article.feed_title}</span><span>{dateLabel(article.published_at)}</span></div>
                  <h2><a href={article.url} target="_blank" rel="noreferrer">{article.title}</a></h2>
                  {article.summary && <p>{article.summary}</p>}
                  <a className="article-link" href={article.url} target="_blank" rel="noreferrer">Открыть оригинал <ExternalLink size={13}/></a>
                </article>
              ))}
            </div>
          )}
        </section>
      </main>
      <footer>Personal News · Личный проект · RSS / Atom</footer>
    </div>
  );
}

createRoot(document.getElementById("root")).render(<App />);
