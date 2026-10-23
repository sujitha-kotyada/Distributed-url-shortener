import React, { useCallback, useEffect, useState } from "react";
import { api, getStoredToken } from "./api";
import type { UrlItem, UrlStatsResponse, User } from "./types";

export function App(): React.JSX.Element {
  const [currentUser, setCurrentUser] = useState<User | null>(null);
  const [authModalOpen, setAuthModalOpen] = useState(false);
  const [authMode, setAuthMode] = useState<"login" | "register">("login");
  const [authEmail, setAuthEmail] = useState("");
  const [authPassword, setAuthPassword] = useState("");
  const [authError, setAuthError] = useState<string | null>(null);

  const [inputUrl, setInputUrl] = useState("");
  const [createLoading, setCreateLoading] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);
  const [createdUrl, setCreatedUrl] = useState<UrlItem | null>(null);
  const [copied, setCopied] = useState(false);

  const [urls, setUrls] = useState<UrlItem[]>([]);
  const [selectedCode, setSelectedCode] = useState<string | null>(null);
  const [stats, setStats] = useState<UrlStatsResponse | null>(null);
  const [statsLoading, setStatsLoading] = useState(false);
  const [statsInterval, setStatsInterval] = useState<"hour" | "day">("day");

  const handleSelectUrl = useCallback(async (code: string, interval = statsInterval): Promise<void> => {
    setSelectedCode(code);
    setStatsLoading(true);
    try {
      const res = await api.getUrlStats(code, 7, interval);
      setStats(res);
    } catch {
      setStats(null);
    } finally {
      setStatsLoading(false);
    }
  }, [statsInterval]);

  const loadUrls = useCallback(async (): Promise<void> => {
    try {
      const myUrls = await api.getMyUrls();
      setUrls(myUrls);
      if (myUrls.length > 0) {
        setSelectedCode((prev) => {
          if (!prev) {
            handleSelectUrl(myUrls[0].short_code);
            return myUrls[0].short_code;
          }
          return prev;
        });
      }
    } catch {
      // ignore
    }
  }, [handleSelectUrl]);

  // Check initial user login state
  useEffect(() => {
    if (getStoredToken()) {
      api
        .getMe()
        .then((user) => {
          setCurrentUser(user);
          loadUrls();
        })
        .catch(() => {
          api.logout();
          setCurrentUser(null);
        });
    }
  }, [loadUrls]);

  const handleCreateUrl = async (e: React.FormEvent): Promise<void> => {
    e.preventDefault();
    if (!inputUrl.trim()) return;
    setCreateLoading(true);
    setCreateError(null);
    setCreatedUrl(null);

    try {
      const res = await api.createUrl(inputUrl.trim());
      setCreatedUrl(res);
      setInputUrl("");
      if (currentUser) {
        setUrls((prev) => [res, ...prev]);
        handleSelectUrl(res.short_code);
      } else {
        setSelectedCode(res.short_code);
        handleSelectUrl(res.short_code);
      }
    } catch (err: any) {
      setCreateError(err.message || "Failed to create short URL.");
    } finally {
      setCreateLoading(false);
    }
  };

  const handleAuthSubmit = async (e: React.FormEvent): Promise<void> => {
    e.preventDefault();
    setAuthError(null);
    try {
      if (authMode === "register") {
        await api.register(authEmail, authPassword);
      }
      await api.login(authEmail, authPassword);
      const user = await api.getMe();
      setCurrentUser(user);
      setAuthModalOpen(false);
      setAuthEmail("");
      setAuthPassword("");
      loadUrls();
    } catch (err: any) {
      setAuthError(err.message || "Authentication failed.");
    }
  };

  const handleLogout = (): void => {
    api.logout();
    setCurrentUser(null);
    setUrls([]);
    setSelectedCode(null);
    setStats(null);
  };

  const handleCopyLink = (text: string): void => {
    navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const maxClickCount = stats?.clicks_by_period.reduce((max, p) => Math.max(max, p.count), 0) || 1;

  return (
    <div>
      {/* Header */}
      <header className="app-header">
        <div className="brand">
          <span>⚡ DistriLink</span>
          <span className="brand-badge">Distributed</span>
        </div>
        <div>
          {currentUser ? (
            <div style={{ display: "flex", alignItems: "center", gap: "1rem" }}>
              <span style={{ fontSize: "0.875rem", color: "var(--text-secondary)" }}>
                {currentUser.email}
              </span>
              <button className="btn btn-secondary btn-sm" onClick={handleLogout}>
                Log Out
              </button>
            </div>
          ) : (
            <button className="btn btn-primary btn-sm" onClick={() => setAuthModalOpen(true)}>
              Sign In / Register
            </button>
          )}
        </div>
      </header>

      {/* Main Container */}
      <main className="main-container">
        <section className="hero-section">
          <h1 className="hero-title">Distributed URL Shortener & Analytics</h1>
          <p className="hero-desc">
            Atomic PostgreSQL sequence allocation, Base62 encoding, Redis caching, and real-time asynchronous click streaming.
          </p>
        </section>

        {/* Shorten Box */}
        <div className="glass-card shorten-box">
          <form className="shorten-form" onSubmit={handleCreateUrl}>
            <input
              type="url"
              className="input-field"
              placeholder="Paste long destination URL (e.g. https://github.com/torvalds/linux)..."
              value={inputUrl}
              onChange={(e) => setInputUrl(e.target.value)}
              required
            />
            <button type="submit" className="btn btn-primary" disabled={createLoading}>
              {createLoading ? "Shortening..." : "Shorten URL"}
            </button>
          </form>

          {createError && <div className="alert-error" style={{ marginTop: "1rem" }}>{createError}</div>}

          {createdUrl && (
            <div className="alert-success" style={{ marginTop: "1rem", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <div>
                <strong>Short Link Created: </strong>
                <a href={createdUrl.short_url} target="_blank" rel="noreferrer" style={{ color: "var(--accent-cyan)", marginLeft: "0.5rem" }}>
                  {createdUrl.short_url}
                </a>
              </div>
              <button className="btn btn-secondary btn-sm" onClick={() => handleCopyLink(createdUrl.short_url)}>
                {copied ? "✓ Copied!" : "Copy Link"}
              </button>
            </div>
          )}
        </div>

        {/* Stats Overview Grid */}
        <div className="overview-grid">
          <div className="glass-card stat-card">
            <div className="stat-label">Total Links Shortened</div>
            <div className="stat-value" style={{ color: "var(--accent-cyan)" }}>
              {urls.length || (createdUrl ? 1 : 0)}
            </div>
          </div>
          <div className="glass-card stat-card">
            <div className="stat-label">Selected Link Total Clicks</div>
            <div className="stat-value" style={{ color: "var(--accent-emerald)" }}>
              {stats ? stats.total_clicks : 0}
            </div>
          </div>
          <div className="glass-card stat-card">
            <div className="stat-label">Ingestion Architecture</div>
            <div className="stat-value" style={{ fontSize: "1.25rem", color: "var(--text-primary)" }}>
              Redis Streams + PG
            </div>
          </div>
        </div>

        {/* Dashboard Main Grid */}
        <div className="dashboard-grid">
          {/* Column 1: Links List */}
          <div className="glass-card panel">
            <div className="panel-header">
              <h2 className="panel-title">Your Shortened Links</h2>
              <span style={{ fontSize: "0.8rem", color: "var(--text-muted)" }}>
                {currentUser ? `${urls.length} links` : "Sign in to save links"}
              </span>
            </div>

            {urls.length === 0 ? (
              <div style={{ textAlign: "center", padding: "2rem", color: "var(--text-muted)" }}>
                {currentUser
                  ? "No links yet. Shorten your first destination above!"
                  : "Sign in to manage persistent links and track click telemetry."}
              </div>
            ) : (
              <div>
                {urls.map((item) => (
                  <div
                    key={item.short_code}
                    className={`url-item ${selectedCode === item.short_code ? "active" : ""}`}
                    onClick={() => handleSelectUrl(item.short_code)}
                  >
                    <div>
                      <div className="url-short-link">{item.short_url}</div>
                      <div className="url-destination" title={item.original_url}>
                        {item.original_url}
                      </div>
                    </div>
                    <button
                      className="btn btn-secondary btn-sm"
                      onClick={(e) => {
                        e.stopPropagation();
                        handleCopyLink(item.short_url);
                      }}
                    >
                      Copy
                    </button>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Column 2: Analytics Inspector */}
          <div className="glass-card panel">
            <div className="panel-header">
              <h2 className="panel-title">Click Analytics & Telemetry</h2>
              {selectedCode && (
                <div style={{ display: "flex", gap: "0.5rem" }}>
                  <button
                    className={`btn btn-sm ${statsInterval === "hour" ? "btn-primary" : "btn-secondary"}`}
                    onClick={() => {
                      setStatsInterval("hour");
                      handleSelectUrl(selectedCode, "hour");
                    }}
                  >
                    Hourly
                  </button>
                  <button
                    className={`btn btn-sm ${statsInterval === "day" ? "btn-primary" : "btn-secondary"}`}
                    onClick={() => {
                      setStatsInterval("day");
                      handleSelectUrl(selectedCode, "day");
                    }}
                  >
                    Daily
                  </button>
                </div>
              )}
            </div>

            {statsLoading ? (
              <div style={{ textAlign: "center", padding: "3rem", color: "var(--text-muted)" }}>
                Loading telemetry data...
              </div>
            ) : !selectedCode ? (
              <div style={{ textAlign: "center", padding: "3rem", color: "var(--text-muted)" }}>
                Select a short link to inspect click performance.
              </div>
            ) : stats ? (
              <div>
                <div style={{ marginBottom: "1.25rem", padding: "0.75rem", background: "rgba(255,255,255,0.02)", borderRadius: "var(--radius-sm)" }}>
                  <div style={{ fontSize: "0.8rem", color: "var(--text-muted)" }}>Destination</div>
                  <div style={{ fontSize: "0.9rem", wordBreak: "break-all" }}>{stats.original_url}</div>
                </div>

                {/* Bar Chart Visualizer */}
                <h3 style={{ fontSize: "0.95rem", fontWeight: 600, color: "var(--text-secondary)" }}>
                  Clicks by Period ({statsInterval === "hour" ? "Last 7 Days Hourly" : "Last 7 Days Daily"})
                </h3>

                {stats.clicks_by_period.length === 0 ? (
                  <div style={{ textAlign: "center", padding: "2rem", color: "var(--text-muted)", fontSize: "0.85rem" }}>
                    No click telemetry recorded in this time range yet. Visit the short URL to generate events!
                  </div>
                ) : (
                  <div className="chart-container">
                    {stats.clicks_by_period.map((p, idx) => {
                      const heightPercent = Math.max(8, (p.count / maxClickCount) * 100);
                      const displayLabel = p.period.length > 10 ? p.period.slice(11, 16) : p.period.slice(5);
                      return (
                        <div key={idx} className="chart-bar-col" title={`${p.period}: ${p.count} clicks`}>
                          <span style={{ fontSize: "0.7rem", color: "var(--text-secondary)", marginBottom: "0.2rem" }}>
                            {p.count}
                          </span>
                          <div className="chart-bar" style={{ height: `${heightPercent}%` }} />
                          <span className="chart-label">{displayLabel}</span>
                        </div>
                      );
                    })}
                  </div>
                )}

                {/* Recent Events Table */}
                <h3 style={{ fontSize: "0.95rem", fontWeight: 600, color: "var(--text-secondary)", marginTop: "1.5rem", marginBottom: "0.75rem" }}>
                  Recent Ingested Click Events
                </h3>

                {stats.recent_events.length === 0 ? (
                  <div style={{ fontSize: "0.85rem", color: "var(--text-muted)" }}>No click events recorded yet.</div>
                ) : (
                  <div style={{ maxHeight: "220px", overflowY: "auto" }}>
                    <table className="events-table">
                      <thead>
                        <tr>
                          <th>Occurred (UTC)</th>
                          <th>Event ID</th>
                        </tr>
                      </thead>
                      <tbody>
                        {stats.recent_events.map((ev) => (
                          <tr key={ev.event_id}>
                            <td>{new Date(ev.occurred_at).toUTCString()}</td>
                            <td style={{ fontFamily: "monospace", fontSize: "0.75rem" }}>
                              {ev.event_id.slice(0, 18)}...
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>
            ) : (
              <div style={{ textAlign: "center", padding: "3rem", color: "var(--text-muted)" }}>
                No telemetry available.
              </div>
            )}
          </div>
        </div>
      </main>

      {/* Auth Modal */}
      {authModalOpen && (
        <div className="modal-overlay" onClick={() => setAuthModalOpen(false)}>
          <div className="glass-card modal-content" onClick={(e) => e.stopPropagation()}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "1.5rem" }}>
              <h2 style={{ fontSize: "1.25rem", fontWeight: 700 }}>
                {authMode === "login" ? "Sign In" : "Create Account"}
              </h2>
              <button
                style={{ background: "none", border: "none", color: "var(--text-muted)", fontSize: "1.5rem", cursor: "pointer" }}
                onClick={() => setAuthModalOpen(false)}
              >
                &times;
              </button>
            </div>

            {authError && <div className="alert-error">{authError}</div>}

            <form onSubmit={handleAuthSubmit}>
              <div style={{ marginBottom: "1rem" }}>
                <label style={{ display: "block", fontSize: "0.85rem", color: "var(--text-muted)", marginBottom: "0.4rem" }}>
                  Email Address
                </label>
                <input
                  type="email"
                  className="input-field"
                  style={{ width: "100%" }}
                  required
                  value={authEmail}
                  onChange={(e) => setAuthEmail(e.target.value)}
                />
              </div>

              <div style={{ marginBottom: "1.5rem" }}>
                <label style={{ display: "block", fontSize: "0.85rem", color: "var(--text-muted)", marginBottom: "0.4rem" }}>
                  Password
                </label>
                <input
                  type="password"
                  className="input-field"
                  style={{ width: "100%" }}
                  minLength={8}
                  required
                  value={authPassword}
                  onChange={(e) => setAuthPassword(e.target.value)}
                />
              </div>

              <button type="submit" className="btn btn-primary" style={{ width: "100%", marginBottom: "1rem" }}>
                {authMode === "login" ? "Sign In" : "Register"}
              </button>

              <div style={{ textAlign: "center", fontSize: "0.85rem", color: "var(--text-muted)" }}>
                {authMode === "login" ? "Don't have an account? " : "Already have an account? "}
                <button
                  type="button"
                  style={{ background: "none", border: "none", color: "var(--accent-cyan)", cursor: "pointer", fontWeight: 600 }}
                  onClick={() => {
                    setAuthMode(authMode === "login" ? "register" : "login");
                    setAuthError(null);
                  }}
                >
                  {authMode === "login" ? "Register now" : "Sign In"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}

export default App;
