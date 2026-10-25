(function () {
  'use strict';

  var MOCK_MODE = new URLSearchParams(window.location.search).get('mock') === '1';
  var REAL_DEFAULT_LOCATION = { lat: 30.657, lon: 104.066, name: '成都天府广场' };
  var MOCK_DEFAULT_LOCATION = { lat: 30.2741, lon: 120.1551, name: '杭州西湖（Mock 演示坐标）' };
  var DEFAULT_LOCATION = MOCK_MODE ? MOCK_DEFAULT_LOCATION : REAL_DEFAULT_LOCATION;
  var DISCLOSURE = '本内容由 AI 生成，仅供参考，不承诺渔获。';
  var HISTORY_LIMIT = 10;
  var DEFAULT_RADIUS_KM = 50;
  var SPOT_LIMIT = 5;
  var SPOT_FETCH_LIMIT = 10;
  var IOS_INSTALL_HINT_KEY = 'fishagent.iosInstallHintDismissed';
  var standaloneQuery =
    typeof window.matchMedia === 'function'
      ? window.matchMedia('(display-mode: standalone)')
      : null;
  var deferredInstallPrompt = null;
  var AUTH_ERROR_CODES = ['UNAUTHORIZED', 'INVALID_TOKEN', 'TOKEN_EXPIRED'];
  var authRedirectPending = false;
  var TOOL_LABELS = { get_fish_activity: '鱼情分析', recommend_spots: '钓位推荐' };
  var IMPACT_LABELS = { positive: '利好', neutral: '中性', negative: '不利' };
  var BAND_CLASS = {
    '极佳': 'band-excellent',
    '良好': 'band-good',
    '一般': 'band-fair',
    '偏差': 'band-poor',
    '劝退': 'band-bad'
  };

  var state = {
    lat: DEFAULT_LOCATION.lat,
    lon: DEFAULT_LOCATION.lon,
    name: DEFAULT_LOCATION.name,
    sessionId: makeSessionId(),
    history: [],
    chatBusy: false,
    seq: 0,
    mockMode: MOCK_MODE,
    radiusKm: DEFAULT_RADIUS_KM,
    statusTimer: null,
    spotsHintTimer: null,
    spotsAll: [],
    spotsPage: 0,
    spotsPayload: null,
    spotsBusy: false
  };

  function $(id) {
    return document.getElementById(id);
  }

  function el(tag, className, text) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined && text !== null) node.textContent = String(text);
    return node;
  }

  function makeSessionId() {
    if (window.crypto && typeof window.crypto.randomUUID === 'function') {
      return 'web-' + window.crypto.randomUUID();
    }
    return 'web-' + Date.now().toString(36) + '-' + Math.random().toString(36).slice(2, 10);
  }

  function clamp(value, min, max) {
    return Math.min(max, Math.max(min, value));
  }

  function roundCoord(value) {
    return Math.round(value * 1e6) / 1e6;
  }

  function formatNum(value) {
    var number = Number(value);
    if (!Number.isFinite(number)) return '—';
    return Number.isInteger(number) ? String(number) : String(Math.round(number * 10) / 10);
  }

  function signed(value) {
    var number = Number(value);
    if (!Number.isFinite(number)) return '—';
    return (number > 0 ? '+' : '') + formatNum(number);
  }

  function formatDateTime(value, timeZone) {
    if (!value) return '';
    var date = new Date(value);
    if (Number.isNaN(date.getTime())) return '';
    return date.toLocaleString('zh-CN', {
      timeZone: timeZone || 'Asia/Shanghai',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      hour12: false
    });
  }

  function safeHttpUrl(value) {
    if (typeof value !== 'string' || !value) return null;
    try {
      var url = new URL(value, window.location.href);
      if (url.protocol === 'http:' || url.protocol === 'https:') return url.href;
    } catch (error) {
      return null;
    }
    return null;
  }

  function isAppleMobile() {
    var ua = navigator.userAgent || '';
    if (/iPhone|iPad|iPod/i.test(ua)) return true;
    return /Macintosh/i.test(ua) && navigator.maxTouchPoints > 1;
  }

  function isAndroidMobile() {
    return /Android/i.test(navigator.userAgent || '');
  }

  function amapAppUrl(spot) {
    var data = spot && typeof spot === 'object' ? spot : {};
    var entry = data.entry_location_gcj02 || data.location_gcj02 || {};
    var lat = Number(entry.lat);
    var lon = Number(entry.lon);
    if (!Number.isFinite(lat) || !Number.isFinite(lon)) return null;
    var params =
      'sourceApplication=FishAgent' +
      '&dlat=' + lat.toFixed(6) +
      '&dlon=' + lon.toFixed(6) +
      '&dname=' + encodeURIComponent(String(data.name || '钓位')) +
      '&dev=0&t=0';
    if (isAppleMobile()) return 'iosamap://path?' + params;
    if (isAndroidMobile()) return 'amapuri://route/plan/?' + params;
    return null;
  }

  function isStandalone() {
    if (standaloneQuery && standaloneQuery.matches) return true;
    return window.navigator.standalone === true;
  }

  function isIosSafari() {
    if (!isAppleMobile()) return false;
    return !/CriOS|FxiOS|EdgiOS|OPiOS/.test(navigator.userAgent || '');
  }

  function readSessionValue(key) {
    try {
      return window.sessionStorage.getItem(key);
    } catch (error) {
      return null;
    }
  }

  function writeSessionValue(key, value) {
    try {
      window.sessionStorage.setItem(key, value);
    } catch (error) {
      /* storage unavailable; the hint simply reappears next time */
    }
  }

  function syncPwaUi() {
    var installBtn = $('install-btn');
    if (installBtn) installBtn.hidden = isStandalone() || !deferredInstallPrompt;

    var hint = $('ios-install-hint');
    if (hint) {
      var dismissed = readSessionValue(IOS_INSTALL_HINT_KEY) === '1';
      hint.hidden = isStandalone() || !isIosSafari() || dismissed;
    }
  }

  function registerServiceWorker() {
    if (!('serviceWorker' in navigator) || !window.isSecureContext) return;
    navigator.serviceWorker.register('./sw.js').catch(function () {
      return null;
    });
  }

  function bindInstallPrompt() {
    window.addEventListener('beforeinstallprompt', function (event) {
      event.preventDefault();
      deferredInstallPrompt = event;
      syncPwaUi();
    });

    window.addEventListener('appinstalled', function () {
      deferredInstallPrompt = null;
      syncPwaUi();
      setStatus('已添加到主屏幕，可从桌面直接打开 FishAgent。', 'info', true);
    });

    var installBtn = $('install-btn');
    if (installBtn) {
      installBtn.addEventListener('click', function () {
        if (!deferredInstallPrompt) return;
        var promptEvent = deferredInstallPrompt;
        deferredInstallPrompt = null;
        syncPwaUi();
        promptEvent.prompt();
        if (promptEvent.userChoice && typeof promptEvent.userChoice.then === 'function') {
          promptEvent.userChoice.then(function (choice) {
            if (choice && choice.outcome === 'accepted') {
              setStatus('正在安装 FishAgent…', 'info', true);
            }
          });
        }
      });
    }

    var closeBtn = $('ios-install-close');
    if (closeBtn) {
      closeBtn.addEventListener('click', function () {
        writeSessionValue(IOS_INSTALL_HINT_KEY, '1');
        syncPwaUi();
      });
    }

    if (standaloneQuery) {
      var onModeChange = function () {
        syncPwaUi();
      };
      if (typeof standaloneQuery.addEventListener === 'function') {
        standaloneQuery.addEventListener('change', onModeChange);
      } else if (typeof standaloneQuery.addListener === 'function') {
        standaloneQuery.addListener(onModeChange);
      }
    }
  }

  function bindOfflineState() {
    var banner = $('offline-banner');

    function render() {
      var offline = navigator.onLine === false;
      if (banner) banner.hidden = !offline;
      var chatStatus = $('chat-status');
      if (chatStatus) chatStatus.classList.toggle('chat-status-offline', offline);
      var chatStatusText = $('chat-status-text');
      if (chatStatusText) chatStatusText.textContent = offline ? '离线' : '在线';
    }

    render();
    window.addEventListener('offline', render);
    window.addEventListener('online', function () {
      render();
      setStatus('网络已恢复，正在重新获取鱼情与钓位。', 'info', true);
      refreshAll();
    });
  }

  function initPwa() {
    registerServiceWorker();
    bindInstallPrompt();
    bindOfflineState();
    syncPwaUi();
  }

  function setStatus(message, type, autoHide) {
    var region = $('status-region');
    if (state.statusTimer) {
      clearTimeout(state.statusTimer);
      state.statusTimer = null;
    }
    if (!message) {
      region.hidden = true;
      region.textContent = '';
      return;
    }
    region.hidden = false;
    region.className = 'wrap status-region status-' + (type || 'info');
    region.textContent = message;
    if (autoHide) {
      state.statusTimer = setTimeout(function () {
        setStatus('');
      }, 5000);
    }
  }

  function setModeBadge(text) {
    var badge = $('mode-badge');
    if (!text) {
      badge.hidden = true;
      badge.textContent = '';
      return;
    }
    badge.hidden = false;
    badge.textContent = text;
  }

  function setGeoStatus(text) {
    $('geo-status').textContent = text || '';
  }

  function syncLocationUI() {
    $('lat-input').value = state.lat.toFixed(4);
    $('lon-input').value = state.lon.toFixed(4);
    $('location-summary').textContent =
      state.name + ' · ' + state.lat.toFixed(4) + ', ' + state.lon.toFixed(4);
  }

  function buildQuery(pathname, params) {
    var query = new URLSearchParams();
    Object.keys(params).forEach(function (key) {
      var value = params[key];
      if (value !== undefined && value !== null && value !== '') query.set(key, String(value));
    });
    return pathname + '?' + query.toString();
  }

  function extractErrorMessage(data, status) {
    if (data && data.detail) {
      if (typeof data.detail === 'string') return data.detail;
      if (Array.isArray(data.detail) && data.detail.length) {
        var first = data.detail[0];
        if (first && first.msg) return String(first.msg);
      }
      if (typeof data.detail === 'object' && data.detail.message) return String(data.detail.message);
    }
    return '请求失败（HTTP ' + status + '）';
  }

  function errorCode(data) {
    if (data && data.detail && typeof data.detail === 'object' && data.detail.code) {
      return String(data.detail.code);
    }
    return '';
  }

  function isPilotPath() {
    return window.location.pathname.indexOf('/pilot/') === 0;
  }

  function redirectToLogin() {
    if (authRedirectPending || isPilotPath()) return false;
    authRedirectPending = true;
    var next = window.location.pathname + window.location.search;
    window.location.assign('/pilot/login?next=' + encodeURIComponent(next));
    return true;
  }

  function parseRetryAfter(response) {
    var raw = response.headers.get('Retry-After');
    if (!raw) return null;
    var text = String(raw).trim();
    if (/^\d+$/.test(text)) {
      var seconds = Number(text);
      return seconds > 0 ? seconds : null;
    }
    var at = Date.parse(text);
    if (!Number.isNaN(at)) {
      var diff = Math.ceil((at - Date.now()) / 1000);
      return diff > 0 ? diff : null;
    }
    return null;
  }

  function rateLimitMessage(data, retryAfter) {
    var base = errorCode(data) === 'QUOTA_EXCEEDED' ? '今日额度已用完' : '请求过于频繁';
    if (retryAfter) return base + '，请 ' + retryAfter + ' 秒后重试。';
    return base + '，请稍后重试。';
  }

  async function requestJSON(path, options) {
    if (state.mockMode) return mockRequest(path, options || {});
    if (navigator.onLine === false) {
      throw new Error('当前处于离线状态，无法获取实时数据；请恢复网络后重试。');
    }
    var init = Object.assign({}, options || {});
    init.headers = Object.assign({ Accept: 'application/json' }, (options && options.headers) || {});
    var response = await fetch(path, init);
    var data = null;
    try {
      data = await response.json();
    } catch (error) {
      data = null;
    }
    if (!response.ok) {
      var code = errorCode(data);
      if (response.status === 401 && AUTH_ERROR_CODES.indexOf(code) !== -1) {
        var redirecting = redirectToLogin();
        var authError = new Error(
          redirecting ? '登录已过期，正在跳转登录页。' : extractErrorMessage(data, response.status)
        );
        authError.status = 401;
        authError.code = code;
        throw authError;
      }
      if (response.status === 429) {
        var retryAfter = parseRetryAfter(response);
        var rateError = new Error(rateLimitMessage(data, retryAfter));
        rateError.status = 429;
        rateError.code = code;
        rateError.retryAfter = retryAfter;
        throw rateError;
      }
      throw new Error(extractErrorMessage(data, response.status));
    }
    if (data === null) {
      throw new Error('服务返回了无法解析的响应。');
    }
    return data;
  }

  async function checkHealth() {
    try {
      var health = await requestJSON('/health');
      setModeBadge(health && health.mock_mode ? 'Mock 模式' : '在线数据');
    } catch (error) {
      setModeBadge('服务未连接');
      setStatus(
        navigator.onLine === false
          ? '当前处于离线状态，恢复网络后将自动重试。'
          : '无法连接后端服务，请先启动 FishAgent 后端后再刷新页面。',
        'error'
      );
    }
  }

  function refreshAll() {
    state.seq += 1;
    var seq = state.seq;
    state.spotsAll = [];
    state.spotsPage = 0;
    state.spotsPayload = null;
    state.spotsBusy = true;
    updateSpotsButton();
    renderActivityLoading();
    renderSpotsLoading();
    loadActivity(seq);
    loadSpots(seq);
  }

  async function loadActivity(seq) {
    var body = $('activity-body');
    body.setAttribute('aria-busy', 'true');
    try {
      var data = await requestJSON(
        buildQuery('/api/fish-activity', {
          lat: state.lat,
          lon: state.lon,
          location_name: state.name
        })
      );
      if (seq !== state.seq) return;
      renderActivity(data);
    } catch (error) {
      if (seq !== state.seq) return;
      renderActivityError(error);
    } finally {
      if (seq === state.seq) body.setAttribute('aria-busy', 'false');
    }
  }

  function requestSpots() {
    return requestJSON(
      buildQuery('/api/spots/recommend', {
        lat: state.lat,
        lon: state.lon,
        radius_km: state.radiusKm,
        limit: SPOT_FETCH_LIMIT
      })
    );
  }

  function applySpotsData(data) {
    var payload = data && typeof data === 'object' ? data : {};
    state.spotsPayload = payload;
    state.spotsAll = Array.isArray(payload.spots) ? payload.spots : [];
    state.spotsPage = 0;
    renderSpotsPage();
    updateSpotsButton();
  }

  function renderSpotsPage() {
    var payload = state.spotsPayload || {};
    var start = state.spotsPage * SPOT_LIMIT;
    var visible = state.spotsAll.slice(start, start + SPOT_LIMIT);
    var filtered = Object.assign({}, payload.filtered || {});
    filtered.returned = visible.length;
    renderSpots(Object.assign({}, payload, { spots: visible, filtered: filtered }));
  }

  function spotsPageCount() {
    if (!state.spotsAll.length) return 0;
    return Math.ceil(state.spotsAll.length / SPOT_LIMIT);
  }

  function updateSpotsButton() {
    var button = $('spots-refresh');
    if (!button) return;
    button.disabled = state.spotsBusy || state.spotsAll.length === 0;
    button.textContent = '换一批';
    button.setAttribute('aria-busy', state.spotsBusy ? 'true' : 'false');
  }

  async function loadSpots(seq) {
    var body = $('spots-body');
    body.setAttribute('aria-busy', 'true');
    try {
      var data = await requestSpots();
      if (seq !== state.seq) return;
      applySpotsData(data);
    } catch (error) {
      if (seq !== state.seq) return;
      state.spotsAll = [];
      renderSpotsError(error);
    } finally {
      if (seq === state.seq) {
        clearSpotsHint();
        state.spotsBusy = false;
        updateSpotsButton();
        body.setAttribute('aria-busy', 'false');
      }
    }
  }

  function handleSpotsRefresh() {
    if (state.spotsBusy || !state.spotsAll.length) return;
    var pages = spotsPageCount();
    if (pages <= 1) {
      setStatus('已展示全部推荐。', 'info', true);
      return;
    }
    if (state.spotsPage + 1 >= pages) {
      state.spotsPage = 0;
      renderSpotsPage();
      setStatus('已展示全部推荐，已回到第 1 批。', 'info', true);
      return;
    }
    state.spotsPage += 1;
    renderSpotsPage();
    setStatus('已换到下一批钓位。', 'info', true);
  }

  function clearSpotsHint() {
    if (state.spotsHintTimer) {
      clearTimeout(state.spotsHintTimer);
      state.spotsHintTimer = null;
    }
  }

  function loadingPlaceholder(text) {
    var box = el('div', 'placeholder');
    box.append(el('p', null, text));
    box.append(el('div', 'skeleton-line'));
    box.append(el('div', 'skeleton-line short'));
    return box;
  }

  function renderActivityLoading() {
    var body = $('activity-body');
    body.setAttribute('aria-busy', 'true');
    body.replaceChildren(loadingPlaceholder('正在分析当前鱼情…'));
  }

  function renderSpotsLoading() {
    var body = $('spots-body');
    clearSpotsHint();
    body.setAttribute('aria-busy', 'true');
    body.replaceChildren(loadingPlaceholder('正在筛选附近钓位…'));
    state.spotsHintTimer = setTimeout(function () {
      state.spotsHintTimer = null;
      if (body.getAttribute('aria-busy') !== 'true') return;
      var line = body.querySelector('.placeholder p');
      if (line) line.textContent = '正在规划车程，真实模式约需 20 秒';
    }, 3000);
  }

  function renderActivityError(error) {
    var body = $('activity-body');
    var box = el('div', 'empty');
    box.append(el('p', null, '鱼情分析暂时不可用'));
    box.append(el('p', 'hint', (error && error.message) || '请稍后重试。'));
    body.replaceChildren(box);
    body.setAttribute('aria-busy', 'false');
  }

  function renderSpotsError(error) {
    var body = $('spots-body');
    var box = el('div', 'empty');
    box.append(el('p', null, '钓位推荐暂时不可用'));
    box.append(el('p', 'hint', (error && error.message) || '请稍后重试。'));
    body.replaceChildren(box);
    body.setAttribute('aria-busy', 'false');
  }

  function renderActivity(data) {
    var body = $('activity-body');
    var fragment = document.createDocumentFragment();
    var activity = data && typeof data === 'object' ? data : {};
    var band = typeof activity.band === 'string' && activity.band ? activity.band : '待评估';
    var bandClass = BAND_CLASS[band] || 'band-fair';
    var score = clamp(Math.round(Number(activity.score) || 0), 0, 100);
    var timezone = activity.timezone || 'Asia/Shanghai';
    var generated = formatDateTime(activity.generated_at, timezone);

    var hero = el('div', 'score-hero');
    var ring = el('div', 'score-ring ' + bandClass);
    ring.style.setProperty('--score', String(score));
    var ringInner = el('div', 'score-ring-inner');
    ringInner.append(el('span', 'score-value', String(score)));
    ringInner.append(el('span', 'score-unit', '/100'));
    ring.append(ringInner);

    var copy = el('div', 'score-copy');
    var bandRow = el('div', 'band-row');
    bandRow.append(el('span', 'band-chip ' + bandClass, band));
    if (generated) bandRow.append(el('span', 'score-meta', generated + ' · ' + timezone));
    copy.append(bandRow);
    copy.append(el('p', 'score-recommendation', activity.recommendation || activity.advice || '暂无建议'));
    if (activity.advice && activity.recommendation && activity.advice !== activity.recommendation) {
      copy.append(el('p', 'score-advice', '档位建议：' + activity.advice));
    }
    hero.append(ring, copy);
    fragment.append(hero);

    var factors = Array.isArray(activity.factors) ? activity.factors : [];
    var topFactors =
      Array.isArray(activity.top_factors) && activity.top_factors.length
        ? activity.top_factors
        : factors.slice(0, 3);
    if (topFactors.length) {
      var factorBlock = el('div', 'block');
      var factorTitle = el('div', 'block-title');
      factorTitle.append(el('h3', null, '关键因子 Top 3'));
      factorTitle.append(el('span', 'hint', '分数越高越有利'));
      factorBlock.append(factorTitle);
      var topList = el('ul', 'factor-list');
      topFactors.forEach(function (factor) {
        topList.append(renderFactor(factor));
      });
      factorBlock.append(topList);
      if (factors.length > topFactors.length) {
        var details = el('details', 'factor-more');
        details.append(el('summary', null, '展开全部 ' + factors.length + ' 项因子明细'));
        var allList = el('ul', 'factor-list');
        factors.forEach(function (factor) {
          allList.append(renderFactor(factor));
        });
        details.append(allList);
        factorBlock.append(details);
      }
      fragment.append(factorBlock);
    }

    var infoGrid = el('div', 'info-grid');
    infoGrid.append(renderWindows(activity.best_windows));
    infoGrid.append(renderTextInfo('建议水深', activity.water_depth || '暂无建议'));
    infoGrid.append(renderSpecies(activity.suitable_species));
    fragment.append(infoGrid);

    if (Array.isArray(activity.alerts) && activity.alerts.length) {
      var alerts = el('div', 'alerts');
      alerts.append(el('h3', null, '提示与风险'));
      activity.alerts.forEach(function (alert) {
        var item = typeof alert === 'string' ? { message: alert, level: 'warning' } : alert || {};
        var level = ['danger', 'warning', 'info'].indexOf(item.level) !== -1 ? item.level : 'warning';
        var alertItem = el('div', 'alert-item alert-' + level);
        var alertHead = el('div', 'alert-head');
        if (item.code) alertHead.append(el('span', 'alert-code', String(item.code)));
        if (item.forced) alertHead.append(el('span', 'alert-forced', '强制提示'));
        alertItem.append(alertHead);
        alertItem.append(el('p', 'alert-msg', item.message || '请留意出钓安全。'));
        alerts.append(alertItem);
      });
      fragment.append(alerts);
    }

    var weatherNode = renderWeather(activity.weather_summary);
    if (weatherNode) fragment.append(weatherNode);

    var sources = Array.isArray(activity.data_sources) ? activity.data_sources.join(' · ') : '';
    var sourceText = sources ? '数据源：' + sources : '数据源：FishAgent 规则引擎';
    if (generated) sourceText += ' · 生成于 ' + generated + '（' + timezone + '）';
    sourceText += ' · 7 项因子满分 100';
    fragment.append(el('p', 'source-line', sourceText));
    fragment.append(el('p', 'ai-line', activity.ai_disclosure || DISCLOSURE));

    var pill = $('activity-mode-pill');
    if (sources.indexOf('Mock') !== -1) {
      pill.textContent = 'Mock 数据';
      pill.hidden = false;
    } else {
      pill.hidden = true;
    }

    body.replaceChildren(fragment);
    body.setAttribute('aria-busy', 'false');
  }

  function renderFactor(factor) {
    var item = factor && typeof factor === 'object' ? factor : {};
    var li = el('li', 'factor');
    var top = el('div', 'factor-top');
    var name = el('span', 'factor-name');
    if (item.code) name.append(el('span', 'factor-code', String(item.code)));
    name.append(document.createTextNode(String(item.name || '未命名因子')));
    if (item.impact) {
      name.append(
        el('span', 'factor-impact impact-' + item.impact, IMPACT_LABELS[item.impact] || String(item.impact))
      );
    }
    var score = Number(item.score) || 0;
    var maxScore = Number(item.max_score) || 0;
    top.append(name);
    top.append(el('span', 'factor-score', formatNum(score) + '/' + formatNum(maxScore)));
    li.append(top);

    var bar = el('div', 'factor-bar');
    var fill = el('span', 'impact-' + (item.impact || 'neutral'));
    fill.style.width = (maxScore > 0 ? clamp((score / maxScore) * 100, 0, 100) : 0).toFixed(1) + '%';
    bar.append(fill);
    li.append(bar);

    if (item.detail) li.append(el('p', 'factor-detail', String(item.detail)));
    return li;
  }

  function renderWindows(windows) {
    var item = el('div', 'info-item');
    item.append(el('span', 'info-label', '最佳时段'));
    var value = el('div', 'info-value');
    if (Array.isArray(windows) && windows.length) {
      var chips = el('div', 'chips');
      windows.forEach(function (windowItem) {
        if (!windowItem) return;
        var label = String(windowItem.start || '') + '–' + String(windowItem.end || '');
        if (windowItem.label) label += ' · ' + windowItem.label;
        chips.append(el('span', 'chip', label));
      });
      if (chips.childElementCount) value.append(chips);
      else value.textContent = '暂无明确窗口';
    } else {
      value.textContent = '暂无明确窗口';
    }
    item.append(value);
    return item;
  }

  function renderSpecies(species) {
    var item = el('div', 'info-item');
    item.append(el('span', 'info-label', '适配鱼种'));
    var value = el('div', 'info-value');
    if (Array.isArray(species) && species.length) {
      var chips = el('div', 'chips');
      species.forEach(function (name) {
        chips.append(el('span', 'chip', String(name)));
      });
      value.append(chips);
    } else {
      value.textContent = '通用建议';
    }
    item.append(value);
    return item;
  }

  function renderTextInfo(label, text) {
    var item = el('div', 'info-item');
    item.append(el('span', 'info-label', label));
    item.append(el('div', 'info-value', text));
    return item;
  }

  function renderWeather(weather) {
    if (!weather || typeof weather !== 'object') return null;
    var metrics = [];
    if (weather.pressure_msl !== undefined && weather.pressure_msl !== null) {
      metrics.push(['气压', formatNum(weather.pressure_msl) + ' hPa']);
    }
    if (weather.pressure_change_24h !== undefined && weather.pressure_change_24h !== null) {
      metrics.push(['24h 变压', signed(weather.pressure_change_24h) + ' hPa']);
    }
    if (weather.wind_level !== undefined || weather.wind_speed_ms !== undefined) {
      var wind = weather.wind_direction || '风向未知';
      if (weather.wind_level !== undefined && weather.wind_level !== null) wind += ' ' + formatNum(weather.wind_level) + ' 级';
      if (weather.wind_speed_ms !== undefined && weather.wind_speed_ms !== null) {
        wind += '（' + formatNum(weather.wind_speed_ms) + ' m/s）';
      }
      metrics.push(['风力', wind]);
    }
    if (weather.temperature !== undefined && weather.temperature !== null) {
      var temp = formatNum(weather.temperature) + '℃';
      if (weather.temperature_change_24h !== undefined && weather.temperature_change_24h !== null) {
        temp += ' · 24h ' + signed(weather.temperature_change_24h) + '℃';
      }
      metrics.push(['气温', temp]);
    }
    if (weather.precipitation_mm !== undefined && weather.precipitation_mm !== null) {
      metrics.push(['降水', formatNum(weather.precipitation_mm) + ' mm']);
    }
    if (weather.cloud_cover_pct !== undefined && weather.cloud_cover_pct !== null) {
      metrics.push(['云量', formatNum(weather.cloud_cover_pct) + '%']);
    }
    if (weather.sunrise || weather.sunset) {
      metrics.push(['日出 / 日落', (weather.sunrise || '--') + ' / ' + (weather.sunset || '--')]);
    }
    if (!metrics.length) return null;
    var grid = el('div', 'weather-strip');
    metrics.forEach(function (pair) {
      var metric = el('div', 'metric');
      metric.append(el('span', 'metric-label', pair[0]));
      metric.append(el('span', 'metric-value', pair[1]));
      grid.append(metric);
    });
    var block = el('div', 'block weather-block');
    var title = el('div', 'block-title');
    title.append(el('h3', null, '评分依据（非天气预报）'));
    title.append(el('span', 'hint', '仅当前因子数据'));
    block.append(title);
    block.append(grid);
    return block;
  }

  function renderSpots(data) {
    var body = $('spots-body');
    var fragment = document.createDocumentFragment();
    var payload = data && typeof data === 'object' ? data : {};
    var filtered = payload.filtered || {};
    var spots = Array.isArray(payload.spots) ? payload.spots : [];

    var summary = el('div', 'spots-summary');
    summary.append(el('span', null, '候选 ' + formatNum(filtered.total_candidates ?? spots.length) + ' 个'));
    if (filtered.forbidden !== undefined) {
      summary.append(el('span', null, '禁钓排除 ' + formatNum(filtered.forbidden)));
    }
    if (filtered.over_two_hours !== undefined) {
      summary.append(el('span', null, '往返超 2 小时 ' + formatNum(filtered.over_two_hours)));
    }
    if (filtered.eligible !== undefined) {
      summary.append(el('span', null, '符合条件 ' + formatNum(filtered.eligible)));
    }
    if (filtered.truncated_by_limit !== undefined && Number(filtered.truncated_by_limit) > 0) {
      summary.append(el('span', null, '按限额截断 ' + formatNum(filtered.truncated_by_limit)));
    }
    if (Number(filtered.unevaluated) > 0) {
      summary.append(
        el('span', null, '未评估 ' + formatNum(filtered.unevaluated) + '（超出本轮预算）')
      );
    }
    fragment.append(summary);

    if (!spots.length) {
      fragment.append(el('div', 'empty', '附近暂未找到满足条件的钓位，可尝试更换位置后重试。'));
      body.replaceChildren(fragment);
      body.setAttribute('aria-busy', 'false');
      return;
    }

    var list = el('ol', 'spot-list');
    spots.forEach(function (spot, index) {
      list.append(renderSpot(spot, index));
    });
    fragment.append(list);

    var meta = payload.meta || {};
    var notes = ['去程与回程分别估算，合计不超过 2 小时', '已排除禁钓候选'];
    if (meta.radius_km) notes.push('搜索半径 ' + formatNum(meta.radius_km) + ' km');
    if (meta.traffic_basis === 'baseline_estimate') notes.push('车程为基线估计，实际以导航为准');
    if (filtered.returned !== undefined) notes.push('展示 ' + formatNum(filtered.returned) + ' 个');
    var generatedSpots = formatDateTime(meta.generated_at, 'Asia/Shanghai');
    if (generatedSpots) notes.push('生成于 ' + generatedSpots + '（Asia/Shanghai）');
    if (meta.mock_mode) notes.push('Mock 数据');
    fragment.append(el('p', 'source-line', notes.join(' · ')));

    body.replaceChildren(fragment);
    body.setAttribute('aria-busy', 'false');
  }

  function renderSpot(spot, index) {
    var data = spot && typeof spot === 'object' ? spot : {};
    var li = el('li', 'spot');

    var head = el('div', 'spot-head');
    head.append(el('span', 'spot-rank', String(index + 1)));
    var title = el('div', 'spot-title');
    title.append(el('h3', null, data.name || '未命名钓位'));
    var subParts = [];
    if (data.water_type) subParts.push(String(data.water_type));
    if (data.address) subParts.push(String(data.address));
    title.append(el('p', 'spot-sub', subParts.join(' · ') || '水域信息待补充'));

    var score = el('div', 'spot-score');
    score.append(document.createTextNode(formatNum(data.total_score)));
    score.append(el('small', null, '综合分'));
    head.append(title, score);
    li.append(head);

    var metrics = el('div', 'spot-metrics');
    if (data.distance_m !== undefined && data.distance_m !== null) {
      metrics.append(el('span', null, '距离 ' + formatNum(Number(data.distance_m) / 1000) + ' km'));
    }
    if (data.drive_minutes_one_way !== undefined && data.drive_minutes_one_way !== null) {
      metrics.append(el('span', null, '单程 ' + formatNum(data.drive_minutes_one_way) + ' 分钟'));
    }
    if (data.drive_seconds_round_trip !== undefined && data.drive_seconds_round_trip !== null) {
      metrics.append(
        el('span', 'metric-highlight', '往返 ' + Math.round(Number(data.drive_seconds_round_trip) / 60) + ' 分钟')
      );
    }
    if (metrics.childElementCount) li.append(metrics);

    if (Array.isArray(data.reasons) && data.reasons.length) {
      var reasons = el('ul', 'reasons');
      data.reasons.slice(0, 4).forEach(function (reason) {
        reasons.append(el('li', null, String(reason)));
      });
      li.append(reasons);
    }

    if (data.entry_precision === 'center_fallback') {
      li.append(el('p', 'precision-warn', '该钓位缺少入口坐标，已回退至中心点，端点精度较低。'));
    }

    var actions = el('div', 'spot-actions');
    var navUrl = safeHttpUrl(data.navigation_url);
    var appUrl = amapAppUrl(data);
    var nav = el('div', 'spot-nav');
    if (appUrl) {
      var appLink = el('a', 'btn btn-ghost', '打开高德导航');
      appLink.href = appUrl;
      nav.append(appLink);
      if (navUrl) {
        var fallback = el('a', 'nav-fallback', '未安装高德？使用网页版');
        fallback.href = navUrl;
        fallback.target = '_blank';
        fallback.rel = 'noopener noreferrer';
        nav.append(fallback);
      }
    } else if (navUrl) {
      var link = el('a', 'btn btn-ghost', '打开高德导航');
      link.href = navUrl;
      link.target = '_blank';
      link.rel = 'noopener noreferrer';
      nav.append(link);
    } else {
      nav.append(el('span', 'spot-note', '暂无导航链接'));
    }
    actions.append(nav);
    actions.append(el('span', 'spot-note', '出行前请确认当地禁钓规定'));
    li.append(actions);

    return li;
  }

  function appendChatMessage(role, text, options) {
    var config = options || {};
    var list = $('chat-messages');
    var wrapper = el('div', 'msg ' + (role === 'user' ? 'msg-user' : 'msg-assistant'));
    wrapper.append(el('div', 'msg-bubble', text));

    if (role !== 'user') {
      var meta = el('div', 'msg-meta');
      meta.append(el('span', 'mini-badge', config.error ? '服务提示' : 'AI 生成'));
      if (config.error) meta.append(el('span', 'mini-badge mini-badge-error', '请求失败'));
      if (config.mode) {
        meta.append(el('span', 'mini-badge mini-badge-soft', config.mode === 'fallback' ? '规则兜底' : 'LLM'));
      }
      var calls = Array.isArray(config.toolCalls) ? config.toolCalls : [];
      calls.forEach(function (call) {
        var label = TOOL_LABELS[call.name] || '工具调用';
        var ok = call.status === 'ok';
        meta.append(el('span', 'mini-badge ' + (ok ? 'mini-badge-soft' : 'mini-badge-error'), label + ' · ' + (ok ? '完成' : '失败')));
      });
      wrapper.append(meta);
    }

    list.append(wrapper);
    list.scrollTop = list.scrollHeight;
    return wrapper;
  }

  function appendTyping() {
    var list = $('chat-messages');
    var wrapper = el('div', 'msg msg-assistant msg-typing');
    var bubble = el('div', 'msg-bubble');
    bubble.setAttribute('aria-label', '助手正在输入');
    for (var i = 0; i < 3; i += 1) bubble.append(el('span', 'typing-dot'));
    wrapper.append(bubble);
    list.append(wrapper);
    list.scrollTop = list.scrollHeight;
    return wrapper;
  }

  function updateChatControls() {
    $('chat-send').disabled = state.chatBusy;
    $('chat-input').disabled = state.chatBusy;
  }

  async function sendMessage(rawText) {
    var input = $('chat-input');
    var message = String(rawText !== undefined && rawText !== null ? rawText : input.value).trim();
    if (!message || state.chatBusy) return;
    if (message.length > 500) {
      setStatus('问题请控制在 500 字以内。', 'error');
      return;
    }

    state.chatBusy = true;
    input.value = '';
    updateChatControls();
    appendChatMessage('user', message);
    var typing = appendTyping();

    var history = state.history.slice(-HISTORY_LIMIT).map(function (item) {
      return { role: item.role, content: item.content };
    });
    state.history.push({ role: 'user', content: message });

    try {
      var data = await requestJSON('/api/agent/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          message: message,
          location: { lat: state.lat, lon: state.lon, name: state.name },
          session_id: state.sessionId,
          history: history
        })
      });
      typing.remove();
      var reply =
        data && typeof data.reply === 'string' && data.reply.trim()
          ? data.reply.trim()
          : '抱歉，我暂时没有生成有效回复，请稍后再试。';
      appendChatMessage('assistant', reply, {
        mode: data && data.mode,
        toolCalls: data && data.tool_calls
      });
      state.history.push({ role: 'assistant', content: reply });
      if (state.history.length > HISTORY_LIMIT * 2) {
        state.history = state.history.slice(-HISTORY_LIMIT * 2);
      }
      if (data && data.fish_activity && typeof data.fish_activity === 'object') {
        renderActivity(data.fish_activity);
      }
      if (data && data.spots && typeof data.spots === 'object') {
        applySpotsData(data.spots);
      }
    } catch (error) {
      typing.remove();
      state.history.pop();
      var chatNotice =
        error && error.status === 429 && error.message
          ? error.message
          : '抱歉，服务暂时不可用。请确认后端已启动后再试。';
      appendChatMessage('assistant', chatNotice, { error: true });
      setStatus('对话请求失败：' + ((error && error.message) || '未知错误'), 'error');
    } finally {
      state.chatBusy = false;
      updateChatControls();
      input.focus();
    }
  }

  function handleRadiusChange() {
    var radius = Number($('radius-select').value);
    if (radius !== 50 && radius !== 100) return;
    if (radius === state.radiusKm) return;
    state.radiusKm = radius;
    setStatus('搜索半径已切换为 ' + radius + ' km，正在重新分析。', 'info', true);
    refreshAll();
  }

  function handleManualLocation(event) {
    event.preventDefault();
    var latRaw = $('lat-input').value.trim();
    var lonRaw = $('lon-input').value.trim();
    var lat = Number(latRaw);
    var lon = Number(lonRaw);
    if (!latRaw || !lonRaw || !Number.isFinite(lat) || !Number.isFinite(lon)) {
      setStatus('请输入有效的经纬度数字。', 'error');
      return;
    }
    if (lat < -90 || lat > 90) {
      setStatus('纬度需在 -90 到 90 之间。', 'error');
      return;
    }
    if (lon < -180 || lon > 180) {
      setStatus('经度需在 -180 到 180 之间。', 'error');
      return;
    }
    state.lat = roundCoord(lat);
    state.lon = roundCoord(lon);
    state.name = '手动坐标';
    syncLocationUI();
    setGeoStatus('');
    setStatus('位置已更新，正在重新分析。', 'info', true);
    refreshAll();
  }

  function handleGeolocation() {
    if (!('geolocation' in navigator)) {
      setStatus('当前浏览器不支持定位，请手动输入坐标。', 'error');
      return;
    }
    var button = $('geo-btn');
    button.disabled = true;
    setGeoStatus('正在获取定位…');
    navigator.geolocation.getCurrentPosition(
      function (position) {
        button.disabled = false;
        var lat = roundCoord(position.coords.latitude);
        var lon = roundCoord(position.coords.longitude);
        var accuracy = Math.round(Number(position.coords.accuracy) || 0);
        state.lat = lat;
        state.lon = lon;
        state.name = '我的位置';
        syncLocationUI();
        setGeoStatus(accuracy ? '定位成功，精度约 ' + accuracy + ' 米（WGS84）。' : '定位成功（WGS84）。');
        setStatus('已使用你的定位，正在分析鱼情与钓位。', 'info', true);
        refreshAll();
      },
      function (error) {
        button.disabled = false;
        var message = '定位失败，请手动输入坐标。';
        if (error && error.code === 1) message = '定位权限被拒绝，请允许权限或手动输入坐标。';
        else if (error && error.code === 2) message = '当前无法获取位置，请手动输入坐标。';
        else if (error && error.code === 3) message = '定位超时，请重试或手动输入坐标。';
        setGeoStatus(message);
        setStatus(message, 'error');
      },
      { enableHighAccuracy: true, timeout: 10000, maximumAge: 60000 }
    );
  }

  function bindEvents() {
    $('coord-form').addEventListener('submit', handleManualLocation);
    $('geo-btn').addEventListener('click', handleGeolocation);
    $('radius-select').addEventListener('change', handleRadiusChange);
    $('spots-refresh').addEventListener('click', handleSpotsRefresh);
    $('chat-form').addEventListener('submit', function (event) {
      event.preventDefault();
      sendMessage();
    });
    document.querySelectorAll('[data-question]').forEach(function (button) {
      button.addEventListener('click', function () {
        sendMessage(button.getAttribute('data-question'));
      });
    });
  }

  function mockRequest(path, options) {
    var url = new URL(path, window.location.href);
    if (url.pathname === '/health') {
      return Promise.resolve({ status: 'ok', version: '0.1.0', mock_mode: true });
    }
    if (url.pathname === '/api/fish-activity') {
      return Promise.resolve(makeMockFishActivity());
    }
    if (url.pathname === '/api/spots/recommend') {
      return Promise.resolve(makeMockSpots());
    }
    if (url.pathname === '/api/agent/chat') {
      var payload = {};
      try {
        payload = JSON.parse((options && options.body) || '{}');
      } catch (error) {
        payload = {};
      }
      return Promise.resolve(makeMockChat(payload.message || ''));
    }
    return Promise.reject(new Error('Mock 未实现接口：' + url.pathname));
  }

  function makeMockFishActivity() {
    var generatedAt = new Date().toISOString();
    var factors = [
      {
        code: 'F1',
        name: '气压变化趋势',
        score: 25,
        max_score: 25,
        impact: 'positive',
        detail: '未来 24h 气压缓降 4.2hPa，近 3h -0.8hPa，鱼口活跃信号'
      },
      {
        code: 'F2',
        name: '气压绝对值',
        score: 12,
        max_score: 20,
        impact: 'neutral',
        detail: '海平面气压 1012hPa，缺少当地 30 天分布，按兜底区间评估'
      },
      {
        code: 'F3',
        name: '气温与变温',
        score: 10,
        max_score: 15,
        impact: 'neutral',
        detail: '日均温 22℃，24h 变温 4.0℃，昼夜温差 9℃'
      },
      {
        code: 'F4',
        name: '风力风向',
        score: 8,
        max_score: 15,
        impact: 'neutral',
        detail: '东南风 4 级（6.2m/s），风力稍大'
      },
      {
        code: 'F5',
        name: '降水与降水窗口',
        score: 5,
        max_score: 10,
        impact: 'negative',
        detail: '连续晴热 4 天，水体溶氧承压'
      },
      {
        code: 'F6',
        name: '季节 / 时段',
        score: 7,
        max_score: 10,
        impact: 'neutral',
        detail: '秋季其他时段，临近日落窗口（17:48）'
      },
      {
        code: 'F7',
        name: '云量 / 光照',
        score: 1,
        max_score: 5,
        impact: 'negative',
        detail: '云量 85%，阴天光照偏弱'
      }
    ];
    return {
      score: 68,
      band: '一般',
      advice: '有机会，建议挑时段',
      recommendation: '有机会，建议挑时段，优先日出窗口',
      factors: factors,
      top_factors: [factors[0], factors[5], factors[2]],
      best_windows: [
        { start: '05:30', end: '08:00', label: '日出窗口' },
        { start: '16:30', end: '18:30', label: '日落窗口' }
      ],
      water_depth: '先钓 1.5–2m 浅滩，无口则转 3m 以上',
      suitable_species: ['鲫鱼', '鲤鱼'],
      alerts: [
        {
          code: 'DATA_FALLBACK',
          level: 'info',
          message: 'F2 缺少当地 30 天气压分布，已按 1005–1020hPa 兜底区间评估。',
          forced: false
        }
      ],
      weather_summary: {
        pressure_msl: 1012.0,
        pressure_change_24h: -4.2,
        pressure_change_3h: -0.8,
        pressure_change_6h: -1.5,
        temperature: 22.0,
        temperature_change_24h: 4.0,
        diurnal_range: 9.0,
        wind_speed_ms: 6.2,
        wind_level: 4,
        wind_direction: '东南风',
        precipitation_mm: 0.0,
        cloud_cover_pct: 85,
        sunrise: '06:12',
        sunset: '17:48',
        is_thunderstorm: false
      },
      data_sources: ['Open-Meteo（Mock）', 'FishAgent 规则引擎 v1'],
      ai_disclosure: '本结论由 AI 辅助生成，仅供参考，不承诺渔获。',
      timezone: 'Asia/Shanghai',
      generated_at: generatedAt
    };
  }

  function makeMockSpots() {
    var generatedAt = new Date().toISOString();
    var allSpots = [
        {
          id: 'mock_spot_001',
          name: '青山水库',
          water_type: '水库',
          address: '示例地址 · 临安区',
          location_gcj02: { lat: 30.35, lon: 120.02 },
          entry_location_gcj02: { lat: 30.349, lon: 120.021 },
          entry_precision: 'entr_location',
          distance_m: 42300,
          drive_seconds_out: 2700,
          drive_seconds_back: 3000,
          drive_seconds_round_trip: 5700,
          drive_minutes_one_way: 45,
          fish_score: 68,
          total_score: 81.5,
          reasons: ['气压缓降，鱼口活跃', '往返约 95 分钟', '水库适配鲫鱼'],
          navigation_url: 'https://uri.amap.com/marker?position=120.021,30.349&name=青山水库'
        },
        {
          id: 'mock_spot_002',
          name: '镜湖湿地野塘',
          water_type: '野塘',
          address: '示例地址 · 余杭区',
          location_gcj02: { lat: 30.31, lon: 120.12 },
          entry_location_gcj02: { lat: 30.309, lon: 120.121 },
          entry_precision: 'entr_location',
          distance_m: 18600,
          drive_seconds_out: 1500,
          drive_seconds_back: 1680,
          drive_seconds_round_trip: 3180,
          drive_minutes_one_way: 25,
          fish_score: 64,
          total_score: 76.2,
          reasons: ['往返约 53 分钟', '野塘适配鲫鱼', '临近浅滩结构'],
          navigation_url: 'https://uri.amap.com/marker?position=120.121,30.309&name=镜湖湿地野塘'
        },
        {
          id: 'mock_spot_003',
          name: '苕溪河湾',
          water_type: '河流',
          address: '示例地址 · 瓶窑镇',
          location_gcj02: { lat: 30.33, lon: 120.05 },
          entry_location_gcj02: { lat: 30.329, lon: 120.051 },
          entry_precision: 'entr_location',
          distance_m: 27400,
          drive_seconds_out: 2100,
          drive_seconds_back: 2280,
          drive_seconds_round_trip: 4380,
          drive_minutes_one_way: 35,
          fish_score: 61,
          total_score: 71.8,
          reasons: ['往返约 73 分钟', '河流回水湾，溶氧较好'],
          navigation_url: 'https://uri.amap.com/marker?position=120.051,30.329&name=苕溪河湾'
        },
        {
          id: 'mock_spot_004',
          name: '白鹭湖',
          water_type: '湖泊',
          address: '示例地址 · 富阳区',
          location_gcj02: { lat: 30.22, lon: 119.98 },
          entry_location_gcj02: null,
          entry_precision: 'center_fallback',
          distance_m: 33100,
          drive_seconds_out: 3300,
          drive_seconds_back: 3540,
          drive_seconds_round_trip: 6840,
          drive_minutes_one_way: 55,
          fish_score: 58,
          total_score: 66.4,
          reasons: ['气压缓降，鱼口有机会', '往返约 114 分钟', '湖泊适配鲤鱼'],
          navigation_url: 'https://uri.amap.com/marker?position=119.98,30.22&name=白鹭湖'
        },
        {
          id: 'mock_spot_005',
          name: '九龙湖',
          water_type: '水库',
          address: '示例地址 · 萧山区',
          location_gcj02: { lat: 30.14, lon: 120.22 },
          entry_location_gcj02: { lat: 30.139, lon: 120.221 },
          entry_precision: 'entr_location',
          distance_m: 48700,
          drive_seconds_out: 3480,
          drive_seconds_back: 3660,
          drive_seconds_round_trip: 7140,
          drive_minutes_one_way: 58,
          fish_score: 55,
          total_score: 61.9,
          reasons: ['往返约 119 分钟', '水库大水面，需留意风力'],
          navigation_url: 'https://uri.amap.com/marker?position=120.221,30.139&name=九龙湖'
        },
        {
          id: 'mock_spot_006',
          name: '湘湖',
          water_type: '湖泊',
          address: '示例地址 · 萧山区',
          location_gcj02: { lat: 30.151, lon: 120.161 },
          entry_location_gcj02: { lat: 30.15, lon: 120.162 },
          entry_precision: 'entr_location',
          distance_m: 21400,
          drive_seconds_out: 1680,
          drive_seconds_back: 1800,
          drive_seconds_round_trip: 3480,
          drive_minutes_one_way: 28,
          fish_score: 57,
          total_score: 58.6,
          reasons: ['往返约 58 分钟', '湖岸平缓，适合早晚窗口'],
          navigation_url: 'https://uri.amap.com/marker?position=120.162,30.15&name=湘湖'
        }
    ];
    return {
      user_location: {
        wgs84: { lat: state.lat, lon: state.lon },
        gcj02: { lat: 30.2756, lon: 120.1598 }
      },
      spots: allSpots,
      filtered: {
        total_candidates: 9,
        forbidden: 1,
        over_two_hours: 2,
        eligible: allSpots.length,
        returned: allSpots.length,
        truncated_by_limit: 0
      },
      meta: {
        mock_mode: true,
        radius_km: state.radiusKm,
        round_trip_limit_seconds: 7200,
        traffic_basis: 'baseline_estimate',
        generated_at: generatedAt
      }
    };
  }

  function makeMockChat(message) {
    var text = String(message || '');
    var wantsSpots = /附近|哪里|钓位|钓点|野钓|推荐|车程|水库|湖/.test(text);
    var wantsTime = /几点|时段|明早|早上|傍晚|什么时候|最佳时间|窗口/.test(text);
    var wantsFish = /气压|鱼情|鱼口|适合钓|能钓|好钓|活跃|天气|出钓|评分/.test(text);
    var toolCalls = [];
    var fish = null;
    var spots = null;
    var reply = '';

    if (!wantsSpots && !wantsTime && !wantsFish) {
      return {
        reply:
          '我可以帮你做三件事：分析当前鱼情与气压、推荐往返 2 小时内的钓位、给出最佳出钓时段。试试问「今天气压适合钓鱼吗？」',
        session_id: state.sessionId,
        mode: 'fallback',
        tool_calls: [],
        fish_activity: null,
        spots: null,
        ai_disclosure: DISCLOSURE
      };
    }

    if (wantsFish || wantsTime) {
      fish = makeMockFishActivity();
      toolCalls.push({ name: 'get_fish_activity', args: { lat: state.lat, lon: state.lon }, status: 'ok' });
    }
    if (wantsSpots) {
      spots = makeMockSpots();
      toolCalls.push({ name: 'recommend_spots', args: { lat: state.lat, lon: state.lon }, status: 'ok' });
    }

    if (wantsSpots && fish) {
      reply =
        '当前鱼情评分 ' + fish.score + ' 分（' + fish.band + '），优先日出窗口 05:30–08:00。' +
        '附近已筛出 ' + spots.spots.length + ' 个往返 ≤2 小时的钓位，首选「' + spots.spots[0].name +
        '」，单程约 ' + spots.spots[0].drive_minutes_one_way + ' 分钟，综合分 ' + spots.spots[0].total_score +
        '。出发前请确认当地禁钓规定。';
    } else if (wantsSpots) {
      reply =
        '附近已筛出 ' + spots.spots.length + ' 个满足往返 ≤2 小时的钓位，已排除禁钓候选。首选「' +
        spots.spots[0].name + '」：单程约 ' + spots.spots[0].drive_minutes_one_way + ' 分钟、往返约 ' +
        Math.round(spots.spots[0].drive_seconds_round_trip / 60) + ' 分钟，综合分 ' + spots.spots[0].total_score +
        '。车程为基线估计，实际以导航为准。';
    } else if (wantsTime) {
      reply =
        '明早建议优先安排 05:30–08:00 的日出窗口，次选 16:30–18:30 的日落窗口。' +
        '当前鱼情评分 ' + fish.score + ' 分（' + fish.band + '），气压缓降 4.2hPa/24h 是主要利好。' +
        '出门前留意风力变化与雷雨提示，不承诺渔获。';
    } else {
      reply =
        '当前鱼情评分 ' + fish.score + ' 分，档位「' + fish.band + '」：' + fish.advice + '。' +
        '主要利好是气压缓降（24h -4.2hPa），建议优先日出窗口 05:30–08:00，其次 16:30–18:30。' +
        '连续晴热天数偏多，建议先钓 1.5–2m 浅滩，无口再转深水。';
    }

    return {
      reply: reply,
      session_id: state.sessionId,
      mode: 'fallback',
      tool_calls: toolCalls,
      fish_activity: fish,
      spots: spots,
      ai_disclosure: DISCLOSURE
    };
  }

  function init() {
    syncLocationUI();
    $('radius-select').value = String(state.radiusKm);
    bindEvents();
    initPwa();
    if (state.mockMode) {
      setModeBadge('Mock 演示');
      setStatus('当前为前端 Mock 演示（?mock=1），数据仅用于界面自查。', 'info', true);
    } else {
      checkHealth();
    }
    refreshAll();
    updateChatControls();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
