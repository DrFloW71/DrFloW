// ==UserScript==
// @name         Connecteur DrFloW - WEDA 
// @namespace    http://tampermonkey.net/
// @version      0.5.14
// @description  Pont local WEDA vers DrFloW : contexte patient et import manuel contrôlé.
// @match        https://secure.weda.fr/*
// @run-at       document-idle
// @noframes
// @grant        GM_xmlhttpRequest
// @grant        GM_setClipboard
// @grant        unsafeWindow
// @connect      127.0.0.1
// @connect      localhost
// ==/UserScript==

(function () {
    'use strict';

    try {
        if (window.top && window.top !== window.self) return;
    } catch (_) {
        return;
    }

    const SERVER = 'http://127.0.0.1:8765';
    const PANEL_ID = 'gemma-weda-assistant-bridge-panel';
    const PANEL_HEADER_ID = 'gemma-weda-assistant-bridge-panel-header';
    const PANEL_BODY_ID = 'gemma-weda-assistant-bridge-panel-body';
    const PANEL_REC_ID = 'gemma-weda-assistant-bridge-panel-rec';
    const PANEL_COLLAPSE_ID = 'gemma-weda-assistant-bridge-panel-collapse';
    const BADGE_ID = 'gemma-weda-assistant-bridge-badge';
    const WEDA_REC_FAVICON_ID = 'gemma-weda-assistant-bridge-rec-favicon';
    const LOG_STORAGE_KEY = 'gemma_weda_assistant_bridge_logs_v1';
    const PANEL_POSITION_STORAGE_KEY = 'gemma_weda_assistant_bridge_panel_position_v1';
    const PANEL_COLLAPSED_STORAGE_KEY = 'gemma_weda_assistant_bridge_panel_collapsed_v1';
    const MAX_LOGS = 160;
    const LAST_TARGET_MAX_AGE_MS = 10 * 60 * 1000;
    const PAGE_WEDA_CONSULTATION = '/foldermedical/consultationform.aspx';
    const PAGE_WEDA_PATIENT = '/foldermedical/patientviewform.aspx';
    const SELECTOR_WEDA_SUITE = '#ContentPlaceHolder1_HistoriqueUCForm1_ButtonSuiteWeda';
    const SELECTOR_WEDA_NEW_CONSULTATION = '#ContentPlaceHolder1_MenuNavigate\\:submenu\\:2 > li:nth-child(1) > a';
    const SELECTOR_WEDA_HOME_IMAGE = 'img[src*="W_BLEU.png"], img[src*="W_BLEU"], img[src*="Weda"], img[src*="weda"]';
    const POSTBACK_MENU_EVENTTARGET_WEDA = 'ctl00$ContentPlaceHolder1$EvenementUcForm1$MenuNavigate';
    const POSTBACK_RETURN_HOME_WEDA = '0';
    const POSTBACK_MENU_GENERAL_EVENTTARGET_WEDA = 'ctl00$ContentPlaceHolder1$MenuNavigate';
    const POSTBACK_RETURN_HOME_GENERAL_WEDA = '0\\0';
    const POSTBACK_RETURN_HOME_GENERAL_ALT_WEDA = '0';
    const POSTBACK_NEW_CONSULTATION_GENERAL_WEDA = '0\\1';
    const MAX_WEDA_SUITE_CLICKS = 6;
    const WEDA_SUITE_CLICK_DELAY_MS = 900;
    const DEFAULT_CONTEXT_CAPTURE_DELAY_SECONDS = 60;
    const MAX_CONTEXT_CAPTURE_DELAY_SECONDS = 300;
    const CONNECTOR_PENDING_JOB_KEY = 'gemma_weda_assistant_connector_pending_job_v1';
    const CONNECTOR_IMPORT_LOCK_KEY = 'gemma_weda_assistant_connector_import_lock_v1';
    const CONNECTOR_IMPORTED_REQUESTS_KEY = 'gemma_weda_assistant_connector_imported_requests_v1';
    const CONNECTOR_SETTINGS_REFRESH_MS = 15000;
    const CONTEXT_REFRESH_POLL_MS = 1000;
    const CONTEXT_REFRESH_ACTIVE_TAB_KEY = 'drflow_weda_context_active_tab_v1';
    const CONNECTOR_POLL_INTERVAL_MS = 2500;
    const CONNECTOR_RESULT_TIMEOUT_MS = 180000;
    const CONNECTOR_PENDING_MAX_AGE_MS = 10 * 60 * 1000;
    const CONNECTOR_SHORTCUT_COOLDOWN_MS = 1200;
    const CONNECTOR_CONSULTATION_OPEN_TIMEOUT_MS = 10000;
    const CONNECTOR_IMPORT_LOCK_TTL_MS = 30000;
    const CONNECTOR_IMPORTED_REQUEST_MAX_AGE_MS = 60 * 60 * 1000;
    const PHRASE_SECURITE_MEDICO_LEGALE = 'Aucun signe de gravité, Explications claires données au patient. Prise en charge expliquée et acceptée par le patient.';
    const SELECTOR_WEDA_WEIGHT = '#ContentPlaceHolder1_SuivisGrid_EditBoxGridSuiviReponse_0';
    const SELECTOR_WEDA_HEIGHT = '#ContentPlaceHolder1_SuivisGrid_EditBoxGridSuiviReponse_1';
    const SELECTOR_WEDA_BP_SYS = '#ContentPlaceHolder1_SuivisGrid_EditBoxGridSuiviReponse_3';
    const SELECTOR_WEDA_BP_DIA = '#ContentPlaceHolder1_SuivisGrid_EditBoxGridSuiviReponse_4';
    const SELECTOR_WEDA_BP_HOME = '#ContentPlaceHolder1_SuivisGrid_EditBoxGridSuiviReponse_5';
    const SELECTOR_WEDA_TEMPERATURE = '#ContentPlaceHolder1_SuivisGrid_EditBoxGridSuiviReponse_6';
    const SELECTOR_WEDA_TOBACCO = '#ContentPlaceHolder1_SuivisGrid_EditBoxGridSuiviReponse_7';
    const SELECTOR_WEDA_ALCOHOL = '#ContentPlaceHolder1_SuivisGrid_EditBoxGridSuiviReponse_8';
    const SELECTOR_WEDA_FEET_EXAM = '#ContentPlaceHolder1_SuivisGrid_EditBoxGridSuiviReponse_9';
    const SELECTOR_WEDA_HEMOCULT = '#ContentPlaceHolder1_SuivisGrid_EditBoxGridSuiviReponse_10';
    const SELECTOR_WEDA_PAP_SMEAR = '#ContentPlaceHolder1_SuivisGrid_EditBoxGridSuiviReponse_11';
    const SELECTOR_WEDA_MAMMOGRAPHY = '#ContentPlaceHolder1_SuivisGrid_EditBoxGridSuiviReponse_12';
    const SELECTOR_WEDA_DENTIST = '#ContentPlaceHolder1_SuivisGrid_EditBoxGridSuiviReponse_13';
    const SELECTOR_WEDA_DTP = '#ContentPlaceHolder1_SuivisGrid_EditBoxGridSuiviReponse_14';
    const SELECTOR_WEDA_HPV = '#ContentPlaceHolder1_SuivisGrid_EditBoxGridSuiviReponse_15';
    const SELECTOR_WEDA_FUNDUS = '#ContentPlaceHolder1_SuivisGrid_EditBoxGridSuiviReponse_20';
    const SELECTOR_WEDA_CARDIOLOGIST = '#ContentPlaceHolder1_SuivisGrid_EditBoxGridSuiviReponse_21';
    const SELECTOR_WEDA_MMS = '#ContentPlaceHolder1_SuivisGrid_EditBoxGridSuiviReponse_23';
    const SELECTOR_WEDA_MADRS = '#ContentPlaceHolder1_SuivisGrid_EditBoxGridSuiviReponse_24';
    const SELECTOR_WEDA_TAG_PANEL_BUTTON = '#ContentPlaceHolder1_EvenementUcForm1_ButtonStatEtiquette';
    const SELECTOR_WEDA_TAG_GRID = '#ContentPlaceHolder1_EvenementUcForm1_GlossairesGrid';
    const WEDA_STRUCTURED_FIELD_TIMEOUT_MS = 4500;
    const WEDA_TAG_PANEL_TIMEOUT_MS = 4000;
    const WEDA_TAG_APPLY_DELAY_MS = 450;
    const WEDA_AVAILABLE_TAGS = [
        'Alcool',
        'Angine',
        'ASALEE',
        'Chute',
        'CoViD',
        'DT2',
        'ETP',
        'HTA',
        'IC',
        'Ongle incarné',
        'Soins palliatifs',
        'Syndrome dépressif',
        'Tabac'
    ];

    let lastEditableTarget = null;
    let connectorSettings = {
        enabled: false,
        start_key: 'PageUp',
        stop_key: 'PageDown',
        document_now_key: 'F8',
        auto_return_home: true
    };
    let connectorShortcutInstalled = false;
    let connectorLastShortcutAt = 0;
    let connectorWorkflowBusy = false;
    let connectorDocumentNowBusy = false;
    let flyDictationSettings = {
        enabled: true,
        key: '²'
    };
    let flyDictationShortcutInstalled = false;
    let flyDictationKeyDown = false;
    let wedaRecordingIndicatorActive = false;
    let wedaOriginalTitle = '';
    let wedaOriginalFaviconHref = null;
    const contextRefreshResponderId = (
        Date.now().toString(36) + '-' + Math.random().toString(36).slice(2)
    );
    let contextRefreshPollBusy = false;

    function markWedaContextTabActive() {
        try {
            localStorage.setItem(CONTEXT_REFRESH_ACTIVE_TAB_KEY, JSON.stringify({
                responderId: contextRefreshResponderId,
                at: Date.now(),
                href: location.href
            }));
        } catch (_) {}
    }

    function isPreferredWedaContextTab() {
        try {
            const raw = localStorage.getItem(CONTEXT_REFRESH_ACTIVE_TAB_KEY);
            const active = raw ? JSON.parse(raw) : null;
            return !!active && active.responderId === contextRefreshResponderId;
        } catch (_) {
            return true;
        }
    }

    window.addEventListener('focus', markWedaContextTabActive, true);
    document.addEventListener('pointerdown', markWedaContextTabActive, true);
    document.addEventListener('keydown', markWedaContextTabActive, true);
    document.addEventListener('visibilitychange', () => {
        if (document.visibilityState === 'visible' && document.hasFocus()) {
            markWedaContextTabActive();
        }
    });
    if (document.visibilityState !== 'hidden' && document.hasFocus()) {
        markWedaContextTabActive();
    }

    function normalizeSpaces(text) {
        return String(text || '')
            .replace(/\u00a0/g, ' ')
            .replace(/[ \t]+/g, ' ')
            .replace(/\n{3,}/g, '\n\n')
            .trim();
    }

    function normalizeSearchText(text) {
        return normalizeSpaces(text)
            .toLowerCase()
            .normalize('NFD')
            .replace(/[\u0300-\u036f]/g, '')
            .replace(/[_:.-]+/g, ' ');
    }

    function nowIso() {
        try {
            return new Date().toISOString();
        } catch (_) {
            return String(Date.now());
        }
    }

    function compactValue(value, depth = 0) {
        if (value == null) return value;
        if (typeof value === 'number' || typeof value === 'boolean') return value;
        if (typeof value === 'string') return value.length > 600 ? value.slice(0, 600) + '...' : value;
        if (depth > 2) return '[object]';
        if (Array.isArray(value)) {
            const sample = value.slice(0, 8).map(item => compactValue(item, depth + 1));
            if (value.length > sample.length) sample.push(`... +${value.length - sample.length}`);
            return sample;
        }
        if (typeof Element !== 'undefined' && value instanceof Element) {
            return describeElement(value);
        }
        if (typeof value === 'object') {
            const out = {};
            Object.keys(value).slice(0, 24).forEach(key => {
                if (/result_text|visible_text|patient_panel_text|raw/i.test(key)) {
                    out[key + '_length'] = String(value[key] || '').length;
                    return;
                }
                out[key] = compactValue(value[key], depth + 1);
            });
            return out;
        }
        return String(value);
    }

    function getLocalLogs() {
        try {
            const logs = JSON.parse(localStorage.getItem(LOG_STORAGE_KEY) || '[]');
            return Array.isArray(logs) ? logs : [];
        } catch (_) {
            return [];
        }
    }

    function saveLocalLogs(logs) {
        try {
            localStorage.setItem(LOG_STORAGE_KEY, JSON.stringify((Array.isArray(logs) ? logs : []).slice(-MAX_LOGS)));
        } catch (_) {}
    }

    function postLogToApp(entry) {
        try {
            GM_xmlhttpRequest({
                method: 'POST',
                url: SERVER + '/debug/log',
                headers: { 'Content-Type': 'application/json' },
                data: JSON.stringify(entry),
                timeout: 3000,
                onload: () => {},
                onerror: () => {},
                ontimeout: () => {}
            });
        } catch (_) {}
    }

    function logEvent(level, event, message, details = {}) {
        const entry = {
            at: nowIso(),
            level: String(level || 'info').toLowerCase(),
            source: 'tampermonkey',
            event: String(event || ''),
            message: String(message || ''),
            details: compactValue({
                page_url: location.href,
                page_title: document.title || '',
                ...details
            })
        };

        const logs = getLocalLogs();
        logs.push(entry);
        saveLocalLogs(logs);

        try {
            const fn = entry.level === 'error' ? console.error : (entry.level === 'warning' ? console.warn : console.log);
            fn('[GEMMA-WEDA-BRIDGE]', entry);
        } catch (_) {}

        postLogToApp(entry);
        return entry;
    }

    function copyDebugLogs() {
        const text = JSON.stringify({
            exported_at: nowIso(),
            source: 'tampermonkey',
            logs: getLocalLogs()
        }, null, 2);
        GM_setClipboard(text, 'text');
        logEvent('info', 'logs_copied', 'Logs Tampermonkey copiés dans le presse-papiers.', { count: getLocalLogs().length });
        showBadge('Logs Tampermonkey copiés dans le presse-papiers.');
    }

    function extractPatDk(value) {
        const text = String(value || location.href || '');
        try {
            const parsed = new URL(text, location.href);
            return normalizeSpaces(parsed.searchParams.get('PatDk') || '');
        } catch (_) {
            const match = text.match(/[?&]PatDk=([^&#]+)/i);
            if (!match) return '';
            try {
                return normalizeSpaces(decodeURIComponent(match[1].replace(/\+/g, ' ')));
            } catch (_) {
                return normalizeSpaces(match[1]);
            }
        }
    }

    function normalizePatientId(value) {
        return normalizeSpaces(value).split('|')[0];
    }

    function samePatient(expected, current) {
        const left = normalizePatientId(expected);
        const right = normalizePatientId(current);
        return !!left && !!right && left === right;
    }

    function sleep(ms) {
        return new Promise(resolve => setTimeout(resolve, ms));
    }

    function getHrefLower() {
        return String(location.href || '').toLowerCase();
    }

    function isWedaPatientHomePage() {
        return getHrefLower().includes(PAGE_WEDA_PATIENT);
    }

    function isWedaConsultationPage() {
        return getHrefLower().includes(PAGE_WEDA_CONSULTATION);
    }

    function showBadge(message, error = false) {
        const old = document.getElementById(BADGE_ID);
        if (old) old.remove();

        const badge = document.createElement('div');
        badge.id = BADGE_ID;
        badge.textContent = message;
        badge.style.position = 'fixed';
        badge.style.left = '14px';
        badge.style.bottom = '14px';
        badge.style.zIndex = '2147483647';
        badge.style.maxWidth = '560px';
        badge.style.whiteSpace = 'pre-wrap';
        badge.style.background = error ? '#7a1020' : '#12395f';
        badge.style.color = '#fff';
        badge.style.font = '700 13px Arial, sans-serif';
        badge.style.lineHeight = '1.35';
        badge.style.padding = '10px 12px';
        badge.style.borderRadius = '8px';
        badge.style.boxShadow = '0 4px 16px rgba(0,0,0,.28)';
        document.documentElement.appendChild(badge);

        setTimeout(() => {
            try { badge.remove(); } catch (_) {}
        }, 7000);
    }

    function getCurrentFaviconLink() {
        return document.querySelector('link[rel~="icon"], link[rel="shortcut icon"]');
    }

    function setWedaRecordingFavicon(active) {
        const existingBadgeIcon = document.getElementById(WEDA_REC_FAVICON_ID);
        if (!active) {
            if (existingBadgeIcon) existingBadgeIcon.remove();
            const icon = getCurrentFaviconLink();
            if (icon && wedaOriginalFaviconHref !== null) {
                icon.setAttribute('href', wedaOriginalFaviconHref);
            }
            wedaOriginalFaviconHref = null;
            return;
        }

        if (wedaOriginalFaviconHref === null) {
            const current = getCurrentFaviconLink();
            wedaOriginalFaviconHref = current ? String(current.getAttribute('href') || '') : '';
        }

        const svg = [
            '<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64" viewBox="0 0 64 64">',
            '<rect width="64" height="64" rx="12" fill="#dc2626"/>',
            '<text x="32" y="38" text-anchor="middle" font-family="Arial, sans-serif" font-size="18" font-weight="700" fill="#ffffff">REC</text>',
            '</svg>'
        ].join('');
        let icon = existingBadgeIcon;
        if (!icon) {
            icon = document.createElement('link');
            icon.id = WEDA_REC_FAVICON_ID;
            icon.rel = 'icon';
            document.head.appendChild(icon);
        }
        icon.href = 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(svg);
    }

    function setWedaPageRecordingIndicator(active) {
        const shouldBeActive = !!active;
        if (shouldBeActive) {
            if (!wedaRecordingIndicatorActive) {
                wedaOriginalTitle = document.title || '';
            }
            document.title = 'REC WEDA - ' + (wedaOriginalTitle || document.title || 'WEDA');
            setWedaRecordingFavicon(true);
            wedaRecordingIndicatorActive = true;
            return;
        }

        if (wedaRecordingIndicatorActive) {
            document.title = wedaOriginalTitle || document.title.replace(/^REC WEDA -\s*/i, '');
        }
        setWedaRecordingFavicon(false);
        wedaRecordingIndicatorActive = false;
        wedaOriginalTitle = '';
    }

    function setPanelRecordingIndicator(active) {
        const rec = document.getElementById(PANEL_REC_ID);
        if (rec) rec.style.display = active ? 'inline-flex' : 'none';
        const panel = document.getElementById(PANEL_ID);
        if (panel) {
            panel.style.borderColor = active ? '#dc2626' : '#cbd5e1';
            panel.style.boxShadow = active
                ? '0 10px 28px rgba(220,38,38,.24)'
                : '0 10px 28px rgba(15,23,42,.28)';
        }
    }

    function syncConnectorRecordingIndicator(job) {
        const active = !!job && (job.phase === 'recording' || job.appStatus === 'recording');
        setWedaPageRecordingIndicator(active);
        setPanelRecordingIndicator(active);
    }

    function requestJson(method, path, body = null) {
        return new Promise((resolve, reject) => {
            GM_xmlhttpRequest({
                method,
                url: SERVER + path,
                headers: { 'Content-Type': 'application/json' },
                data: body ? JSON.stringify(body) : undefined,
                timeout: 10000,
                onload: response => {
                    try {
                        const data = JSON.parse(response.responseText || '{}');
                        if (response.status >= 200 && response.status < 300) resolve(data);
                        else reject(new Error(data.error || `HTTP ${response.status}`));
                    } catch (error) {
                        reject(error);
                    }
                },
                ontimeout: () => reject(new Error('Serveur local indisponible ou timeout.')),
                onerror: () => reject(new Error('Serveur local indisponible.'))
            });
        });
    }

    async function getContextCaptureDelaySeconds() {
        try {
            const response = await requestJson('GET', '/settings');
            const raw = response && response.settings
                ? response.settings.context_capture_delay_seconds
                : DEFAULT_CONTEXT_CAPTURE_DELAY_SECONDS;
            const value = Number(raw);
            if (!Number.isFinite(value)) return DEFAULT_CONTEXT_CAPTURE_DELAY_SECONDS;
            return Math.max(0, Math.min(MAX_CONTEXT_CAPTURE_DELAY_SECONDS, Math.round(value)));
        } catch (error) {
            logEvent('warning', 'settings_unavailable', 'Réglages application indisponibles, délai contexte par défaut utilisé.', {
                defaultDelaySeconds: DEFAULT_CONTEXT_CAPTURE_DELAY_SECONDS,
                error: error && error.message ? error.message : String(error)
            });
            return DEFAULT_CONTEXT_CAPTURE_DELAY_SECONDS;
        }
    }

    async function waitBeforeContextCapture(delaySeconds) {
        const delay = Math.max(0, Math.min(MAX_CONTEXT_CAPTURE_DELAY_SECONDS, Number(delaySeconds) || 0));
        if (delay <= 0) return;

        logEvent('info', 'context_capture_delay_start', 'Temporisation avant récupération du contexte WEDA.', {
            delaySeconds: delay
        });
        showBadge('Collecte contexte WEDA dans ' + delay + ' s...');
        await sleep(delay * 1000);
        logEvent('info', 'context_capture_delay_done', 'Temporisation contexte terminée.', {
            delaySeconds: delay
        });
    }

    function getPatientPanelText() {
        const selectors = [
            '#ContentPlaceHolder1_PanelPatient',
            '#PanelPatient',
            '[id*="PanelPatient"]',
            '[class*="patient"]'
        ];
        for (const doc of getAccessibleDocumentsDeep()) {
            for (const selector of selectors) {
                try {
                    const el = doc.querySelector(selector);
                    const text = normalizeSpaces(el && (el.innerText || el.textContent));
                    if (text) return text;
                } catch (_) {}
            }
        }
        return '';
    }

    function inferPatientIdentity(panelText) {
        const lines = normalizeSpaces(panelText)
            .split(/\r?\n/)
            .map(line => normalizeSpaces(line))
            .filter(Boolean);
        return lines.slice(0, 3).join(' | ').slice(0, 240);
    }

    function getVisibleWedaTextDeep() {
        const blocks = [];
        for (const doc of getAccessibleDocumentsDeep()) {
            try {
                if (!doc.body) continue;
                const text = normalizeSpaces(doc.body.innerText || doc.body.textContent || '');
                if (text && !blocks.includes(text)) blocks.push(text);
            } catch (_) {}
        }
        return normalizeSpaces(blocks.join('\n\n'));
    }

    function getWedaSuiteButton() {
        for (const doc of getAccessibleDocumentsDeep()) {
            try {
                const direct = doc.querySelector(SELECTOR_WEDA_SUITE);
                if (direct) return direct;
            } catch (_) {}

            try {
                const candidates = Array.from(doc.querySelectorAll('input, button, a'));
                const button = candidates.find(element => {
                    const text = normalizeSpaces([
                        element.id || '',
                        element.getAttribute('name') || '',
                        element.getAttribute('value') || element.value || '',
                        element.getAttribute('title') || '',
                        element.innerText || element.textContent || ''
                    ].join(' ')).toLowerCase();
                    return text.includes('buttonsuiteweda')
                        || text.includes('suite des documents weda')
                        || /\bsuite\b/.test(text);
                });
                if (button) return button;
            } catch (_) {}
        }
        return null;
    }

    function clickElementForWeda(el) {
        if (!el) return false;
        try { el.scrollIntoView({ block: 'center', inline: 'center' }); } catch (_) {}
        try {
            const win = ownerWindowOf(el);
            const rect = el.getBoundingClientRect();
            const x = Math.max(1, Math.round(rect.left + rect.width / 2));
            const y = Math.max(1, Math.round(rect.top + rect.height / 2));
            ['mouseover', 'mousemove', 'mousedown', 'mouseup', 'click'].forEach(type => {
                el.dispatchEvent(new win.MouseEvent(type, {
                    bubbles: true,
                    cancelable: true,
                    view: win,
                    clientX: x,
                    clientY: y,
                    button: 0
                }));
            });
        } catch (_) {}
        try { el.click(); } catch (_) {}
        return true;
    }

    function waitFor(predicate, timeoutMs = 10000, intervalMs = 300) {
        const startedAt = Date.now();
        return new Promise(resolve => {
            function tick() {
                let value = null;
                try {
                    value = predicate();
                } catch (_) {
                    value = null;
                }
                if (value) {
                    resolve(value);
                    return;
                }
                if (Date.now() - startedAt >= timeoutMs) {
                    resolve(null);
                    return;
                }
                setTimeout(tick, intervalMs);
            }
            tick();
        });
    }

    function getTampermonkeyUnsafeWindow() {
        try {
            if (typeof unsafeWindow !== 'undefined' && unsafeWindow) return unsafeWindow;
        } catch (_) {}
        return window;
    }

    function callPostBack(eventTarget, eventArgument = '') {
        try {
            const unsafe = getTampermonkeyUnsafeWindow();
            const fn = (unsafe && unsafe.__doPostBack) || window.__doPostBack;
            if (typeof fn !== 'function') return false;
            fn(String(eventTarget || ''), String(eventArgument || ''));
            return true;
        } catch (error) {
            logEvent('warning', 'weda_postback_error', 'Erreur __doPostBack WEDA.', {
                eventTarget,
                eventArgument,
                error: error && error.message ? error.message : String(error)
            });
            return false;
        }
    }

    function decodeWedaJsAttributeValue(value) {
        return String(value || '')
            .replace(/\\\\/g, '\\')
            .replace(/\\'/g, "'")
            .replace(/\\"/g, '"')
            .replace(/\\r/g, '\r')
            .replace(/\\n/g, '\n')
            .replace(/\\t/g, '\t');
    }

    function extractWedaPostBackFromElement(element) {
        if (!element) return null;

        const candidates = [];
        let current = element;
        for (let index = 0; current && index < 5; index += 1) {
            candidates.push(current);
            current = current.parentElement;
        }

        for (const el of candidates) {
            const values = [
                el.getAttribute ? el.getAttribute('onclick') || '' : '',
                el.getAttribute ? el.getAttribute('href') || '' : '',
                el.getAttribute ? el.getAttribute('onmousedown') || '' : ''
            ];

            for (const rawValue of values) {
                const value = String(rawValue || '');
                if (!value.includes('__doPostBack')) continue;

                const singleQuote = value.match(/__doPostBack\s*\(\s*'([^']*)'\s*,\s*'([^']*)'\s*\)/);
                if (singleQuote) {
                    return {
                        eventTarget: decodeWedaJsAttributeValue(singleQuote[1]),
                        eventArgument: decodeWedaJsAttributeValue(singleQuote[2]),
                        eventTargetRaw: singleQuote[1],
                        eventArgumentRaw: singleQuote[2],
                        source: 'single_quote_attribute'
                    };
                }

                const doubleQuote = value.match(/__doPostBack\s*\(\s*"([^"]*)"\s*,\s*"([^"]*)"\s*\)/);
                if (doubleQuote) {
                    return {
                        eventTarget: decodeWedaJsAttributeValue(doubleQuote[1]),
                        eventArgument: decodeWedaJsAttributeValue(doubleQuote[2]),
                        eventTargetRaw: doubleQuote[1],
                        eventArgumentRaw: doubleQuote[2],
                        source: 'double_quote_attribute'
                    };
                }
            }
        }

        return null;
    }

    function submitPostBackForm(eventTarget, eventArgument = '') {
        for (const doc of getAccessibleDocumentsDeep()) {
            try {
                const form = doc.querySelector('form');
                const targetInput = doc.querySelector('input[name="__EVENTTARGET"], #__EVENTTARGET');
                const argumentInput = doc.querySelector('input[name="__EVENTARGUMENT"], #__EVENTARGUMENT');
                if (!form || !targetInput || !argumentInput) continue;

                targetInput.value = String(eventTarget || '');
                argumentInput.value = String(eventArgument || '');

                const win = ownerWindowOf(form);
                const nativeSubmit = win.HTMLFormElement && win.HTMLFormElement.prototype
                    ? win.HTMLFormElement.prototype.submit
                    : null;
                if (typeof nativeSubmit === 'function') nativeSubmit.call(form);
                else form.submit();
                return true;
            } catch (_) {}
        }
        return false;
    }

    function triggerWedaPostBack(postBack, allowFormFallback = true) {
        if (!postBack || !postBack.eventTarget) {
            return { ok: false, okPostBack: false, okFormSubmit: false };
        }

        const okPostBack = callPostBack(postBack.eventTarget, postBack.eventArgument || '');
        const okFormSubmit = !okPostBack && allowFormFallback
            ? submitPostBackForm(postBack.eventTarget, postBack.eventArgument || '')
            : false;
        return {
            ok: okPostBack || okFormSubmit,
            okPostBack,
            okFormSubmit
        };
    }

    function elementActionText(el) {
        if (!el) return '';
        return normalizeSpaces([
            el.id || '',
            el.getAttribute ? el.getAttribute('name') || '' : '',
            el.getAttribute ? el.getAttribute('href') || '' : '',
            el.getAttribute ? el.getAttribute('onclick') || '' : '',
            el.getAttribute ? el.getAttribute('value') || el.value || '' : '',
            el.getAttribute ? el.getAttribute('title') || '' : '',
            el.innerText || el.textContent || ''
        ].join(' ')).toLowerCase();
    }

    function elementActionSearchText(el) {
        if (!el) return '';
        return normalizeSearchText([
            el.innerText || '',
            el.textContent || '',
            el.getAttribute ? el.getAttribute('value') || el.value || '' : '',
            el.getAttribute ? el.getAttribute('title') || '' : '',
            el.getAttribute ? el.getAttribute('aria-label') || '' : '',
            el.id || '',
            el.getAttribute ? el.getAttribute('name') || '' : '',
            el.getAttribute ? el.getAttribute('href') || '' : '',
            el.getAttribute ? el.getAttribute('onclick') || '' : ''
        ].join(' '));
    }

    function postBackLooksLikeNewConsultation(postBack) {
        if (!postBack || !postBack.eventTarget) return false;
        const target = String(postBack.eventTarget || '').toLowerCase();
        const argument = String(postBack.eventArgument || '');
        return target.includes('menunavigate') && argument === POSTBACK_NEW_CONSULTATION_GENERAL_WEDA;
    }

    function collectWedaNewConsultationActions() {
        const results = [];
        const seen = new Set();

        function addCandidate(element, source, score) {
            if (!element || seen.has(element)) return;
            seen.add(element);
            const postBack = extractWedaPostBackFromElement(element);
            results.push({
                element,
                source,
                score,
                target: describeElement(element),
                postBack
            });
        }

        for (const doc of getAccessibleDocumentsDeep()) {
            try {
                const direct = doc.querySelector(SELECTOR_WEDA_NEW_CONSULTATION);
                if (direct) addCandidate(direct, 'known_selector', 100);
            } catch (_) {}

            let elements = [];
            try {
                elements = Array.from(doc.querySelectorAll('a, button, input, img, [role="button"]'));
            } catch (_) {
                elements = [];
            }

            elements.forEach(el => {
                const text = elementActionSearchText(el);
                const postBack = extractWedaPostBackFromElement(el);

                const isKnownPostBack = postBackLooksLikeNewConsultation(postBack);
                const isNewConsultation =
                    text.includes('nouvelle consultation') ||
                    text.includes('nouveau consultation') ||
                    text.includes('creer consultation') ||
                    text.includes('creer une consultation') ||
                    text.includes('nouvel evenement consultation') ||
                    text.includes('menunavigate submenu 2');

                const isSimpleConsultation =
                    text === 'consultation' ||
                    /^consultation\s*\(\d+\)$/.test(text) ||
                    (text.includes('consultation') && text.includes('menunavigate'));

                if (!isKnownPostBack && !isNewConsultation && !isSimpleConsultation) return;

                const excluded =
                    text.includes('distinct') ||
                    text.includes('historique') ||
                    text.includes('compte rendu') ||
                    text.includes('courrier') ||
                    text.includes('hprim') ||
                    text.includes('biologie') ||
                    text.includes('ordonnance');
                if (excluded) return;

                addCandidate(
                    el,
                    isKnownPostBack ? 'known_postback' : (isNewConsultation ? 'new_consultation_text' : 'consultation_text'),
                    isKnownPostBack ? 95 : (isNewConsultation ? 90 : 70)
                );
            });
        }

        results.sort((a, b) => b.score - a.score);
        return results;
    }

    function findWedaNewConsultationAction() {
        const candidates = collectWedaNewConsultationActions();
        return {
            action: candidates.length ? candidates[0] : null,
            candidates
        };
    }

    function findWedaNewConsultationButton() {
        const resolved = findWedaNewConsultationAction();
        return resolved.action && resolved.action.element ? resolved.action.element : null;
    }

    function findWedaHomeButton() {
        for (const doc of getAccessibleDocumentsDeep()) {
            try {
                const direct = doc.querySelector(SELECTOR_WEDA_HOME_IMAGE);
                if (direct) return direct.closest && direct.closest('a') ? direct.closest('a') : direct;
            } catch (_) {}

            try {
                const candidates = Array.from(doc.querySelectorAll('a, button, input, img'));
                const button = candidates.find(el => {
                    const text = elementActionText(el);
                    return (text.includes('menunavigate') && (text.includes('w_bleu') || text.includes('accueil')))
                        || /\baccueil\b/.test(text)
                        || /\bweda\b/.test(text);
                });
                if (button) return button.closest && button.closest('a') ? button.closest('a') : button;
            } catch (_) {}
        }
        return null;
    }

    function readPendingConnectorJob() {
        try {
            const raw = localStorage.getItem(CONNECTOR_PENDING_JOB_KEY);
            const job = raw ? JSON.parse(raw) : null;
            if (!job || !job.jobId) return null;
            const ageMs = Date.now() - Number(job.ts || 0);
            if (!Number.isFinite(ageMs) || ageMs < 0 || ageMs > CONNECTOR_PENDING_MAX_AGE_MS) {
                localStorage.removeItem(CONNECTOR_PENDING_JOB_KEY);
                return null;
            }
            return job;
        } catch (_) {
            return null;
        }
    }

    function writePendingConnectorJob(job) {
        try {
            localStorage.setItem(CONNECTOR_PENDING_JOB_KEY, JSON.stringify({
                ...job,
                ts: Number(job.ts || Date.now()),
                updatedAt: Date.now()
            }));
        } catch (_) {}
        syncConnectorRecordingIndicator(job);
    }

    function updatePendingConnectorJob(updates) {
        const current = readPendingConnectorJob() || {};
        const next = { ...current, ...updates, updatedAt: Date.now() };
        if (!next.ts) next.ts = Date.now();
        writePendingConnectorJob(next);
        return next;
    }

    function clearPendingConnectorJob() {
        try { localStorage.removeItem(CONNECTOR_PENDING_JOB_KEY); } catch (_) {}
        syncConnectorRecordingIndicator(null);
    }

    function getConnectorImportKey(request, currentPatientId, source) {
        if (source !== 'connector_auto' || !request || !request.id) return '';
        const patientId = normalizePatientId(currentPatientId || request.patient_id || '');
        return patientId + '::' + String(request.id || '');
    }

    function readConnectorImportedRequests() {
        let imported = {};
        try {
            const raw = localStorage.getItem(CONNECTOR_IMPORTED_REQUESTS_KEY);
            const parsed = raw ? JSON.parse(raw) : {};
            if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
                imported = parsed;
            }
        } catch (_) {
            imported = {};
        }

        const now = Date.now();
        let changed = false;
        Object.keys(imported).forEach(key => {
            const at = Number(imported[key] && imported[key].at || 0);
            if (!at || now - at < 0 || now - at > CONNECTOR_IMPORTED_REQUEST_MAX_AGE_MS) {
                delete imported[key];
                changed = true;
            }
        });
        if (changed) {
            try { localStorage.setItem(CONNECTOR_IMPORTED_REQUESTS_KEY, JSON.stringify(imported)); } catch (_) {}
        }
        return imported;
    }

    function getConnectorImportedRequest(key) {
        if (!key) return null;
        const imported = readConnectorImportedRequests();
        return imported[key] || null;
    }

    function markConnectorRequestImported(key, details = {}) {
        if (!key) return;
        const imported = readConnectorImportedRequests();
        imported[key] = {
            ...details,
            at: Date.now()
        };
        try { localStorage.setItem(CONNECTOR_IMPORTED_REQUESTS_KEY, JSON.stringify(imported)); } catch (_) {}
    }

    function acquireConnectorImportLock(key) {
        if (!key) return null;
        const now = Date.now();
        const lockId = now + ':' + Math.random().toString(36).slice(2);
        try {
            const raw = localStorage.getItem(CONNECTOR_IMPORT_LOCK_KEY);
            const current = raw ? JSON.parse(raw) : null;
            const ageMs = current && current.ts ? now - Number(current.ts || 0) : CONNECTOR_IMPORT_LOCK_TTL_MS + 1;
            if (current && current.key === key && ageMs >= 0 && ageMs < CONNECTOR_IMPORT_LOCK_TTL_MS) {
                return null;
            }

            localStorage.setItem(CONNECTOR_IMPORT_LOCK_KEY, JSON.stringify({ key, lockId, ts: now }));
            const savedRaw = localStorage.getItem(CONNECTOR_IMPORT_LOCK_KEY);
            const saved = savedRaw ? JSON.parse(savedRaw) : null;
            if (!saved || saved.key !== key || saved.lockId !== lockId) return null;
            return { key, lockId };
        } catch (error) {
            logEvent('warning', 'connector_import_lock_unavailable', 'Verrou import connecteur indisponible, import poursuivi.', {
                key,
                error: error && error.message ? error.message : String(error)
            });
            return { key, lockId: '' };
        }
    }

    function releaseConnectorImportLock(lock) {
        if (!lock || !lock.key || !lock.lockId) return;
        try {
            const raw = localStorage.getItem(CONNECTOR_IMPORT_LOCK_KEY);
            const current = raw ? JSON.parse(raw) : null;
            if (current && current.key === lock.key && current.lockId === lock.lockId) {
                localStorage.removeItem(CONNECTOR_IMPORT_LOCK_KEY);
            }
        } catch (_) {}
    }

    function wedaConsultationActionIsInvisible(action) {
        if (!action || !action.element) return true;
        return !isElementVisibleEnough(action.element);
    }

    async function triggerWedaNewConsultationAction(action) {
        if (!action) {
            return { triggered: false, mode: 'missing_action', clickOk: false, okPostBack: false, okFormSubmit: false };
        }

        const directPostBack = !!(action.postBack && action.postBack.eventTarget && wedaConsultationActionIsInvisible(action));
        if (directPostBack) {
            const postBackReport = triggerWedaPostBack(action.postBack, true);
            return {
                triggered: postBackReport.ok,
                mode: 'direct_postback_hidden_action',
                clickOk: false,
                ...postBackReport
            };
        }

        let clickOk = false;
        if (action.element) {
            clickOk = clickElementForWeda(action.element);
            if (clickOk) {
                return {
                    triggered: true,
                    mode: 'click',
                    clickOk,
                    okPostBack: false,
                    okFormSubmit: false
                };
            }
        }

        const postBackReport = triggerWedaPostBack(action.postBack, true);
        return {
            triggered: postBackReport.ok,
            mode: 'fallback_postback',
            clickOk,
            ...postBackReport
        };
    }

    async function openConsultationForConnector(job) {
        if (isWedaConsultationPage()) return true;
        if (!isWedaPatientHomePage()) {
            logEvent('warning', 'connector_open_consultation_wrong_page', 'Ouverture consultation impossible depuis cette page.', {
                job,
                href: location.href
            });
            showBadge('Connecteur WEDA : ouvre l’accueil patient pour créer la consultation.', true);
            updatePendingConnectorJob({ phase: 'manual_open_consultation', message: 'Accueil patient WEDA non détecté.' });
            return false;
        }

        const attempts = Number(job.openAttempts || 0) + 1;
        const actionInfo = findWedaNewConsultationAction();
        const fallbackAction = {
            element: null,
            source: 'fallback_postback_menu_general_0_1',
            score: 10,
            target: null,
            postBack: {
                eventTarget: POSTBACK_MENU_GENERAL_EVENTTARGET_WEDA,
                eventArgument: POSTBACK_NEW_CONSULTATION_GENERAL_WEDA,
                source: 'known_weda_new_consultation_fallback'
            }
        };
        const action = actionInfo.action || fallbackAction;

        updatePendingConnectorJob({
            phase: 'opening_consultation',
            openAttempts: attempts,
            openRequestedAt: Date.now(),
            message: 'Ouverture consultation WEDA.'
        });
        logEvent('info', 'connector_open_consultation', 'Ouverture consultation WEDA demandée.', {
            jobId: job.jobId,
            attempts,
            actionSource: action.source,
            actionTarget: action.target,
            actionPostBack: action.postBack || null,
            candidatesCount: actionInfo.candidates.length,
            candidates: actionInfo.candidates.slice(0, 8).map(candidate => ({
                source: candidate.source,
                score: candidate.score,
                target: candidate.target,
                postBack: candidate.postBack
            }))
        });
        showBadge('Connecteur WEDA : ouverture consultation...');
        const triggerReport = await triggerWedaNewConsultationAction(action);
        logEvent(triggerReport.triggered ? 'info' : 'warning', 'connector_open_consultation_triggered', 'Déclenchement ouverture consultation WEDA.', {
            jobId: job.jobId,
            attempts,
            actionSource: action.source,
            triggerReport
        });

        if (!triggerReport.triggered) {
            showBadge('Connecteur WEDA : ouverture consultation impossible automatiquement.', true);
            updatePendingConnectorJob({
                phase: 'manual_open_consultation',
                openAttempts: attempts,
                message: 'Déclenchement automatique consultation impossible.'
            });
            return false;
        }

        const opened = await waitFor(() => isWedaConsultationPage(), CONNECTOR_CONSULTATION_OPEN_TIMEOUT_MS, 300);
        if (opened) {
            updatePendingConnectorJob({ phase: 'import_result', message: 'Consultation ouverte.' });
            return true;
        }

        let formFallbackReport = null;
        if (action.postBack && action.postBack.eventTarget) {
            const okFormSubmit = submitPostBackForm(action.postBack.eventTarget, action.postBack.eventArgument || '');
            formFallbackReport = { okFormSubmit };
            if (okFormSubmit) {
                const openedAfterFormFallback = await waitFor(() => isWedaConsultationPage(), 8000, 300);
                if (openedAfterFormFallback) {
                    updatePendingConnectorJob({ phase: 'import_result', message: 'Consultation ouverte.' });
                    return true;
                }
            }
        }

        const latest = updatePendingConnectorJob({
            phase: attempts >= 3 ? 'manual_open_consultation' : 'open_consultation',
            openAttempts: attempts,
            message: attempts >= 3
                ? 'Ouverture automatique consultation non confirmée.'
                : 'Ouverture consultation non confirmée, nouvelle tentative possible.'
        });
        logEvent(attempts >= 3 ? 'error' : 'warning', 'connector_open_consultation_timeout', 'Consultation WEDA non détectée après déclenchement.', {
            ...latest,
            triggerReport,
            formFallbackReport,
            actionSource: action.source,
            actionPostBack: action.postBack || null
        });
        return false;
    }

    async function returnHomeWedaConnector(job) {
        if (isWedaPatientHomePage()) return true;
        logEvent('info', 'connector_return_home_start', 'Retour accueil WEDA demandé.', {
            jobId: job && job.jobId,
            href: location.href
        });

        let triggered = false;
        if (isWedaConsultationPage()) {
            triggered = callPostBack(POSTBACK_MENU_EVENTTARGET_WEDA, POSTBACK_RETURN_HOME_WEDA)
                || callPostBack(POSTBACK_MENU_GENERAL_EVENTTARGET_WEDA, POSTBACK_RETURN_HOME_GENERAL_WEDA)
                || callPostBack(POSTBACK_MENU_GENERAL_EVENTTARGET_WEDA, POSTBACK_RETURN_HOME_GENERAL_ALT_WEDA);
        }

        if (!triggered) {
            const home = findWedaHomeButton();
            if (home) triggered = clickElementForWeda(home);
        }

        if (!triggered) {
            logEvent('warning', 'connector_return_home_missing', 'Retour accueil WEDA non déclenché.', {
                jobId: job && job.jobId,
                href: location.href
            });
            showBadge('Résultat inséré. Retour accueil WEDA à faire manuellement.', true);
            return false;
        }

        showBadge('Résultat inséré. Retour accueil WEDA...');
        await waitFor(() => isWedaPatientHomePage(), 12000, 400);
        return true;
    }

    async function expandWedaHistoryForContext() {
        if (!isWedaPatientHomePage()) {
            logEvent('info', 'context_expand_skipped', 'Dépliage contexte ignoré : page patient WEDA non détectée.', {
                href: location.href
            });
            return { clicks: 0, reason: 'not_patient_home' };
        }

        let clicks = 0;
        let lastLength = getVisibleWedaTextDeep().length;

        while (clicks < MAX_WEDA_SUITE_CLICKS) {
            const button = getWedaSuiteButton();
            if (!button || !isElementVisibleEnough(button)) {
                return { clicks, reason: 'no_visible_suite_button' };
            }

            clicks += 1;
            logEvent('info', 'context_suite_click', 'Clic Suite WEDA avant collecte du contexte.', {
                click: clicks,
                beforeLength: lastLength,
                button: describeElement(button)
            });
            showBadge('Dépliage historique WEDA pour contexte...');
            clickElementForWeda(button);
            await sleep(WEDA_SUITE_CLICK_DELAY_MS);

            const nextLength = getVisibleWedaTextDeep().length;
            if (clicks > 1 && nextLength <= lastLength + 20) {
                return { clicks, reason: 'no_more_text', beforeLength: lastLength, afterLength: nextLength };
            }
            lastLength = nextLength;
        }

        return { clicks, reason: 'max_clicks_reached', finalLength: lastLength };
    }

    function extractContext(expandReport = null) {
        const patientText = getPatientPanelText();
        const visibleText = getVisibleWedaTextDeep().slice(0, 30000);
        return {
            patient_id: extractPatDk(location.href),
            patient_identity: inferPatientIdentity(patientText),
            patient_name: '',
            patient_birthdate: '',
            patient_age: '',
            patient_sex: '',
            page_url: location.href,
            page_title: document.title || '',
            visible_text: visibleText,
            patient_panel_text: patientText,
            context_source: isWedaPatientHomePage() ? 'patient_home_deep_visible_text' : 'current_page_deep_visible_text',
            context_expand_report: expandReport,
            collected_at: new Date().toISOString()
        };
    }

    async function sendContext(options = {}) {
        const skipDelay = !!(options && options.skipDelay);
        const source = options && options.source ? String(options.source) : 'manual';
        logEvent('info', 'context_collect_start', 'Collecte du contexte WEDA demandée.', {
            isPatientHome: isWedaPatientHomePage(),
            isConsultation: isWedaConsultationPage(),
            patient_id: extractPatDk(location.href),
            source,
            skipDelay
        });
        const delaySeconds = await getContextCaptureDelaySeconds();
        if (!skipDelay) {
            await waitBeforeContextCapture(delaySeconds);
        }
        const expandReport = await expandWedaHistoryForContext();
        const context = extractContext(expandReport);
        logEvent('info', 'send_context_start', 'Envoi du contexte WEDA vers l’application.', {
            patient_id: context.patient_id,
            patient_identity: context.patient_identity,
            visible_text_length: String(context.visible_text || '').length,
            expandReport,
            delaySeconds,
            source,
            skipDelay
        });
        await requestJson('POST', '/weda/context', context);
        logEvent('info', 'send_context_done', 'Contexte WEDA envoyé à l’application.', {
            patient_id: context.patient_id,
            source
        });
        if (!options || !options.silent) {
            showBadge('Contexte WEDA envoyé à l’assistant local.');
        }
        return context;
    }

    async function pollWedaContextRefreshRequest() {
        if (
            contextRefreshPollBusy
            || document.visibilityState === 'hidden'
            || !isPreferredWedaContextTab()
        ) return;
        contextRefreshPollBusy = true;
        let request = null;
        try {
            const response = await requestJson('GET', '/weda/context-refresh-request');
            request = response && response.request ? response.request : null;
            if (!request || !request.id || request.status !== 'pending') return;

            const claimResponse = await requestJson('POST', '/weda/context-refresh-claim', {
                request_id: request.id,
                responder_id: contextRefreshResponderId,
                page_url: location.href,
                page_title: document.title || '',
                visibility_state: document.visibilityState || '',
                has_focus: typeof document.hasFocus === 'function' ? document.hasFocus() : false
            });
            if (!claimResponse || !claimResponse.claimed) return;

            showBadge('DrFloW demande une nouvelle lecture du contexte WEDA...');
            logEvent(
                'info',
                'weda_context_refresh_claimed',
                'Nouvelle lecture du contexte demandée par DrFloW.',
                {
                    requestId: request.id,
                    href: location.href,
                    isPatientHome: isWedaPatientHomePage(),
                    isConsultation: isWedaConsultationPage()
                }
            );

            try {
                const context = await sendContext({
                    source: 'app_refresh_request',
                    skipDelay: true,
                    silent: true
                });
                await requestJson('POST', '/weda/context-refresh-ack', {
                    request_id: request.id,
                    responder_id: contextRefreshResponderId,
                    status: 'success',
                    patient_id_present: !!context.patient_id,
                    visible_text_length: String(context.visible_text || '').length,
                    page_url: location.href
                });
                showBadge('Contexte WEDA relu et actualisé dans DrFloW.');
                logEvent(
                    'info',
                    'weda_context_refresh_done',
                    'Contexte WEDA relu à la demande de DrFloW.',
                    {
                        requestId: request.id,
                        patientIdPresent: !!context.patient_id,
                        visibleTextLength: String(context.visible_text || '').length
                    }
                );
            } catch (error) {
                const errorMessage = error && error.message ? error.message : String(error);
                try {
                    await requestJson('POST', '/weda/context-refresh-ack', {
                        request_id: request.id,
                        responder_id: contextRefreshResponderId,
                        status: 'error',
                        error: errorMessage,
                        page_url: location.href
                    });
                } catch (_) {}
                showBadge('Contexte WEDA : actualisation impossible. Voir les logs.', true);
                logEvent(
                    'error',
                    'weda_context_refresh_error',
                    'Erreur pendant la relecture du contexte WEDA.',
                    { requestId: request.id, error: errorMessage }
                );
            }
        } catch (error) {
            if (request && request.id) {
                logEvent(
                    'warning',
                    'weda_context_refresh_poll_error',
                    'Erreur de suivi de la demande de contexte.',
                    {
                        requestId: request.id,
                        error: error && error.message ? error.message : String(error)
                    }
                );
            }
        } finally {
            contextRefreshPollBusy = false;
        }
    }

    function ownerDocumentOf(el) {
        return (el && el.ownerDocument) || document;
    }

    function ownerWindowOf(el) {
        const doc = ownerDocumentOf(el);
        return doc.defaultView || window;
    }

    function isInsidePanel(el) {
        return !!(el && el.closest && el.closest('#' + PANEL_ID));
    }

    function describeElement(el) {
        if (!el) return null;
        let path = '';
        try {
            const parts = [];
            let node = el;
            while (node && node.nodeType === 1 && parts.length < 5) {
                const tag = String(node.tagName || '').toLowerCase();
                const id = node.id ? '#' + node.id : '';
                const name = node.getAttribute && node.getAttribute('name') ? `[name="${node.getAttribute('name')}"]` : '';
                parts.unshift(tag + id + name);
                node = node.parentElement;
            }
            path = parts.join(' > ');
        } catch (_) {}

        let rect = null;
        try {
            const r = el.getBoundingClientRect();
            rect = {
                left: Math.round(r.left),
                top: Math.round(r.top),
                width: Math.round(r.width),
                height: Math.round(r.height)
            };
        } catch (_) {}

        return {
            tag: String(el.tagName || '').toLowerCase(),
            id: el.id || '',
            name: el.getAttribute ? String(el.getAttribute('name') || '') : '',
            type: el.getAttribute ? String(el.getAttribute('type') || '') : '',
            role: el.getAttribute ? String(el.getAttribute('role') || '') : '',
            contenteditable: el.getAttribute ? String(el.getAttribute('contenteditable') || '') : '',
            className: String(el.className || '').slice(0, 180),
            path,
            rect
        };
    }

    function isElementVisibleEnough(el) {
        if (!el || !el.getBoundingClientRect) return false;
        try {
            const win = ownerWindowOf(el);
            const style = win.getComputedStyle(el);
            if (style.display === 'none' || style.visibility === 'hidden') return false;
            const rect = el.getBoundingClientRect();
            return rect.width > 0 && rect.height > 0;
        } catch (_) {
            return true;
        }
    }

    function isEditableElement(el) {
        if (!el || !el.matches || isInsidePanel(el)) return false;
        const tag = String(el.tagName || '').toLowerCase();
        const type = String(el.getAttribute('type') || '').toLowerCase();
        const role = String(el.getAttribute('role') || '').toLowerCase();
        const hasContenteditable = !!(el.hasAttribute && el.hasAttribute('contenteditable'));
        const contenteditable = hasContenteditable ? String(el.getAttribute('contenteditable') || '').toLowerCase() : '';

        if (el.disabled || el.readOnly) return false;
        if (tag === 'textarea') return isElementVisibleEnough(el);
        if (tag === 'input') {
            if (/^(button|checkbox|color|file|hidden|image|radio|range|reset|submit)$/i.test(type)) return false;
            return isElementVisibleEnough(el);
        }
        if (el.isContentEditable || contenteditable === 'true' || (hasContenteditable && contenteditable === '')) return isElementVisibleEnough(el);
        if (role === 'textbox') return isElementVisibleEnough(el);
        return false;
    }

    function editableFromTarget(target) {
        if (!target) return null;
        const el = target.nodeType === 1 ? target : target.parentElement;
        if (!el) return null;
        if (isEditableElement(el)) return el;
        try {
            const closest = el.closest('textarea,input,[contenteditable="true"],[contenteditable=""],[role="textbox"]');
            return isEditableElement(closest) ? closest : null;
        } catch (_) {
            return null;
        }
    }

    function targetIsStillUsable(el) {
        if (!el || !el.isConnected) return false;
        return isEditableElement(el);
    }

    function rememberEditableTarget(target, reason = '') {
        const editable = editableFromTarget(target);
        if (!editable) return null;
        const previous = lastEditableTarget && lastEditableTarget.element;
        const shouldLog = previous !== editable || /focusin|mousedown/i.test(reason);
        lastEditableTarget = {
            element: editable,
            seenAt: Date.now(),
            reason,
            description: describeElement(editable)
        };
        if (shouldLog) {
            logEvent('info', 'editable_target_seen', 'Champ éditable WEDA mémorisé.', {
                reason,
                target: lastEditableTarget.description
            });
        }
        return editable;
    }

    function getAccessibleDocumentsDeep(initialDoc = document) {
        const docs = [];
        const seen = new Set();

        function addDoc(doc) {
            if (!doc || seen.has(doc)) return;
            seen.add(doc);
            docs.push(doc);
        }

        addDoc(initialDoc);
        addDoc(document);
        try {
            if (window.top && window.top.document) addDoc(window.top.document);
        } catch (_) {}

        for (let index = 0; index < docs.length; index += 1) {
            const doc = docs[index];
            try {
                Array.from(doc.querySelectorAll('iframe,frame')).forEach(frame => {
                    try {
                        if (frame.contentDocument) addDoc(frame.contentDocument);
                    } catch (_) {}
                });
            } catch (_) {}
        }

        return docs;
    }

    function getDeepActiveElement() {
        let doc = document;
        let active = null;
        for (let depth = 0; depth < 8; depth += 1) {
            try {
                active = doc.activeElement;
                if (!active || !/^(iframe|frame)$/i.test(active.tagName || '') || !active.contentDocument) {
                    return active;
                }
                doc = active.contentDocument;
            } catch (_) {
                return active;
            }
        }
        return active;
    }

    function findSingleVisibleEditableCandidate() {
        const candidates = [];
        const seen = new Set();
        getAccessibleDocumentsDeep().forEach(doc => {
            try {
                Array.from(doc.querySelectorAll('textarea,input,[contenteditable="true"],[contenteditable=""],[role="textbox"]'))
                    .forEach(el => {
                        if (seen.has(el) || !isEditableElement(el)) return;
                        seen.add(el);
                        candidates.push(el);
                    });
            } catch (_) {}
        });

        if (candidates.length === 1) {
            return {
                element: candidates[0],
                reason: 'single_visible_candidate',
                candidatesCount: candidates.length
            };
        }

        logEvent('warning', 'editable_target_ambiguous', 'Aucun champ actif unique trouvé pour l’import.', {
            candidatesCount: candidates.length,
            candidates: candidates.slice(0, 8).map(describeElement)
        });
        return {
            element: null,
            reason: candidates.length ? 'multiple_visible_candidates' : 'no_visible_candidate',
            candidatesCount: candidates.length
        };
    }

    function contentEditableLooksLikeWedaConsultationField(el) {
        if (!el || isInsidePanel(el)) return false;
        const tag = String(el.tagName || '').toLowerCase();
        const hasContenteditable = !!(el.hasAttribute && el.hasAttribute('contenteditable'));
        const contenteditable = hasContenteditable ? String(el.getAttribute('contenteditable') || '').toLowerCase() : '';
        return tag === 'body'
            ? (contenteditable === 'true' || el.isContentEditable)
            : (el.isContentEditable || contenteditable === 'true' || (hasContenteditable && contenteditable === ''));
    }

    function getFrameForDocument(doc) {
        try {
            return doc && doc.defaultView && doc.defaultView.frameElement ? doc.defaultView.frameElement : null;
        } catch (_) {
            return null;
        }
    }

    function getElementLabelSearchText(el) {
        if (!el) return '';
        const tag = String(el.tagName || '').toLowerCase();
        const selectedOptions = [];
        try {
            if (el.selectedOptions) {
                Array.from(el.selectedOptions).forEach(option => selectedOptions.push(option.text || option.label || ''));
            }
        } catch (_) {}

        if (tag === 'select') {
            return normalizeSearchText([
                selectedOptions.join(' '),
                el.value || '',
                el.getAttribute ? el.getAttribute('title') || '' : '',
                el.getAttribute ? el.getAttribute('aria-label') || '' : '',
                el.id || '',
                el.getAttribute ? el.getAttribute('name') || '' : ''
            ].join(' '));
        }

        return normalizeSearchText([
            el.innerText || '',
            el.textContent || '',
            el.value || '',
            el.getAttribute ? el.getAttribute('title') || '' : '',
            el.getAttribute ? el.getAttribute('aria-label') || '' : '',
            el.id || '',
            el.getAttribute ? el.getAttribute('name') || '' : '',
            selectedOptions.join(' ')
        ].join(' '));
    }

    function textLooksLikeInterrogatoire(text) {
        const value = normalizeSearchText(text);
        return value.includes('interrogatoire') || value.includes('histoire de la maladie');
    }

    function textLooksLikeExcludedClinicalExam(text) {
        const value = normalizeSearchText(text);
        return value.includes('examen clinique');
    }

    function getEditableTargetsInsideContainer(container) {
        const targets = [];
        const seen = new Set();

        function addTarget(el) {
            if (!el || seen.has(el) || !contentEditableLooksLikeWedaConsultationField(el) || !isEditableElement(el)) return;
            seen.add(el);
            targets.push(el);
        }

        if (!container || !container.querySelectorAll) return targets;

        try {
            Array.from(container.querySelectorAll('iframe,frame')).forEach(frame => {
                try {
                    const doc = frame.contentDocument;
                    if (doc && doc.body) addTarget(doc.body);
                    if (doc) {
                        Array.from(doc.querySelectorAll('[contenteditable="true"], [contenteditable=""]')).forEach(addTarget);
                    }
                } catch (_) {}
            });
        } catch (_) {}

        try {
            Array.from(container.querySelectorAll('[contenteditable="true"], [contenteditable=""]')).forEach(addTarget);
        } catch (_) {}

        return targets;
    }

    function getOuterElementForEditable(el) {
        const frame = getFrameForDocument(ownerDocumentOf(el));
        return frame || el;
    }

    function getElementRectSafe(el) {
        try {
            if (!el || !el.getBoundingClientRect) return null;
            const rect = el.getBoundingClientRect();
            return {
                left: Number(rect.left || 0),
                top: Number(rect.top || 0),
                width: Number(rect.width || 0),
                height: Number(rect.height || 0)
            };
        } catch (_) {
            return null;
        }
    }

    function chooseInterrogatoireTarget(labelElement, targets) {
        const labelRect = getElementRectSafe(labelElement);
        const scored = targets.map((target, index) => {
            const contextScore = scoreEditableForInterrogatoire(target);
            const outer = getOuterElementForEditable(target);
            const targetRect = getElementRectSafe(outer);
            let score = 1000 - index;

            if (contextScore.hasInterrogatoire) score += Math.max(0, contextScore.score);
            if (contextScore.hasExcludedExam) score -= 10000;

            if (labelRect && targetRect) {
                const labelCenterX = labelRect.left + labelRect.width / 2;
                const targetCenterX = targetRect.left + targetRect.width / 2;
                const dx = Math.abs(labelCenterX - targetCenterX);
                const dy = Math.abs((targetRect.top || 0) - (labelRect.top || 0));
                score += Math.max(0, 1200 - dx);
                score += Math.max(0, 400 - dy);
                if (targetRect.left >= labelRect.left - 30 && targetRect.left <= labelRect.left + Math.max(120, labelRect.width + 80)) {
                    score += 300;
                }
            }

            return {
                target,
                score,
                contextScore,
                targetRect
            };
        });

        scored.sort((a, b) => b.score - a.score);
        return scored[0] || null;
    }

    function findInterrogatoireTargetFromLabelElement(labelElement, docIndex = 0) {
        const labelText = getElementLabelSearchText(labelElement);
        if (!textLooksLikeInterrogatoire(labelText) || textLooksLikeExcludedClinicalExam(labelText)) return null;

        let container = labelElement;
        for (let depth = 0; container && depth < 8; depth += 1) {
            const containerText = getElementLabelSearchText(container);
            if (textLooksLikeExcludedClinicalExam(containerText) && !textLooksLikeInterrogatoire(containerText)) return null;

            const targets = getEditableTargetsInsideContainer(container);
            if (targets.length) {
                const best = chooseInterrogatoireTarget(labelElement, targets);
                if (!best || !targetIsStillUsable(best.target) || best.score < 500) {
                    container = container.parentElement;
                    continue;
                }
                return {
                    element: best.target,
                    reason: 'weda_interrogatoire_form_label',
                    target: describeElement(best.target),
                    candidatesCount: targets.length,
                    candidates: targets.slice(0, 6).map(target => ({
                        source: 'interrogatoire_container',
                        score: target === best.target ? best.score : 5000 - docIndex,
                        label: labelText.slice(0, 240),
                        target: describeElement(target)
                    }))
                };
            }

            container = container.parentElement;
        }

        return null;
    }

    function getContextTextsForEditable(el) {
        const contexts = [];
        const doc = ownerDocumentOf(el);
        const frame = getFrameForDocument(doc);

        function addText(node, source, depth) {
            if (!node) return;
            let text = '';
            try {
                text = getElementLabelSearchText(node);
            } catch (_) {
                text = '';
            }
            if (!text) return;
            contexts.push({ source, depth, text });
        }

        let node = frame || el;
        for (let depth = 0; node && depth < 8; depth += 1) {
            addText(node, 'self_or_ancestor', depth);
            try { addText(node.previousElementSibling, 'previous_sibling', depth); } catch (_) {}
            try { addText(node.parentElement && node.parentElement.previousElementSibling, 'parent_previous_sibling', depth); } catch (_) {}
            node = node.parentElement;
        }

        return contexts;
    }

    function scoreEditableForInterrogatoire(el) {
        const contexts = getContextTextsForEditable(el);
        let score = 0;
        let bestLabel = '';
        let hasInterrogatoire = false;
        let hasExcludedExam = false;

        contexts.forEach(context => {
            const text = context.text;
            const closeWeight = Math.max(1, 8 - Number(context.depth || 0));
            const isInterrogatoire = textLooksLikeInterrogatoire(text);
            const isExam = textLooksLikeExcludedClinicalExam(text);
            if (isInterrogatoire) {
                hasInterrogatoire = true;
                score += 800 * closeWeight;
                if (!bestLabel || text.length < bestLabel.length) bestLabel = text;
            }
            if (isExam) {
                hasExcludedExam = true;
                score -= 1200 * closeWeight;
            }
        });

        return {
            score,
            hasInterrogatoire,
            hasExcludedExam,
            label: bestLabel.slice(0, 240),
            contexts: contexts.slice(0, 8)
        };
    }

    function normalizePhrasePresenceText(text) {
        return normalizeSearchText(text)
            .replace(/[;,]+/g, ' ')
            .replace(/\s+/g, ' ')
            .trim();
    }

    function scoreEditableForClinicalExam(el) {
        const contexts = getContextTextsForEditable(el);
        let score = 0;
        let bestLabel = '';
        let hasClinicalExam = false;
        let hasInterrogatoire = false;

        contexts.forEach(context => {
            const text = context.text;
            const closeWeight = Math.max(1, 8 - Number(context.depth || 0));
            const isClinicalExam = textLooksLikeExcludedClinicalExam(text);
            const isInterrogatoire = textLooksLikeInterrogatoire(text);
            if (isClinicalExam) {
                hasClinicalExam = true;
                score += 800 * closeWeight;
                if (!bestLabel || text.length < bestLabel.length) bestLabel = text;
            }
            if (isInterrogatoire) {
                hasInterrogatoire = true;
                score -= 1200 * closeWeight;
            }
        });

        return {
            score,
            hasClinicalExam,
            hasInterrogatoire,
            label: bestLabel.slice(0, 240),
            contexts: contexts.slice(0, 8)
        };
    }

    function findWedaClinicalExamEditableTarget(primaryTarget = null) {
        if (targetIsStillUsable(primaryTarget)) {
            const primaryScore = scoreEditableForClinicalExam(primaryTarget);
            if (primaryScore.hasClinicalExam && !primaryScore.hasInterrogatoire && primaryScore.score > 0) {
                return {
                    element: primaryTarget,
                    reason: 'weda_clinical_exam_primary_target',
                    target: describeElement(primaryTarget),
                    candidatesCount: 1,
                    candidates: [{
                        source: 'primary_target',
                        score: primaryScore.score,
                        label: primaryScore.label,
                        target: describeElement(primaryTarget)
                    }]
                };
            }
        }

        const candidates = [];
        const emptyFallbacks = [];
        const seen = new Set();
        const docs = getAccessibleDocumentsDeep();

        function addCandidate(el, docIndex, source) {
            if (!el || seen.has(el) || el === primaryTarget) return;
            if (!contentEditableLooksLikeWedaConsultationField(el)) return;
            if (!isEditableElement(el)) return;
            seen.add(el);

            const score = scoreEditableForClinicalExam(el);
            const textLength = normalizeSpaces(el.innerText || el.textContent || '').length;
            const target = describeElement(el);

            if (score.hasClinicalExam && score.score > 0) {
                candidates.push({
                    element: el,
                    source,
                    score: score.score - docIndex * 3,
                    label: score.label,
                    textLength,
                    target
                });
            }

            if (textLength === 0) {
                emptyFallbacks.push({
                    element: el,
                    source,
                    score: 100 - docIndex,
                    label: '',
                    textLength,
                    target
                });
            }
        }

        docs.forEach((doc, docIndex) => {
            try {
                const body = doc.body;
                if (body && contentEditableLooksLikeWedaConsultationField(body)) {
                    addCandidate(body, docIndex, 'body_contenteditable');
                }
            } catch (_) {}

            try {
                Array.from(doc.querySelectorAll('[contenteditable="true"], [contenteditable=""]')).forEach(el => {
                    addCandidate(el, docIndex, 'contenteditable');
                });
            } catch (_) {}
        });

        candidates.sort((a, b) => b.score - a.score);
        if (candidates.length) {
            return {
                element: candidates[0].element,
                reason: 'weda_clinical_exam_context',
                target: candidates[0].target,
                candidatesCount: candidates.length,
                candidates: candidates.slice(0, 6).map(candidate => ({
                    source: candidate.source,
                    score: candidate.score,
                    label: candidate.label,
                    textLength: candidate.textLength,
                    target: candidate.target
                }))
            };
        }

        const bodyFallback = emptyFallbacks.find(candidate => {
            return candidate.target && candidate.target.tag === 'body';
        });
        const fallback = bodyFallback || (emptyFallbacks.length === 1 ? emptyFallbacks[0] : null);
        if (fallback) {
            return {
                element: fallback.element,
                reason: 'weda_clinical_exam_empty_secondary_fallback',
                target: fallback.target,
                candidatesCount: emptyFallbacks.length,
                candidates: emptyFallbacks.slice(0, 6).map(candidate => ({
                    source: candidate.source,
                    score: candidate.score,
                    label: candidate.label,
                    textLength: candidate.textLength,
                    target: candidate.target
                }))
            };
        }

        return {
            element: null,
            reason: emptyFallbacks.length ? 'multiple_empty_secondary_candidates' : 'no_weda_clinical_exam_field',
            target: null,
            candidatesCount: emptyFallbacks.length,
            candidates: emptyFallbacks.slice(0, 6).map(candidate => ({
                source: candidate.source,
                score: candidate.score,
                label: candidate.label,
                textLength: candidate.textLength,
                target: candidate.target
            }))
        };
    }

    function addMedicoLegalPhraseToClinicalExamField(primaryTarget, options = {}) {
        const targetInfo = findWedaClinicalExamEditableTarget(primaryTarget);
        const shouldNotify = !(options && options.silent) || (options && options.source === 'connector_auto');

        if (!targetIsStillUsable(targetInfo.element)) {
            logEvent('warning', 'clinical_exam_phrase_target_missing', 'Champ Examen Clinique introuvable pour la phrase médico-légale.', {
                source: options && options.source ? String(options.source) : '',
                primaryTarget: describeElement(primaryTarget),
                targetReason: targetInfo.reason,
                candidatesCount: targetInfo.candidatesCount || 0,
                candidates: targetInfo.candidates || []
            });
            if (shouldNotify) {
                showBadge('Phrase médico-légale : champ Examen Clinique introuvable.', true);
            }
            return {
                added: false,
                alreadyPresent: false,
                reason: targetInfo.reason,
                targetInfo
            };
        }

        const target = targetInfo.element;
        const currentText = String(target.innerText || target.textContent || '');
        if (normalizePhrasePresenceText(currentText).includes(normalizePhrasePresenceText(PHRASE_SECURITE_MEDICO_LEGALE))) {
            logEvent('info', 'clinical_exam_phrase_already_present', 'Phrase médico-légale déjà présente dans Examen Clinique.', {
                source: options && options.source ? String(options.source) : '',
                target: targetInfo.target,
                targetReason: targetInfo.reason
            });
            return {
                added: false,
                alreadyPresent: true,
                reason: 'already_present',
                targetInfo
            };
        }

        try {
            appendPlainTextToContentEditable(target, PHRASE_SECURITE_MEDICO_LEGALE);
            try { target.focus(); } catch (_) {}
            dispatchEditableCommitEvents(target, PHRASE_SECURITE_MEDICO_LEGALE);
            logEvent('info', 'clinical_exam_phrase_inserted', 'Phrase médico-légale ajoutée dans Examen Clinique.', {
                source: options && options.source ? String(options.source) : '',
                target: targetInfo.target,
                targetReason: targetInfo.reason
            });
            return {
                added: true,
                alreadyPresent: false,
                reason: 'inserted',
                targetInfo
            };
        } catch (error) {
            logEvent('error', 'clinical_exam_phrase_insert_error', 'Erreur ajout phrase médico-légale dans Examen Clinique.', {
                source: options && options.source ? String(options.source) : '',
                target: targetInfo.target,
                targetReason: targetInfo.reason,
                error: error && error.message ? error.message : String(error)
            });
            if (shouldNotify) {
                showBadge('Phrase médico-légale : insertion Examen Clinique impossible.', true);
            }
            return {
                added: false,
                alreadyPresent: false,
                reason: 'insert_error',
                targetInfo
            };
        }
    }

    let structuredWedaCorrections = [];

    function resetStructuredWedaCorrections() {
        structuredWedaCorrections = [];
    }

    function recordStructuredWedaCorrection(type, raw, corrected, reason) {
        structuredWedaCorrections.push({
            type,
            raw,
            corrected,
            reason,
            timestamp: Date.now()
        });
    }

    function getStructuredWedaCorrections() {
        return structuredWedaCorrections.slice();
    }

    function normalizeExtractionText(text) {
        return String(text || '')
            .normalize('NFD')
            .replace(/[\u0300-\u036f]/g, '')
            .replace(/œ/g, 'oe')
            .replace(/Œ/g, 'oe')
            .toLowerCase()
            .replace(/[’']/g, ' ')
            .replace(/\s+/g, ' ')
            .trim();
    }

    function normalizeWedaDecimal(value) {
        let text = String(value || '').trim().replace('.', ',');
        text = text.replace(/,(\d*?)0+$/, (_match, decimals) => decimals ? ',' + decimals : '');
        text = text.replace(/,$/, '');
        return text;
    }

    function pad2(value) {
        return String(value).padStart(2, '0');
    }

    function plausibleYear(value) {
        const year = parseInt(String(value || ''), 10);
        const currentYear = new Date().getFullYear();
        return Number.isFinite(year) && year >= 1990 && year <= currentYear + 5;
    }

    function plausibleFullDate(day, month, year) {
        const d = parseInt(day, 10);
        const m = parseInt(month, 10);
        const y = parseInt(year, 10);
        if (!plausibleYear(y) || !Number.isFinite(d) || !Number.isFinite(m)) return false;
        if (d < 1 || d > 31 || m < 1 || m > 12) return false;
        const date = new Date(y, m - 1, d);
        return date.getFullYear() === y && date.getMonth() === m - 1 && date.getDate() === d;
    }

    function extractDateFromContext(context) {
        const raw = String(context || '').replace(/\u00a0/g, ' ').replace(/\s+/g, ' ');
        const normalized = normalizeExtractionText(raw);
        let match = raw.match(/\b(\d{1,2})[\/\-.](\d{1,2})[\/\-.](19\d{2}|20\d{2})\b/);
        if (match && plausibleFullDate(match[1], match[2], match[3])) {
            return pad2(match[1]) + '/' + pad2(match[2]) + '/' + match[3];
        }

        match = raw.match(/\b(\d{1,2})[\/\-.](19\d{2}|20\d{2})\b/);
        if (match) {
            const month = parseInt(match[1], 10);
            if (month >= 1 && month <= 12 && plausibleYear(match[2])) return pad2(month) + '/' + match[2];
        }

        const monthMap = {
            janvier: '01',
            fevrier: '02',
            mars: '03',
            avril: '04',
            mai: '05',
            juin: '06',
            juillet: '07',
            aout: '08',
            septembre: '09',
            octobre: '10',
            novembre: '11',
            decembre: '12'
        };
        match = normalized.match(/\b(janvier|fevrier|mars|avril|mai|juin|juillet|aout|septembre|octobre|novembre|decembre)\s+(19\d{2}|20\d{2})\b/);
        if (match && plausibleYear(match[2])) return monthMap[match[1]] + '/' + match[2];

        match = normalized.match(/\b(19\d{2}|20\d{2})\b/);
        if (match && plausibleYear(match[1])) return match[1];
        return null;
    }

    function extractYearFromContext(context) {
        const date = extractDateFromContext(context);
        const match = String(date || '').match(/\b(19\d{2}|20\d{2})\b/);
        return match ? match[1] : null;
    }

    function splitExtractionSegments(text) {
        return String(text || '')
            .replace(/\u00a0/g, ' ')
            .replace(/[\n\r;]/g, '.')
            .split('.')
            .map(segment => segment.trim())
            .filter(Boolean);
    }

    function segmentAroundIndex(source, index) {
        const text = String(source || '');
        let start = 0;
        let end = text.length;
        ['.', ';', '\n', '\r'].forEach(separator => {
            const pos = text.lastIndexOf(separator, index);
            if (pos >= 0 && pos + 1 > start) start = pos + 1;
        });
        ['.', ';', '\n', '\r'].forEach(separator => {
            const pos = text.indexOf(separator, index);
            if (pos >= 0 && pos < end) end = pos;
        });
        const segment = text.slice(start, end).trim();
        if (segment.length <= 260) return segment;
        return text.slice(Math.max(0, index - 110), Math.min(text.length, index + 150)).trim();
    }

    function includesAny(source, values) {
        return values.some(value => source.includes(value));
    }

    function addUnique(list, value) {
        if (value && !list.includes(value)) list.push(value);
    }

    function uniqueArray(list) {
        const result = [];
        (Array.isArray(list) ? list : []).forEach(value => addUnique(result, value));
        return result;
    }

    function extractWedaWeightFromText(text) {
        const source = String(text || '').replace(/\u00a0/g, ' ').replace(/\s+/g, ' ');
        const regex = /(\d{1,3}(?:[,.]\d{1,2})?)\s*kg\b/gi;
        let match;
        while ((match = regex.exec(source)) !== null) {
            const raw = String(match[1] || '').trim();
            const number = parseFloat(raw.replace(',', '.'));
            if (!Number.isFinite(number) || number < 1) continue;
            let correctedNumber = number;
            let correctedText = raw;
            if (correctedNumber > 350) {
                const div10 = correctedNumber / 10;
                const div100 = correctedNumber / 100;
                if (div10 >= 1 && div10 <= 350) {
                    correctedNumber = div10;
                    correctedText = String(div10).replace('.', ',');
                    recordStructuredWedaCorrection('poids', raw + ' kg', correctedText + ' kg', 'poids supérieur à 350 kg divisé par 10');
                } else if (div100 >= 1 && div100 <= 350) {
                    correctedNumber = div100;
                    correctedText = String(div100).replace('.', ',');
                    recordStructuredWedaCorrection('poids', raw + ' kg', correctedText + ' kg', 'poids supérieur à 350 kg divisé par 100');
                }
            }
            if (correctedNumber <= 350) return normalizeWedaDecimal(correctedText);
        }
        return null;
    }

    function extractWedaHeightFromText(text) {
        const source = String(text || '').replace(/\u00a0/g, ' ').replace(/\s+/g, ' ');
        let match;
        const cmRegex = /(\d{2,3}(?:[,.]\d{1,2})?)\s*cm\b/gi;
        while ((match = cmRegex.exec(source)) !== null) {
            const number = parseFloat(String(match[1]).replace(',', '.'));
            if (!Number.isFinite(number)) continue;
            let height = number;
            if (height >= 10 && height <= 25) {
                height *= 10;
                recordStructuredWedaCorrection('taille', String(number) + ' cm', String(Math.round(height)) + ' cm', 'taille en cm trop basse multipliée par 10');
            } else if (height > 250 && height <= 2500) {
                height /= 10;
                recordStructuredWedaCorrection('taille', String(number) + ' cm', String(Math.round(height)) + ' cm', 'taille en cm trop haute divisée par 10');
            }
            if (height >= 30 && height <= 250) return String(Math.round(height));
        }

        const decimalMeterRegex = /\b([1-2])\s*[,.]\s*(\d{1,2})\s*m\b/gi;
        while ((match = decimalMeterRegex.exec(source)) !== null) {
            const meters = parseInt(match[1], 10);
            let cmPart = String(match[2] || '').trim();
            if (cmPart.length === 1) cmPart += '0';
            const height = meters * 100 + parseInt(cmPart, 10);
            if (height >= 30 && height <= 250) return String(height);
        }

        const meterCmRegex = /\b([1-2])\s*(?:m|metre|mètre|metres|mètres)\s*(\d{1,2})\b/gi;
        while ((match = meterCmRegex.exec(source)) !== null) {
            const meters = parseInt(match[1], 10);
            let cmPart = String(match[2] || '').trim();
            if (cmPart.length === 1) cmPart += '0';
            const height = meters * 100 + parseInt(cmPart, 10);
            if (height >= 30 && height <= 250) return String(height);
        }
        return null;
    }

    function normalizeDetectedTemperature(rawValue, sourceName) {
        let temperature = parseFloat(String(rawValue || '').replace(',', '.'));
        let corrected = String(rawValue || '').trim();
        if (!Number.isFinite(temperature)) return null;
        if (temperature >= 3 && temperature < 5) {
            temperature *= 10;
            corrected = String(temperature).replace('.', ',');
            recordStructuredWedaCorrection('température', String(rawValue) + ' °C', corrected + ' °C', 'température trop basse multipliée par 10');
        } else if (temperature > 45 && temperature <= 450) {
            temperature /= 10;
            corrected = String(temperature).replace('.', ',');
            recordStructuredWedaCorrection('température', String(rawValue) + ' °C', corrected + ' °C', 'température trop haute divisée par 10');
        }
        if (temperature >= 36 && temperature <= 45) return normalizeWedaDecimal(corrected);
        if (temperature >= 30 && temperature < 36) {
            recordStructuredWedaCorrection('température', String(rawValue) + ' °C', '37 °C', 'température inférieure à 36 °C remplacée par 37');
            logEvent('info', 'structured_temperature_low_corrected', 'Température explicite inférieure à 36 corrigée à 37.', { rawValue, sourceName });
            return '37';
        }
        return null;
    }

    function extractWedaTemperatureFromText(text) {
        const source = String(text || '').replace(/\u00a0/g, ' ').replace(/\s+/g, ' ');
        const searches = [
            {
                name: 'marqueur température',
                regex: /(?:^|[^a-z0-9])(?:t\s*[°º]?|temp(?:erature|érature)?|temperature|température)\s*[:=]?\s*(\d{1,3}(?:[,.]\d{1,2})?)\s*(?:°\s*c|º\s*c|\bc\b|degr[eé]s?\s*(?:c(?:elsius)?)?|celsius)?/gi
            },
            { name: 'unité °C', regex: /(\d{1,3}(?:[,.]\d{1,2})?)\s*(?:°\s*c|º\s*c|\bcelsius\b)/gi },
            { name: 'unité degrés', regex: /(\d{1,3}(?:[,.]\d{1,2})?)\s*degr[eé]s?\b/gi }
        ];
        for (const search of searches) {
            let match;
            while ((match = search.regex.exec(source)) !== null) {
                const value = normalizeDetectedTemperature(match[1], search.name);
                if (value) return value;
            }
        }
        return null;
    }

    function contextIndicatesHomeBloodPressure(context) {
        const normalized = normalizeExtractionText(context);
        const tokens = normalized.split(' ');
        return normalized.includes('automesure')
            || normalized.includes('auto mesure')
            || normalized.includes('auto-mesure')
            || tokens.includes('amt')
            || normalized.includes('domicile')
            || normalized.includes('maison')
            || normalized.includes('a la maison')
            || normalized.includes('a domicile')
            || normalized.includes('au domicile')
            || normalized.includes('chez lui')
            || normalized.includes('chez elle')
            || normalized.includes('moyenne tensionnelle')
            || normalized.includes('releve tensionnel');
    }

    function contextIndicatesBloodPressure(context) {
        const normalized = normalizeExtractionText(context);
        const tokens = normalized.split(' ');
        return tokens.includes('ta')
            || tokens.includes('pa')
            || tokens.includes('amt')
            || normalized.includes('tension')
            || normalized.includes('pression')
            || normalized.includes('arterielle')
            || contextIndicatesHomeBloodPressure(normalized);
    }

    function normalizeBloodPressure(sysRaw, diaRaw, withContext) {
        let sys = parseInt(String(sysRaw || '').trim(), 10);
        let dia = parseInt(String(diaRaw || '').trim(), 10);
        if (!Number.isFinite(sys) || !Number.isFinite(dia)) return null;
        if (withContext && sys >= 8 && sys <= 25 && dia >= 4 && dia <= 15 && sys > dia) {
            const oldSys = sys;
            const oldDia = dia;
            sys *= 10;
            dia *= 10;
            recordStructuredWedaCorrection('tension artérielle', String(oldSys) + '/' + String(oldDia), String(sys) + '/' + String(dia), 'format oral converti en mmHg');
        }
        if (sys >= 70 && sys <= 260 && dia >= 30 && dia <= 160 && sys > dia) {
            return {
                systolic: String(sys),
                diastolic: String(dia),
                text: String(sys) + '/' + String(dia),
                sysNum: sys,
                diaNum: dia
            };
        }
        return null;
    }

    function pressureMatchIsHomeMeasurement(source, matchStart, matchEnd) {
        const before = source.slice(Math.max(0, matchStart - 60), matchStart);
        const after = source.slice(matchEnd, Math.min(source.length, matchEnd + 45));
        const beforeNormalized = normalizeExtractionText(before);
        const afterNormalized = normalizeExtractionText(after);
        if (contextIndicatesHomeBloodPressure(beforeNormalized)) return true;
        const afterKeyword = afterNormalized.match(/\b(?:automesure|auto mesure|auto-mesure|amt|domicile|maison)\b/);
        if (!afterKeyword) return false;
        const textBeforeKeyword = afterNormalized.slice(0, afterKeyword.index);
        return !textBeforeKeyword.includes('(') && !textBeforeKeyword.includes(')') && !textBeforeKeyword.includes(';') && !textBeforeKeyword.includes('.');
    }

    function extractWedaBloodPressuresFromText(text) {
        let source = String(text || '').replace(/\u00a0/g, ' ').replace(/[\n\r]/g, ' ').replace(/ {2,}/g, ' ');
        const search = normalizeExtractionText(source);
        const results = { office: null, home: null };

        function registerHomeFromRegex(regex) {
            let match;
            while ((match = regex.exec(search)) !== null) {
                const pressure = normalizeBloodPressure(match[1], match[2], true);
                if (!pressure) continue;
                results.home = pressure;
                return true;
            }
            return false;
        }

        registerHomeFromRegex(/(?:^|[^a-z0-9])(?:amt|automesure|auto[ -]?mesure|a domicile|domicile|maison)[^0-9]{0,35}([0-9]{1,3}) *[/] *([0-9]{1,3})(?![0-9])/gi);
        if (!results.home) {
            registerHomeFromRegex(/([0-9]{1,3}) *[/] *([0-9]{1,3})(?![0-9])[^.;)]{0,45}(?:^|[^a-z0-9])(?:amt|automesure|auto[ -]?mesure|a domicile|domicile|maison)/gi);
        }

        const regex = /(?:^|[^0-9])([0-9]{1,3}) *[/] *([0-9]{1,3})(?![0-9])/g;
        let match;
        while ((match = regex.exec(source)) !== null) {
            const firstChar = String(match[0] || '').charAt(0);
            const prefixLength = (firstChar < '0' || firstChar > '9') ? 1 : 0;
            const matchStart = match.index + prefixLength;
            const matchEnd = regex.lastIndex;
            const before = source.slice(Math.max(0, matchStart - 90), matchStart);
            const after = source.slice(matchEnd, Math.min(source.length, matchEnd + 45));
            const context = normalizeExtractionText(before + ' ' + after);
            const withContext = contextIndicatesBloodPressure(context);
            const pressure = normalizeBloodPressure(match[1], match[2], withContext);
            if (!pressure || !withContext) continue;
            if (pressureMatchIsHomeMeasurement(source, matchStart, matchEnd)) {
                if (!results.home) results.home = pressure;
            } else if (!results.office) {
                results.office = pressure;
            }
            if (results.office && results.home) break;
        }
        return results;
    }

    function extractWedaMadrsFromText(text) {
        const source = normalizeExtractionText(String(text || '').replace(/\u00a0/g, ' '));
        const patterns = [
            /\b(?:madrs|mdrs|score madrs|score mdrs|echelle madrs|echelle mdrs|montgomery(?:\s+asberg)?)\b[^\d]{0,50}(\d{1,2})(?:\s*(?:\/|sur)\s*(\d{1,2}))?/gi,
            /(?:score|echelle|resultat|depistage moral)?[^\d]{0,25}(\d{1,2})(?:\s*(?:\/|sur)\s*(\d{1,2}))?[^\d]{0,55}\b(?:madrs|mdrs|montgomery(?:\s+asberg)?)\b/gi
        ];
        for (const regex of patterns) {
            let match;
            while ((match = regex.exec(source)) !== null) {
                const score = parseInt(match[1], 10);
                const denominator = match[2] ? parseInt(match[2], 10) : null;
                if (!Number.isFinite(score) || score < 0 || score > 60) continue;
                if (denominator !== null && denominator !== 60) continue;
                return String(score);
            }
        }
        return null;
    }

    function extractWedaMmsFromText(text) {
        const source = normalizeExtractionText(String(text || '').replace(/\u00a0/g, ' '));
        const patterns = [
            /\b(?:mms|mmse|score mms|score mmse|mini[\s-]*mental(?:\s+state)?(?:\s+examination)?|mini[\s-]*mental[\s-]*state)\b[^\d]{0,50}(\d{1,2})(?:\s*(?:\/|sur)\s*(\d{1,2}))?/gi,
            /(?:score|echelle|resultat|depistage cognitif)?[^\d]{0,20}(\d{1,2})(?:\s*(?:\/|sur)\s*(\d{1,2}))?[^\d]{0,50}\b(?:mms|mmse|mini[\s-]*mental(?:\s+state)?(?:\s+examination)?|mini[\s-]*mental[\s-]*state)\b/gi
        ];
        for (const regex of patterns) {
            let match;
            while ((match = regex.exec(source)) !== null) {
                const score = parseInt(match[1], 10);
                const denominator = match[2] ? parseInt(match[2], 10) : null;
                if (!Number.isFinite(score) || score < 0 || score > 30) continue;
                if (denominator !== null && denominator !== 30) continue;
                return String(score);
            }
        }
        return null;
    }

    function extractWedaTobaccoFromText(text) {
        const raw = String(text || '').replace(/\u00a0/g, ' ').replace(/\s+/g, ' ');
        const source = normalizeExtractionText(raw);
        if (/\bancien(?:ne)?\s+fumeur\b/.test(source)
            || source.includes('ancien tabagisme')
            || source.includes('tabac sevre')
            || source.includes('sevre du tabac')
            || source.includes('ne fume plus')
            || source.includes('a arrete de fumer')) return 'Ancien fumeur';
        if (/\bnon[-\s]?fumeur\b/.test(source)
            || source.includes('ne fume pas')
            || source.includes('pas de tabac')
            || source.includes('aucun tabac')
            || source.includes('jamais fume')
            || source.includes('tabagisme non')) return 'Non fumeur';

        let match;
        const packetRegex = /(\d+(?:[,.]\d{1,2})?|demi)\s*(?:paquets?|paq\.?)\s*(?:\/|\bpar\b)?\s*(?:jour|j)\b/gi;
        while ((match = packetRegex.exec(raw)) !== null) {
            let value = String(match[1] || '').trim();
            if (/demi/i.test(value)) value = '0,5';
            const number = parseFloat(value.replace(',', '.'));
            if (Number.isFinite(number) && number > 0 && number <= 5) return normalizeWedaDecimal(value) + ' paquet/j';
        }

        const cigaretteRegex = /(\d{1,3}(?:[,.]\d{1,2})?)\s*(?:cigarettes?|cig\.?|cigs?|clopes?)\s*(?:\/|\bpar\b)?\s*(?:jour|j)\b/gi;
        while ((match = cigaretteRegex.exec(raw)) !== null) {
            const value = String(match[1] || '').trim();
            const number = parseFloat(value.replace(',', '.'));
            if (Number.isFinite(number) && number > 0 && number <= 120) return normalizeWedaDecimal(value) + ' cig/j';
        }

        const contextRegex = /\b(?:tabac|fume|tabagisme|fumeur)\b[^\d]{0,40}(\d{1,3}(?:[,.]\d{1,2})?)\s*(?:\/|\bpar\b)?\s*(?:jour|j)\b/gi;
        while ((match = contextRegex.exec(raw)) !== null) {
            const value = String(match[1] || '').trim();
            const number = parseFloat(value.replace(',', '.'));
            if (Number.isFinite(number) && number > 0 && number <= 120) return normalizeWedaDecimal(value) + ' cig/j';
        }
        if (source.includes('fumeur actif') || source.includes('tabagisme actif') || source.includes('tabac actif')) return 'Fumeur actif';
        return null;
    }

    function alcoholContextLooksRelevant(normalizedContext) {
        return normalizedContext.includes('alcool')
            || normalizedContext.includes('vin')
            || normalizedContext.includes('biere')
            || normalizedContext.includes('bieres')
            || normalizedContext.includes('aperitif')
            || normalizedContext.includes('apero')
            || normalizedContext.includes('spiritueux')
            || normalizedContext.includes('whisky')
            || normalizedContext.includes('boit')
            || normalizedContext.includes('consommation');
    }

    function extractWedaAlcoholFromText(text) {
        const raw = String(text || '').replace(/\u00a0/g, ' ').replace(/\s+/g, ' ');
        const source = normalizeExtractionText(raw);
        if (source.includes('sevre alcool') || source.includes('sevre de l alcool') || source.includes('ancien ethylisme')) return 'Sevré';
        if (source.includes('pas d alcool')
            || source.includes('pas de consommation d alcool')
            || source.includes('aucun alcool')
            || source.includes('ne boit pas')
            || source.includes('zero alcool')
            || source.includes('0 alcool')
            || source.includes('abstinent')) return 'Pas d’alcool';

        let match;
        const glassRegex = /(\d{1,3}(?:[,.]\d{1,2})?)\s*(?:verres?|unites?|unités?)\s*(?:d['’ ]?alcool)?\s*(?:\/|\bpar\b)?\s*(jour|j|semaine|sem|mois|week[-\s]?end|we)\b/gi;
        while ((match = glassRegex.exec(raw)) !== null) {
            const value = String(match[1] || '').trim();
            const unit = normalizeExtractionText(match[2] || '');
            const number = parseFloat(value.replace(',', '.'));
            if (!Number.isFinite(number) || number <= 0 || number > 300) continue;
            const context = raw.slice(Math.max(0, match.index - 100), Math.min(raw.length, match.index + 140));
            const normalizedContext = normalizeExtractionText(context);
            if (normalizedContext.includes('eau') || !alcoholContextLooksRelevant(normalizedContext)) continue;
            let suffix = '/j';
            if (unit.includes('sem')) suffix = '/sem';
            else if (unit.includes('mois')) suffix = '/mois';
            else if (unit.includes('week') || unit === 'we') suffix = '/week-end';
            return normalizeWedaDecimal(value) + ' verres' + suffix;
        }

        const drinkRegex = /(\d{1,3}(?:[,.]\d{1,2})?)\s*(?:verres?)\s*(?:de\s+)?(?:vin|bi[eè]re|bieres|alcool|whisky|spiritueux)\s*(?:\/|\bpar\b)?\s*(jour|j|semaine|sem|mois|week[-\s]?end|we)?\b/gi;
        while ((match = drinkRegex.exec(raw)) !== null) {
            const value = String(match[1] || '').trim();
            const unit = normalizeExtractionText(match[2] || '');
            const number = parseFloat(value.replace(',', '.'));
            if (!Number.isFinite(number) || number <= 0 || number > 300) continue;
            let suffix = '';
            if (unit.includes('jour') || unit === 'j') suffix = '/j';
            else if (unit.includes('sem')) suffix = '/sem';
            else if (unit.includes('mois')) suffix = '/mois';
            else if (unit.includes('week') || unit === 'we') suffix = '/week-end';
            return normalizeWedaDecimal(value) + ' verres' + suffix;
        }

        if (source.includes('alcool occasionnel')
            || source.includes('consommation occasionnelle')
            || source.includes('boit occasionnellement')
            || source.includes('alcool social')) return 'Occasionnel';
        return null;
    }

    function contextIndicatesScreeningTodo(normalizedContext) {
        return includesAny(normalizedContext, [
            'a faire',
            'a prevoir',
            'a programmer',
            'a planifier',
            'a realiser',
            'a refaire',
            'a renouveler',
            'doit faire',
            'devra faire',
            'prescrit',
            'prescription',
            'non fait',
            'non faite',
            'non realise',
            'non realisee',
            'jamais fait',
            'jamais faite',
            'pas fait',
            'pas faite',
            'en attente',
            'absence de depistage',
            'absence de test',
            'pas de depistage',
            'pas de test',
            'pas a jour',
            'non a jour',
            'plus a jour',
            'en retard'
        ]);
    }

    function extractScreeningFromText(text, options) {
        const source = String(text || '').replace(/\u00a0/g, ' ').replace(/\s+/g, ' ');
        const regex = options.regex;
        let match;
        let foundDate = null;
        let foundTodo = false;
        while ((match = regex.exec(source)) !== null) {
            const segment = segmentAroundIndex(source, match.index);
            const normalized = normalizeExtractionText(segment);
            if (contextIndicatesScreeningTodo(normalized)) {
                foundTodo = true;
                continue;
            }
            const date = extractDateFromContext(segment);
            if (date && !foundDate) foundDate = date;
        }
        if (foundTodo) return 'A faire';
        if (foundDate) return foundDate;
        return null;
    }

    function extractWedaHemocultFromText(text) {
        return extractScreeningFromText(text, {
            regex: /\b(?:h[eé]mocult|hemocult|h[eé]moccult|hemoccult|test\s+immunologique|fit|test\s+fit|depistage\s+colorectal|d[eé]pistage\s+colorectal|depistage\s+cancer\s+colorectal|d[eé]pistage\s+cancer\s+colorectal|depistage\s+ccr|d[eé]pistage\s+ccr|test\s+colorectal|recherche\s+de\s+sang\s+dans\s+les\s+selles|sang\s+dans\s+les\s+selles)\b/gi
        });
    }

    function extractWedaPapSmearFromText(text) {
        return extractScreeningFromText(text, {
            regex: /\b(?:frottis|fcu|fcv|cervico[-\s]*uterin|cervico[-\s]*ut[eé]rin|cervico[-\s]*uterine|cervico[-\s]*ut[eé]rine|cervico[-\s]*vaginal|cervico[-\s]*vaginale|hpv|test\s+hpv)\b/gi
        });
    }

    function extractWedaMammographyFromText(text) {
        return extractScreeningFromText(text, {
            regex: /\b(?:mammographie|mammo|depistage\s+mammaire|d[eé]pistage\s+mammaire|depistage\s+du\s+sein|d[eé]pistage\s+du\s+sein)\b/gi
        });
    }

    function extractAgeFromContext(context) {
        const normalized = normalizeExtractionText(context);
        const match = normalized.match(/\b(?:a|age de|l age de|a l age de)\s*(\d{1,3})\s*ans\b/);
        if (!match) return null;
        const age = parseInt(match[1], 10);
        if (!Number.isFinite(age) || age < 0 || age > 120) return null;
        return String(age) + ' ans';
    }

    function extractWedaDentistFromText(text) {
        const source = String(text || '').replace(/\u00a0/g, ' ').replace(/\s+/g, ' ');
        const regex = /\b(?:dentiste|dentaire|dentaires|chirurgien[-\s]*dentiste|chirurgienne[-\s]*dentiste|consultation\s+dentaire|consultations\s+dentaires|controle\s+dentaire|contrôle\s+dentaire|bilan\s+dentaire|soins\s+dentaires|suivi\s+dentaire|rdv\s+dentiste|rendez[-\s]*vous\s+dentiste)\b/gi;
        let match;
        let todo = false;
        let ageFound = null;
        while ((match = regex.exec(source)) !== null) {
            const segment = segmentAroundIndex(source, match.index);
            const normalized = normalizeExtractionText(segment);
            const year = extractYearFromContext(segment);
            if (year) return year;
            const age = extractAgeFromContext(segment);
            if (age && !ageFound) ageFound = age;
            if (includesAny(normalized, [
                'a faire',
                'a prevoir',
                'a programmer',
                'a planifier',
                'a realiser',
                'a reprendre',
                'doit voir',
                'devra voir',
                'controle a faire',
                'bilan a faire',
                'consultation a prevoir',
                'rdv a prendre',
                'rendez vous a prendre',
                'non fait',
                'non realise',
                'pas fait',
                'non a jour',
                'pas a jour',
                'plus a jour',
                'en retard',
                'pas vu de dentiste',
                'n a pas vu de dentiste',
                'jamais vu de dentiste',
                'absence de suivi dentaire',
                'depuis longtemps'
            ])) todo = true;
        }
        if (ageFound) return ageFound;
        if (todo) return 'A faire';
        return null;
    }

    function extractWedaDtpFromText(text) {
        const source = String(text || '').replace(/\u00a0/g, ' ').replace(/\s+/g, ' ');
        const regex = /\b(?:d\s*\.?\s*t\s*\.?\s*p|dtp|diphterie[-\s]*tetanos[-\s]*polio|dipht[eé]rie[-\s]*t[eé]tanos[-\s]*polio|t[eé]tanos[-\s]*polio|vaccin\s+(?:du\s+)?t[eé]tanos|vaccination\s+(?:du\s+)?t[eé]tanos|rappel\s+(?:du\s+)?t[eé]tanos|revaxis|boostrix|repevax)\b/gi;
        let match;
        let todo = false;
        let ageFound = null;
        while ((match = regex.exec(source)) !== null) {
            const segment = segmentAroundIndex(source, match.index);
            const normalized = normalizeExtractionText(segment);
            const year = extractYearFromContext(segment);
            if (year) return year;
            const age = extractAgeFromContext(segment);
            if (age && !ageFound) ageFound = age;
            if (contextIndicatesScreeningTodo(normalized) || normalized.includes('retard vaccinal')) todo = true;
        }
        if (ageFound) return ageFound;
        if (todo) return 'A faire';
        return null;
    }

    function extractWedaHpvFromText(text) {
        const segments = splitExtractionSegments(text);
        let done = false;
        let notDone = false;
        for (const segment of segments) {
            const normalized = normalizeExtractionText(segment);
            const relevant = normalized.includes('gardasil')
                || normalized.includes('papillomavirus')
                || normalized.includes('papilloma virus')
                || (normalized.includes('hpv') && (normalized.includes('vaccin') || normalized.includes('vaccination') || normalized.includes('vaccine')));
            if (!relevant) continue;
            if (includesAny(normalized, [
                'non fait',
                'non faite',
                'pas fait',
                'pas faite',
                'non realise',
                'pas realise',
                'pas eu',
                'jamais eu',
                'absence de vaccin',
                'absence de vaccination',
                'pas de vaccin',
                'pas de vaccination',
                'non vaccine',
                'pas vaccine',
                'a faire',
                'a prevoir',
                'a programmer',
                'a proposer',
                'refus'
            ])) {
                notDone = true;
                continue;
            }
            if (includesAny(normalized, [
                'fait',
                'faite',
                'realise',
                'realisee',
                'effectue',
                'effectuee',
                'a eu',
                'a recu',
                'recu',
                'injecte',
                'vaccine',
                'vaccination complete',
                'schema complet',
                'a jour',
                '1ere dose',
                'premiere dose',
                '2e dose',
                'deuxieme dose',
                '3e dose',
                'troisieme dose'
            ])) done = true;
        }
        if (notDone) return 'Non fait';
        if (done) return 'Fait';
        return null;
    }

    function segmentConcernsFeetExam(normalized) {
        return normalized.includes('examen des pieds')
            || normalized.includes('examen du pied')
            || normalized.includes('pieds examines')
            || normalized.includes('pied examine')
            || normalized.includes('pied diabetique')
            || normalized.includes('monofilament')
            || normalized.includes('sensibilite plantaire')
            || normalized.includes('pouls pedieux')
            || normalized.includes('pouls tibiaux')
            || normalized.includes('plaie du pied')
            || normalized.includes('podologue')
            || normalized.includes('pedicure podologue')
            || normalized.includes('bilan podologique')
            || normalized.includes('suivi podologique');
    }

    function extractWedaFeetExamFromText(text) {
        const segments = splitExtractionSegments(text);
        let today = false;
        let done = false;
        let todo = false;
        for (const segment of segments) {
            const normalized = normalizeExtractionText(segment);
            if (!segmentConcernsFeetExam(normalized)) continue;
            const year = extractYearFromContext(segment);
            if (year) return year;
            if (contextIndicatesScreeningTodo(normalized)
                || normalized.includes('pas examine')
                || normalized.includes('pas vu')
                || normalized.includes('absence de suivi')
                || normalized.includes('absence d examen')) {
                todo = true;
                continue;
            }
            if (includesAny(normalized, ['ce jour', 'aujourd hui', 'aujourdhui', 'pendant la consultation', 'fait en consultation', 'realise ce jour', 'fait ce jour'])) {
                today = true;
                continue;
            }
            if (includesAny(normalized, ['fait', 'faite', 'realise', 'realisee', 'effectue', 'effectuee', 'examine', 'normal', 'sensibilite conservee', 'monofilament normal', 'vu podologue', 'bilan podologique'])) done = true;
        }
        if (today) return 'Ce jour';
        if (todo) return 'A faire';
        if (done) return 'Fait';
        return null;
    }

    function segmentConcernsFundus(normalized) {
        const spaced = ' ' + normalized + ' ';
        return normalized.includes('fond d oeil')
            || normalized.includes('fond d œil')
            || normalized.includes('fonds d oeil')
            || spaced.includes(' fo ')
            || normalized.includes('ophtalmo')
            || normalized.includes('ophtalmologue')
            || normalized.includes('ophtalmologie')
            || normalized.includes('retinographie')
            || normalized.includes('retinopathie diabetique')
            || normalized.includes('depistage retinopathie');
    }

    function extractWedaFundusFromText(text) {
        const segments = splitExtractionSegments(text);
        let todo = false;
        for (const segment of segments) {
            const normalized = normalizeExtractionText(segment);
            if (!segmentConcernsFundus(normalized)) continue;
            const year = extractYearFromContext(segment);
            if (year) return year;
            if (contextIndicatesScreeningTodo(normalized)
                || normalized.includes('a voir')
                || normalized.includes('a revoir')
                || normalized.includes('orienter vers')
                || normalized.includes('adresser a')
                || normalized.includes('pas vu')
                || normalized.includes('absence de suivi')) todo = true;
        }
        if (todo) return 'A faire';
        return null;
    }

    function segmentConcernsCardiologist(normalized) {
        const spaced = ' ' + normalized + ' ';
        return spaced.includes(' cardio ')
            || normalized.includes('cardiologue')
            || normalized.includes('cardiologie')
            || normalized.includes('consultation cardio')
            || normalized.includes('bilan cardio')
            || normalized.includes('avis cardio')
            || normalized.includes('echographie cardiaque')
            || normalized.includes('echo cardiaque')
            || normalized.includes('echocardiographie')
            || normalized.includes('holter')
            || normalized.includes('ecg');
    }

    function extractWedaCardiologistFromText(text) {
        const segments = splitExtractionSegments(text);
        let todo = false;
        for (const segment of segments) {
            const normalized = normalizeExtractionText(segment);
            if (!segmentConcernsCardiologist(normalized)) continue;
            const year = extractYearFromContext(segment);
            if (year) return year;
            if (includesAny(normalized, [
                'a voir',
                'a revoir',
                'a prevoir',
                'a programmer',
                'a planifier',
                'a adresser',
                'a orienter',
                'orienter vers',
                'doit voir',
                'devra voir',
                'rdv a prendre',
                'rendez vous a prendre',
                'consultation a prevoir',
                'avis a demander',
                'bilan a faire',
                'non vu',
                'pas vu',
                'absence de suivi',
                'pas de suivi',
                'non a jour',
                'pas a jour',
                'en retard'
            ])) todo = true;
        }
        if (todo) return 'A voir';
        return null;
    }

    function segmentNegatesTheme(normalizedSegment, themes) {
        const normalized = ' ' + normalizeExtractionText(normalizedSegment) + ' ';
        const list = Array.isArray(themes) ? themes : [themes];
        return list.some(rawTheme => {
            const theme = normalizeExtractionText(rawTheme);
            if (!theme) return false;
            return [
                'pas de ' + theme,
                'pas d ' + theme,
                'absence de ' + theme,
                'absence d ' + theme,
                'aucun ' + theme,
                'aucune ' + theme,
                'sans ' + theme,
                'ni ' + theme,
                theme + ' absent',
                theme + ' negatif',
                theme + ' exclu',
                theme + ' ecarte'
            ].some(expression => normalized.includes(' ' + expression + ' '));
        });
    }

    function anyAffirmativeSegment(text, themes, predicate) {
        return splitExtractionSegments(text).some(segment => {
            const normalized = normalizeExtractionText(segment);
            if (segmentNegatesTheme(normalized, themes)) return false;
            return predicate(normalized, segment);
        });
    }

    function alcoholGlassesPerWeek(value) {
        const normalized = normalizeExtractionText(value).replace(',', '.');
        const number = parseFloat(normalized);
        if (!Number.isFinite(number)) return null;
        if (normalized.includes('/j') || normalized.includes('par jour')) return number * 7;
        if (normalized.includes('/sem') || normalized.includes('par semaine')) return number;
        if (normalized.includes('/mois') || normalized.includes('par mois')) return number / 4.345;
        if (normalized.includes('/week-end') || normalized.includes('/week end') || normalized.includes('/we')) return number;
        return null;
    }

    function textIndicatesAlcoholProblem(normalizedSource) {
        return anyAffirmativeSegment(normalizedSource, ['alcool', 'alcoolisme', 'ethylisme'], normalized => includesAny(normalized, [
            'alcoolisme',
            'ethylisme',
            'dependance alcool',
            'dependance a l alcool',
            'trouble de l usage d alcool',
            'mesusage alcool',
            'abus d alcool',
            'consommation excessive d alcool',
            'alcoolisation excessive',
            'intoxication alcoolique',
            'ivresse',
            'sevrage alcool',
            'ancien ethylisme',
            'bouteille de whisky',
            'bouteille de vodka',
            'bouteille de rhum',
            'bouteille de pastis'
        ]));
    }

    function wedaAlcoholTagIndicated(text) {
        const raw = String(text || '').replace(/\u00a0/g, ' ');
        const normalized = normalizeExtractionText(raw);
        const alcohol = extractWedaAlcoholFromText(raw);
        if (textIndicatesAlcoholProblem(normalized)) return true;
        if (!alcohol) return false;
        if (alcohol === 'Pas d’alcool' || alcohol === 'Occasionnel') return false;
        if (alcohol === 'Sevré') return true;
        const weekly = alcoholGlassesPerWeek(alcohol);
        return Number.isFinite(weekly) && weekly > 4;
    }

    function wedaFallTagIndicated(text) {
        return splitExtractionSegments(text).some(segment => {
            const normalized = normalizeExtractionText(segment);
            if (includesAny(normalized, ['pas de chute', 'aucune chute', 'absence de chute', 'sans chute', 'n a pas chute', 'pas tombe', 'ne tombe pas', 'risque de chute', 'prevention des chutes'])) return false;
            return normalized.includes('chute')
                || normalized.includes('a chute')
                || normalized.includes('est tombe')
                || normalized.includes('est tombee')
                || normalized.includes('traumatisme apres chute')
                || normalized.includes('traumatisme suite a chute');
        });
    }

    function textIndicatesBloodPressureTreatment(normalized) {
        return includesAny(normalized, [
            'traitement antihypertenseur',
            'antihypertenseur',
            'traitement contre la tension',
            'traitement pour la tension',
            'traitement hta',
            'sous traitement pour hta',
            'ramipril',
            'perindopril',
            'lisinopril',
            'enalapril',
            'candesartan',
            'losartan',
            'valsartan',
            'irbesartan',
            'telmisartan',
            'olmesartan',
            'amlodipine',
            'lercanidipine',
            'nicardipine',
            'hydrochlorothiazide',
            'indapamide',
            'furosemide',
            'spironolactone'
        ]);
    }

    function wedaHtaTagIndicated(text) {
        const raw = String(text || '').replace(/\u00a0/g, ' ');
        const pressures = extractWedaBloodPressuresFromText(raw);
        if (pressures.office && (pressures.office.sysNum >= 140 || pressures.office.diaNum >= 90)) return true;
        if (pressures.home && (pressures.home.sysNum >= 135 || pressures.home.diaNum >= 85)) return true;
        return anyAffirmativeSegment(raw, ['hta', 'hypertension', 'hypertension arterielle', 'antihypertenseur', 'traitement tension'], normalized => {
            const spaced = ' ' + normalized + ' ';
            return textIndicatesBloodPressureTreatment(normalized)
                || spaced.includes(' hta ')
                || normalized.includes('hypertension arterielle')
                || normalized.includes('traitement contre la tension')
                || normalized.includes('traitement pour la tension');
        });
    }

    function textIndicatesDepressionTreatment(normalized) {
        return includesAny(normalized, [
            'traitement antidepresseur',
            'sous antidepresseur',
            'traitement contre la depression',
            'traitement pour depression',
            'sertraline',
            'zoloft',
            'escitalopram',
            'seroplex',
            'paroxetine',
            'deroxat',
            'fluoxetine',
            'prozac',
            'venlafaxine',
            'effexor',
            'duloxetine',
            'cymbalta',
            'mirtazapine',
            'norset',
            'vortioxetine',
            'brintellix',
            'citalopram',
            'seropram',
            'mianserine'
        ]);
    }

    function extractBnpValuesFromText(text) {
        const source = normalizeExtractionText(text)
            .replace(/[:=><\/-]/g, ' ');
        const tokens = source.split(' ').filter(Boolean);
        const values = [];
        tokens.forEach((token, index) => {
            const isBnp = token === 'bnp'
                || token === 'ntprobnp'
                || (token === 'nt' && tokens[index + 1] === 'pro' && tokens[index + 2] === 'bnp');
            if (!isBnp) return;
            for (let i = Math.max(0, index - 4); i <= Math.min(tokens.length - 1, index + 5); i += 1) {
                const digits = String(tokens[i] || '').replace(/\D/g, '');
                if (!digits) continue;
                const value = parseInt(digits, 10);
                if (Number.isFinite(value)) values.push(value);
            }
        });
        return values;
    }

    function extractWedaTagsFromText(text) {
        const tags = [];
        const raw = String(text || '').replace(/\u00a0/g, ' ');
        const tobacco = extractWedaTobaccoFromText(raw);
        const madrs = parseInt(extractWedaMadrsFromText(raw), 10);

        if (wedaAlcoholTagIndicated(raw)) addUnique(tags, 'Alcool');
        if (tobacco && tobacco !== 'Non fumeur') addUnique(tags, 'Tabac');
        if (wedaHtaTagIndicated(raw)) addUnique(tags, 'HTA');
        if (anyAffirmativeSegment(raw, ['dt2', 'diabete', 'diabete type 2'], normalized => {
            const spaced = ' ' + normalized + ' ';
            return spaced.includes(' dt2 ')
                || normalized.includes('diabete de type 2')
                || normalized.includes('diabete type 2')
                || normalized.includes('diabetique type 2')
                || normalized.includes('diabete non insulinodependant')
                || spaced.includes(' dnid ')
                || normalized.includes('metformine')
                || normalized.includes('hba1c')
                || normalized.includes('hemoglobine glyquee');
        })) addUnique(tags, 'DT2');
        if ((Number.isFinite(madrs) && madrs > 12)
            || anyAffirmativeSegment(raw, ['depression', 'syndrome depressif', 'antidepresseur'], normalized => textIndicatesDepressionTreatment(normalized))) {
            addUnique(tags, 'Syndrome dépressif');
        }
        if (extractBnpValuesFromText(raw).some(value => value > 1000)
            || anyAffirmativeSegment(raw, ['ic', 'insuffisance cardiaque', 'bnp', 'nt pro bnp'], normalized => {
                const spaced = ' ' + normalized + ' ';
                return spaced.includes(' ic ')
                    || normalized.includes('insuffisance cardiaque')
                    || normalized.includes('decompensation cardiaque')
                    || normalized.includes('oedeme pulmonaire cardiogenique')
                    || normalized.includes('oap cardiogenique');
            })) addUnique(tags, 'IC');
        if (anyAffirmativeSegment(raw, ['covid', 'sars cov 2'], normalized => normalized.includes('covid') || normalized.includes('sars cov 2') || normalized.includes('sars-cov-2') || normalized.includes('test antigenique') || normalized.includes('pcr covid'))) addUnique(tags, 'CoViD');
        if (anyAffirmativeSegment(raw, ['angine', 'amygdalite', 'streptocoque'], normalized => normalized.includes('angine') || normalized.includes('odynophagie') || normalized.includes('tdr angine') || normalized.includes('streptocoque') || normalized.includes('amygdalite'))) addUnique(tags, 'Angine');
        if (wedaFallTagIndicated(raw)) addUnique(tags, 'Chute');
        if (anyAffirmativeSegment(raw, ['asalee', 'azalee', 'genevieve'], normalized => normalized.includes('asalee') || normalized.includes('azalee') || normalized.includes('genevieve') || normalized.includes('infirmiere asalee') || normalized.includes('infirmiere azalee'))) addUnique(tags, 'ASALEE');
        if (anyAffirmativeSegment(raw, ['etp', 'education therapeutique'], normalized => normalized.includes('etp en cours') || normalized.includes('programme etp') || normalized.includes('education therapeutique en cours') || normalized.includes('atelier etp') || normalized.includes('participe a l etp'))) addUnique(tags, 'ETP');
        if (anyAffirmativeSegment(raw, ['ongle incarne', 'onychocryptose'], normalized => normalized.includes('ongle incarne') || normalized.includes('onychocryptose'))) addUnique(tags, 'Ongle incarné');
        if (anyAffirmativeSegment(raw, ['soins palliatifs', 'palliatif', 'fin de vie'], normalized => normalized.includes('soins palliatifs') || normalized.includes('palliatif') || normalized.includes('palliative') || normalized.includes('fin de vie') || normalized.includes('had palliative') || normalized.includes('sedation') || normalized.includes('morphine palliative'))) addUnique(tags, 'Soins palliatifs');

        return tags.filter(tag => WEDA_AVAILABLE_TAGS.includes(tag));
    }

    function createStructuredWedaReportFromText(text, context = {}) {
        resetStructuredWedaCorrections();
        const pressures = extractWedaBloodPressuresFromText(text);
        const report = {
            version: '0.5.14',
            timestamp: Date.now(),
            context,
            fields: {
                weight: extractWedaWeightFromText(text),
                height: extractWedaHeightFromText(text),
                temperature: extractWedaTemperatureFromText(text),
                officeBloodPressure: pressures.office ? pressures.office.text : null,
                systolicBloodPressure: pressures.office ? pressures.office.systolic : null,
                diastolicBloodPressure: pressures.office ? pressures.office.diastolic : null,
                homeBloodPressure: pressures.home ? pressures.home.text : null,
                tobacco: extractWedaTobaccoFromText(text),
                alcohol: extractWedaAlcoholFromText(text),
                feetExam: extractWedaFeetExamFromText(text),
                hemocult: extractWedaHemocultFromText(text),
                papSmear: extractWedaPapSmearFromText(text),
                mammography: extractWedaMammographyFromText(text),
                dentist: extractWedaDentistFromText(text),
                dtp: extractWedaDtpFromText(text),
                hpv: extractWedaHpvFromText(text),
                fundus: extractWedaFundusFromText(text),
                cardiologist: extractWedaCardiologistFromText(text),
                mms: extractWedaMmsFromText(text),
                madrs: extractWedaMadrsFromText(text)
            },
            tags: extractWedaTagsFromText(text),
            corrections: getStructuredWedaCorrections()
        };
        return report;
    }

    function getWedaElementBySelector(selector) {
        for (const doc of getAccessibleDocumentsDeep()) {
            try {
                const element = doc.querySelector(selector);
                if (element) return element;
            } catch (_) {}
        }
        return null;
    }

    async function waitForWedaElementBySelector(selector, name, timeoutMs = WEDA_STRUCTURED_FIELD_TIMEOUT_MS) {
        return waitFor(() => getWedaElementBySelector(selector), timeoutMs, 90);
    }

    function wedaFieldIsEmpty(field) {
        if (!field) return false;
        if ('value' in field) return String(field.value || '').trim() === '';
        return String(field.innerText || field.textContent || '').trim() === '';
    }

    function setWedaFieldValue(field, value) {
        if (!field) return false;
        const doc = field.ownerDocument || document;
        const win = ownerWindowOf(field) || doc.defaultView || window;
        const text = String(value || '');

        try { field.focus(); } catch (_) {}
        try {
            const prototype = Object.getPrototypeOf(field);
            const descriptor = Object.getOwnPropertyDescriptor(prototype, 'value');
            if (descriptor && typeof descriptor.set === 'function') descriptor.set.call(field, text);
            else field.value = text;
        } catch (_) {
            try { field.value = text; } catch (_error) { return false; }
        }

        try { field.setAttribute('value', text); } catch (_) {}

        ['input', 'change', 'keyup', 'blur'].forEach(type => {
            try {
                let event;
                if (type === 'input' && typeof win.InputEvent === 'function') {
                    event = new win.InputEvent(type, {
                        bubbles: true,
                        cancelable: true,
                        inputType: 'insertText',
                        data: text
                    });
                } else {
                    event = new win.Event(type, { bubbles: true, cancelable: true });
                }
                field.dispatchEvent(event);
            } catch (_) {}
        });

        return true;
    }

    async function fillSimpleWedaStructuredField(selector, name, value) {
        if (!value) return { name, selector, value: null, status: 'no_value' };
        const field = await waitForWedaElementBySelector(selector, name, WEDA_STRUCTURED_FIELD_TIMEOUT_MS);
        if (!field) return { name, selector, value, status: 'missing_field' };
        if (!wedaFieldIsEmpty(field)) {
            return {
                name,
                selector,
                value,
                status: 'already_filled',
                existingValue: 'value' in field ? String(field.value || '') : String(field.innerText || field.textContent || '')
            };
        }
        const ok = setWedaFieldValue(field, value);
        return { name, selector, value, status: ok ? 'filled' : 'failed', target: describeElement(field) };
    }

    async function fillWedaBloodPressureFromReport(fields) {
        const data = fields || {};
        const results = [];

        if (data.systolicBloodPressure || data.diastolicBloodPressure) {
            const [sysField, diaField] = await Promise.all([
                waitForWedaElementBySelector(SELECTOR_WEDA_BP_SYS, 'tension systolique WEDA', WEDA_STRUCTURED_FIELD_TIMEOUT_MS),
                waitForWedaElementBySelector(SELECTOR_WEDA_BP_DIA, 'tension diastolique WEDA', WEDA_STRUCTURED_FIELD_TIMEOUT_MS)
            ]);

            if (!sysField || !diaField) {
                results.push({
                    name: 'tension cabinet',
                    value: data.officeBloodPressure || '',
                    status: 'missing_field',
                    missing: {
                        systolic: !sysField,
                        diastolic: !diaField
                    }
                });
            } else {
                let filledAny = false;
                if (data.systolicBloodPressure && wedaFieldIsEmpty(sysField)) {
                    filledAny = setWedaFieldValue(sysField, data.systolicBloodPressure) || filledAny;
                }
                if (data.diastolicBloodPressure && wedaFieldIsEmpty(diaField)) {
                    filledAny = setWedaFieldValue(diaField, data.diastolicBloodPressure) || filledAny;
                }
                results.push({
                    name: 'tension cabinet',
                    value: data.officeBloodPressure || '',
                    status: filledAny ? 'filled' : 'already_filled',
                    target: {
                        systolic: describeElement(sysField),
                        diastolic: describeElement(diaField)
                    }
                });
            }
        }

        if (data.homeBloodPressure) {
            results.push(await fillSimpleWedaStructuredField(
                SELECTOR_WEDA_BP_HOME,
                'automesure tensionnelle',
                data.homeBloodPressure
            ));
        }

        return results;
    }

    async function fillStructuredWedaFieldsFromReport(report) {
        const fields = report && report.fields ? report.fields : {};
        const tasks = [
            fillSimpleWedaStructuredField(SELECTOR_WEDA_WEIGHT, 'poids', fields.weight),
            fillSimpleWedaStructuredField(SELECTOR_WEDA_HEIGHT, 'taille', fields.height),
            fillSimpleWedaStructuredField(SELECTOR_WEDA_TEMPERATURE, 'température', fields.temperature),
            fillWedaBloodPressureFromReport(fields),
            fillSimpleWedaStructuredField(SELECTOR_WEDA_TOBACCO, 'tabac', fields.tobacco),
            fillSimpleWedaStructuredField(SELECTOR_WEDA_ALCOHOL, 'alcool', fields.alcohol),
            fillSimpleWedaStructuredField(SELECTOR_WEDA_FEET_EXAM, 'examen des pieds / podologue', fields.feetExam),
            fillSimpleWedaStructuredField(SELECTOR_WEDA_HEMOCULT, 'hémocult', fields.hemocult),
            fillSimpleWedaStructuredField(SELECTOR_WEDA_PAP_SMEAR, 'frottis', fields.papSmear),
            fillSimpleWedaStructuredField(SELECTOR_WEDA_MAMMOGRAPHY, 'mammographie', fields.mammography),
            fillSimpleWedaStructuredField(SELECTOR_WEDA_DENTIST, 'dentiste', fields.dentist),
            fillSimpleWedaStructuredField(SELECTOR_WEDA_DTP, 'DTP', fields.dtp),
            fillSimpleWedaStructuredField(SELECTOR_WEDA_HPV, 'papillomavirus / Gardasil', fields.hpv),
            fillSimpleWedaStructuredField(SELECTOR_WEDA_FUNDUS, 'fond d’œil / ophtalmo', fields.fundus),
            fillSimpleWedaStructuredField(SELECTOR_WEDA_CARDIOLOGIST, 'cardiologue', fields.cardiologist),
            fillSimpleWedaStructuredField(SELECTOR_WEDA_MMS, 'MMS', fields.mms),
            fillSimpleWedaStructuredField(SELECTOR_WEDA_MADRS, 'MADRS', fields.madrs)
        ];

        const settled = await Promise.allSettled(tasks);
        const results = [];
        settled.forEach(result => {
            if (result.status === 'fulfilled') {
                if (Array.isArray(result.value)) results.push(...result.value);
                else results.push(result.value);
            } else {
                results.push({
                    name: 'structured_field_task',
                    status: 'error',
                    error: result.reason && result.reason.message ? result.reason.message : String(result.reason)
                });
            }
        });

        return {
            results,
            filled: results.filter(result => result && result.status === 'filled'),
            alreadyFilled: results.filter(result => result && result.status === 'already_filled'),
            missing: results.filter(result => result && result.status === 'missing_field'),
            detected: results.filter(result => result && result.status !== 'no_value')
        };
    }

    function normalizeWedaTagName(name) {
        return normalizeExtractionText(name).trim();
    }

    function findWedaTagPanelButton() {
        return getWedaElementBySelector(SELECTOR_WEDA_TAG_PANEL_BUTTON);
    }

    function findWedaTagGrid() {
        return getWedaElementBySelector(SELECTOR_WEDA_TAG_GRID);
    }

    function wedaTagGridIsVisible(grid) {
        if (!grid) return false;
        try {
            const win = ownerWindowOf(grid);
            const style = win.getComputedStyle(grid);
            const rect = grid.getBoundingClientRect();
            return rect.width > 0 && rect.height > 0 && style.display !== 'none' && style.visibility !== 'hidden';
        } catch (_) {
            return true;
        }
    }

    async function waitForWedaTagGrid(timeoutMs = WEDA_TAG_PANEL_TIMEOUT_MS) {
        return waitFor(() => {
            const grid = findWedaTagGrid();
            return grid && wedaTagGridIsVisible(grid) ? grid : null;
        }, timeoutMs, 90);
    }

    async function openWedaTagGrid() {
        const visibleGrid = findWedaTagGrid();
        if (visibleGrid && wedaTagGridIsVisible(visibleGrid)) return visibleGrid;

        const button = await waitFor(() => findWedaTagPanelButton(), WEDA_TAG_PANEL_TIMEOUT_MS, 90);
        if (!button) return null;
        clickElementForWeda(button);
        await sleep(120);
        return waitForWedaTagGrid(WEDA_TAG_PANEL_TIMEOUT_MS);
    }

    function findWedaTagRowInGrid(grid, tag) {
        if (!grid) return null;
        const target = normalizeWedaTagName(tag);
        const rows = Array.from(grid.querySelectorAll('tr'));
        return rows.find(row => {
            const titleLink = row.querySelector('a[id*="LinkButtonGlossaireTitre"]');
            const text = normalizeWedaTagName(titleLink ? (titleLink.textContent || titleLink.innerText || '') : '');
            return text === target;
        }) || null;
    }

    function findWedaTagApplyLink(row) {
        if (!row) return null;
        return row.querySelector('a[id*="LinkButtonAffecterEtiquette"]')
            || Array.from(row.querySelectorAll('a, button, input')).find(element => {
                const text = normalizeWedaTagName([
                    element.getAttribute ? element.getAttribute('title') || '' : '',
                    element.getAttribute ? element.getAttribute('value') || element.value || '' : '',
                    element.innerText || element.textContent || '',
                    element.id || ''
                ].join(' '));
                return text.includes('affecter') || text.includes('ajouter') || text.includes('plus');
            })
            || null;
    }

    async function addWedaTagByName(tag, existingGrid = null) {
        const grid = existingGrid && wedaTagGridIsVisible(existingGrid)
            ? existingGrid
            : await openWedaTagGrid();
        if (!grid) return { tag, added: false, reason: 'tag_grid_missing' };
        const row = findWedaTagRowInGrid(grid, tag);
        if (!row) return { tag, added: false, reason: 'tag_row_missing' };
        const link = findWedaTagApplyLink(row);
        if (!link) return { tag, added: false, reason: 'tag_apply_link_missing', row: describeElement(row) };
        clickElementForWeda(link);
        await sleep(WEDA_TAG_APPLY_DELAY_MS);
        return { tag, added: true, reason: 'clicked', target: describeElement(link) };
    }

    async function applyWedaTagsFromReport(report) {
        const tags = uniqueArray(report && Array.isArray(report.tags) ? report.tags : [])
            .filter(tag => WEDA_AVAILABLE_TAGS.includes(tag));
        const results = [];
        if (!tags.length) {
            return { tags, results, added: [], failed: [] };
        }

        let grid = await openWedaTagGrid();
        if (!grid) {
            tags.forEach(tag => results.push({ tag, added: false, reason: 'tag_grid_missing' }));
            return { tags, results, added: [], failed: results.slice() };
        }

        for (const tag of tags) {
            try {
                const currentGrid = findWedaTagGrid();
                grid = currentGrid && wedaTagGridIsVisible(currentGrid) ? currentGrid : await openWedaTagGrid();
                if (!grid) {
                    results.push({ tag, added: false, reason: 'tag_grid_missing' });
                    continue;
                }
                results.push(await addWedaTagByName(tag, grid));
            } catch (error) {
                results.push({
                    tag,
                    added: false,
                    reason: 'error',
                    error: error && error.message ? error.message : String(error)
                });
            }
        }
        return {
            tags,
            results,
            added: results.filter(result => result && result.added),
            failed: results.filter(result => result && !result.added)
        };
    }

    async function runStructuredWedaAutomationFromText(text, options = {}) {
        const source = options && options.source ? String(options.source) : '';
        const report = createStructuredWedaReportFromText(text, { source });
        const fields = await fillStructuredWedaFieldsFromReport(report);
        const tags = await applyWedaTagsFromReport(report);
        const filledNames = fields.filled.map(result => result.name).filter(Boolean);
        const addedTags = tags.added.map(result => result.tag).filter(Boolean);

        logEvent('info', 'structured_weda_automation_done', 'Complétion structurée WEDA terminée.', {
            source,
            detectedFields: fields.detected.map(result => ({
                name: result.name,
                value: result.value,
                status: result.status
            })),
            filledFields: filledNames,
            missingFields: fields.missing.map(result => result.name),
            detectedTags: tags.tags,
            addedTags,
            failedTags: tags.failed,
            corrections: report.corrections
        });

        if (!(options && options.silent) && (filledNames.length || addedTags.length)) {
            showBadge('Connecteur WEDA : champs structurés/tags complétés.');
        }

        return { report, fields, tags };
    }

    function findWedaInterrogatoireEditableTarget() {
        const labelSelectors = [
            'select',
            'option',
            'input',
            'button',
            '[role="combobox"]',
            '[title]',
            '[aria-label]',
            'label',
            'td',
            'th',
            'span',
            'div'
        ].join(',');

        const docs = getAccessibleDocumentsDeep();
        for (let docIndex = 0; docIndex < docs.length; docIndex += 1) {
            const doc = docs[docIndex];
            try {
                const labels = Array.from(doc.querySelectorAll(labelSelectors)).filter(el => {
                    const text = getElementLabelSearchText(el);
                    return text && text.length <= 800 && textLooksLikeInterrogatoire(text) && !textLooksLikeExcludedClinicalExam(text);
                });

                for (const label of labels) {
                    const target = findInterrogatoireTargetFromLabelElement(label, docIndex);
                    if (target && targetIsStillUsable(target.element)) return target;
                }
            } catch (_) {}
        }

        const candidates = [];
        const seen = new Set();
        docs.forEach((doc, docIndex) => {
            try {
                const body = doc.body;
                if (body && !seen.has(body) && contentEditableLooksLikeWedaConsultationField(body) && isEditableElement(body)) {
                    seen.add(body);
                    const score = scoreEditableForInterrogatoire(body);
                    if (score.hasInterrogatoire && score.score > 0) {
                        candidates.push({ element: body, source: 'interrogatoire_context_body', docIndex, ...score });
                    }
                }
            } catch (_) {}

            try {
                Array.from(doc.querySelectorAll('[contenteditable="true"], [contenteditable=""]')).forEach(el => {
                    if (seen.has(el) || !isEditableElement(el)) return;
                    seen.add(el);
                    const score = scoreEditableForInterrogatoire(el);
                    if (score.hasInterrogatoire && score.score > 0) {
                        candidates.push({ element: el, source: 'interrogatoire_context_contenteditable', docIndex, ...score });
                    }
                });
            } catch (_) {}
        });

        candidates.sort((a, b) => b.score - a.score || a.docIndex - b.docIndex);
        if (candidates.length) {
            return {
                element: candidates[0].element,
                reason: 'weda_interrogatoire_context',
                target: describeElement(candidates[0].element),
                candidatesCount: candidates.length,
                candidates: candidates.slice(0, 6).map(candidate => ({
                    source: candidate.source,
                    score: candidate.score,
                    label: candidate.label,
                    target: describeElement(candidate.element)
                }))
            };
        }

        return {
            element: null,
            reason: 'no_weda_interrogatoire_field',
            candidatesCount: 0,
            candidates: []
        };
    }

    function findWedaConsultationEditableTarget(options = {}) {
        const preferInterrogatoire = !!(options && options.preferInterrogatoire);
        const requireInterrogatoire = !!(options && options.requireInterrogatoire);
        if (preferInterrogatoire || requireInterrogatoire) {
            const interrogatoireTarget = findWedaInterrogatoireEditableTarget();
            if (targetIsStillUsable(interrogatoireTarget.element) || requireInterrogatoire) {
                return interrogatoireTarget;
            }
        }

        const candidates = [];
        const seen = new Set();

        function addCandidate(el, docIndex, source) {
            if (!el || seen.has(el)) return;
            if (!contentEditableLooksLikeWedaConsultationField(el)) return;
            if (!isEditableElement(el)) return;
            seen.add(el);
            const rect = (() => {
                try {
                    const r = el.getBoundingClientRect();
                    return { width: Number(r.width || 0), height: Number(r.height || 0) };
                } catch (_) {
                    return { width: 0, height: 0 };
                }
            })();
            const textLength = normalizeSpaces(el.innerText || el.textContent || '').length;
            let score = 0;
            if (isWedaConsultationPage()) score += 1000;
            if (String(el.tagName || '').toLowerCase() === 'body') score += 120;
            if (source === 'body_contenteditable') score += 80;
            if (textLength === 0) score += 30;
            score += Math.min(120, Math.round((rect.width * rect.height) / 5000));
            score -= docIndex * 3;

            candidates.push({
                element: el,
                source,
                score,
                textLength,
                target: describeElement(el)
            });
        }

        const docs = getAccessibleDocumentsDeep();
        docs.forEach((doc, docIndex) => {
            try {
                const body = doc.body;
                if (body && contentEditableLooksLikeWedaConsultationField(body)) {
                    addCandidate(body, docIndex, 'body_contenteditable');
                }
            } catch (_) {}

            try {
                Array.from(doc.querySelectorAll('[contenteditable="true"], [contenteditable=""]')).forEach(el => {
                    addCandidate(el, docIndex, 'contenteditable');
                });
            } catch (_) {}
        });

        candidates.sort((a, b) => b.score - a.score);

        if (candidates.length) {
            return {
                element: candidates[0].element,
                reason: 'weda_consultation_contenteditable',
                target: candidates[0].target,
                candidatesCount: candidates.length,
                candidates: candidates.slice(0, 6).map(candidate => ({
                    source: candidate.source,
                    score: candidate.score,
                    textLength: candidate.textLength,
                    target: candidate.target
                }))
            };
        }

        return {
            element: null,
            reason: 'no_weda_consultation_contenteditable',
            candidatesCount: 0,
            candidates: []
        };
    }

    function getEditableTarget(options = {}) {
        const consultationTarget = isWedaConsultationPage()
            ? findWedaConsultationEditableTarget(options)
            : { element: null, reason: 'not_weda_consultation_page', candidatesCount: 0, candidates: [] };
        if (targetIsStillUsable(consultationTarget.element)) {
            return consultationTarget;
        }

        if (options && options.requireInterrogatoire) {
            return {
                element: null,
                reason: consultationTarget.reason || 'required_interrogatoire_not_found',
                target: null,
                candidatesCount: consultationTarget.candidatesCount || 0,
                candidates: consultationTarget.candidates || []
            };
        }

        const active = editableFromTarget(getDeepActiveElement());
        if (targetIsStillUsable(active)) {
            return {
                element: active,
                reason: 'deep_active_element',
                target: describeElement(active)
            };
        }

        if (
            lastEditableTarget &&
            Date.now() - Number(lastEditableTarget.seenAt || 0) <= LAST_TARGET_MAX_AGE_MS &&
            targetIsStillUsable(lastEditableTarget.element)
        ) {
            return {
                element: lastEditableTarget.element,
                reason: 'remembered_editable_target',
                target: describeElement(lastEditableTarget.element),
                rememberedReason: lastEditableTarget.reason,
                rememberedAgeMs: Date.now() - Number(lastEditableTarget.seenAt || 0)
            };
        }

        const fallback = findSingleVisibleEditableCandidate();
        return {
            element: fallback.element,
            reason: fallback.reason,
            target: describeElement(fallback.element),
            candidatesCount: fallback.candidatesCount
        };
    }

    function setNativeValue(el, value) {
        const win = ownerWindowOf(el);
        const proto = Object.getPrototypeOf(el);
        const descriptor = proto ? Object.getOwnPropertyDescriptor(proto, 'value') : null;
        if (descriptor && descriptor.set) descriptor.set.call(el, value);
        else el.value = value;
        el.dispatchEvent(new win.Event('input', { bubbles: true }));
        el.dispatchEvent(new win.Event('change', { bubbles: true }));
    }

    function editableTextIsEmpty(el) {
        return normalizeSpaces(el && (el.innerText || el.textContent || '')).length === 0;
    }

    function clearEmptyEditableHtml(el) {
        if (editableTextIsEmpty(el)) {
            try { el.innerHTML = ''; } catch (_) {}
        }
    }

    function escapeHtml(text) {
        return String(text || '')
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }

    function markdownInlineToSafeHtml(text) {
        const preservedTags = [];

        function preserveTag(html) {
            const index = preservedTags.length;
            preservedTags.push(html);
            return '@@GWATAG' + index + '@@';
        }

        let source = String(text || '').replace(/<\/?\s*(strong|b|em|i|u|s|strike|del|br)\b[^>]*>/gi, tag => {
            const match = tag.match(/^<\/?\s*([a-z0-9]+)/i);
            if (!match) return escapeHtml(tag);
            const name = String(match[1] || '').toLowerCase();
            if (name === 'br') return preserveTag('<br>');

            const closing = /^<\//.test(tag);
            const normalized = name === 'strike' || name === 'del' ? 's' : name;
            return preserveTag(closing ? '</' + normalized + '>' : '<' + normalized + '>');
        });

        source = escapeHtml(source);
        source = source
            .replace(/\*\*\*([^*]+)\*\*\*/g, '<strong><em>$1</em></strong>')
            .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
            .replace(/__([^_]+)__/g, '<u>$1</u>')
            .replace(/~~([^~]+)~~/g, '<s>$1</s>')
            .replace(/\*([^*]+)\*/g, '<em>$1</em>')
            .replace(/_([^_]+)_/g, '<em>$1</em>');

        const placeholderPattern = /@@GWATAG(\d+)@@/g;
        return source.replace(placeholderPattern, (_, index) => preservedTags[Number(index)] || '');
    }

    const WEDA_SECTION_HEADING_LABELS = new Set([
        'allergies',
        'antecedents',
        'atcd',
        'avis',
        'biologie',
        'cat',
        'compte rendu',
        'conclusion',
        'conduite a tenir',
        'constantes',
        'contexte',
        'courrier',
        'diagnostic',
        'diagnostics',
        'documents',
        'evolution',
        'examen',
        'examen clinique',
        'histoire',
        'imagerie',
        'interrogatoire',
        'motif',
        'ordonnance',
        'plan',
        'prise en charge',
        'resume',
        'resultats',
        'suivi',
        'surveillance',
        'synthese',
        'traitement',
        'traitements'
    ]);

    function markdownInlineToPlainText(text) {
        return String(text || '')
            .replace(/<\/?\s*br\s*\/?\s*>/gi, '\n')
            .replace(/<[^>]+>/g, '')
            .replace(/!\[([^\]]*)\]\([^)]+\)/g, '$1')
            .replace(/\[([^\]]+)\]\([^)]+\)/g, '$1')
            .replace(/`([^`]*)`/g, '$1')
            .replace(/\*\*\*([^*]+)\*\*\*/g, '$1')
            .replace(/\*\*([^*]+)\*\*/g, '$1')
            .replace(/__([^_]+)__/g, '$1')
            .replace(/\+\+([^+]+)\+\+/g, '$1')
            .replace(/~~([^~]+)~~/g, '$1')
            .replace(/\*([^*]+)\*/g, '$1')
            .replace(/_([^_]+)_/g, '$1')
            .trim();
    }

    function normalizeSectionHeadingLabel(text) {
        return markdownInlineToPlainText(text)
            .normalize('NFD')
            .replace(/[\u0300-\u036f]/g, '')
            .toLowerCase()
            .replace(/[^a-z0-9]+/g, ' ')
            .replace(/\s+/g, ' ')
            .trim();
    }

    function isSectionHeadingLabel(text) {
        return WEDA_SECTION_HEADING_LABELS.has(normalizeSectionHeadingLabel(text));
    }

    function splitWedaSectionHeadingLine(line) {
        const stripped = String(line || '').trim();
        if (!stripped) return null;

        const colon = stripped.match(/^(.{2,60}?)(\s*:\s*)(.*)$/);
        if (colon && isSectionHeadingLabel(colon[1])) {
            return {
                label: colon[1].trim() + colon[2].replace(/\s+$/g, ''),
                suffix: colon[3].trim()
            };
        }

        if (stripped.length <= 60 && isSectionHeadingLabel(stripped)) {
            return { label: stripped, suffix: '' };
        }

        return null;
    }

    function markdownToWedaSafeHtml(text) {
        return String(text || '')
            .replace(/\r\n?/g, '\n')
            .split('\n')
            .map(line => {
                const heading = line.match(/^\s{0,3}#{1,6}\s+(.+)$/);
                if (heading) return '<strong><u>' + markdownInlineToSafeHtml(heading[1]) + '</u></strong>';
                const sectionHeading = splitWedaSectionHeadingLine(line);
                if (sectionHeading) {
                    const label = '<strong><u>' + markdownInlineToSafeHtml(sectionHeading.label) + '</u></strong>';
                    return sectionHeading.suffix ? label + ' ' + markdownInlineToSafeHtml(sectionHeading.suffix) : label;
                }
                return markdownInlineToSafeHtml(line);
            })
            .join('<br>');
    }

    function sanitizeWedaSafeHtmlFragment(html, doc = document) {
        const allowedTags = {
            strong: 'strong',
            b: 'strong',
            em: 'em',
            i: 'em',
            u: 'u',
            s: 's',
            strike: 's',
            del: 's',
            br: 'br'
        };
        const template = doc.createElement('template');
        template.innerHTML = String(html || '');

        function cleanChildren(node) {
            const fragment = doc.createDocumentFragment();
            Array.from(node.childNodes || []).forEach(child => {
                if (child.nodeType === 3) {
                    fragment.appendChild(doc.createTextNode(child.textContent || ''));
                    return;
                }

                if (child.nodeType !== 1) {
                    return;
                }

                const rawName = String(child.tagName || '').toLowerCase();
                const tagName = allowedTags[rawName] || '';
                if (!tagName) {
                    fragment.appendChild(cleanChildren(child));
                    return;
                }

                if (tagName === 'br') {
                    fragment.appendChild(doc.createElement('br'));
                    return;
                }

                const safeElement = doc.createElement(tagName);
                safeElement.appendChild(cleanChildren(child));
                fragment.appendChild(safeElement);
            });
            return fragment;
        }

        const output = doc.createElement('div');
        output.appendChild(cleanChildren(template.content));
        return output.innerHTML;
    }

    function htmlFragmentToPlainText(html, doc = document) {
        const container = doc.createElement('div');
        container.innerHTML = sanitizeWedaSafeHtmlFragment(html, doc);
        const parts = [];

        function walk(node) {
            if (!node) return;
            if (node.nodeType === 3) {
                parts.push(node.textContent || '');
                return;
            }
            if (node.nodeType !== 1) return;
            if (String(node.tagName || '').toLowerCase() === 'br') {
                parts.push('\n');
                return;
            }
            Array.from(node.childNodes || []).forEach(walk);
        }

        Array.from(container.childNodes || []).forEach(walk);
        return parts.join('').replace(/\n{3,}/g, '\n\n').trim();
    }

    function placeCaretAtEnd(el) {
        const doc = ownerDocumentOf(el);
        const win = ownerWindowOf(el);
        try {
            const range = doc.createRange();
            range.selectNodeContents(el);
            range.collapse(false);
            const selection = win.getSelection ? win.getSelection() : null;
            if (selection) {
                selection.removeAllRanges();
                selection.addRange(range);
            }
            return true;
        } catch (_) {
            return false;
        }
    }

    function editorVisibleText(el) {
        return normalizeSpaces(el && (el.innerText || el.textContent || ''));
    }

    function editorLooksChangedWithExpectedText(el, beforeText, expectedText) {
        const before = normalizeSpaces(beforeText);
        const after = editorVisibleText(el);
        const expected = normalizeSpaces(expectedText);
        if (after === before) return false;
        if (after.length > before.length) return true;
        if (!expected) return true;
        const head = expected.slice(0, Math.min(180, expected.length));
        const tail = expected.slice(Math.max(0, expected.length - 180));
        return after.includes(head) || after.includes(tail);
    }

    function insertHtmlByCommand(el, html, plainText, beforeText) {
        try {
            const doc = ownerDocumentOf(el);
            placeCaretAtEnd(el);
            doc.execCommand('insertHTML', false, html);
            return editorLooksChangedWithExpectedText(el, beforeText, plainText);
        } catch (_) {
            return false;
        }
    }

    function pasteRichHtmlIntoContentEditable(el, html, plainText, beforeText) {
        try {
            const win = ownerWindowOf(el);
            if (typeof win.DataTransfer !== 'function' || typeof win.ClipboardEvent !== 'function') return false;

            const dataTransfer = new win.DataTransfer();
            dataTransfer.setData('text/html', html);
            dataTransfer.setData('text/plain', plainText);
            placeCaretAtEnd(el);

            const event = new win.ClipboardEvent('paste', {
                bubbles: true,
                cancelable: true,
                clipboardData: dataTransfer
            });

            try {
                if (!event.clipboardData) {
                    Object.defineProperty(event, 'clipboardData', {
                        value: dataTransfer
                    });
                }
            } catch (_) {}

            el.dispatchEvent(event);
            return editorLooksChangedWithExpectedText(el, beforeText, plainText);
        } catch (_) {
            return false;
        }
    }

    function appendFormattedHtmlDirectly(el, html) {
        const doc = ownerDocumentOf(el);
        const template = doc.createElement('template');
        template.innerHTML = html;
        el.appendChild(template.content.cloneNode(true));
        return true;
    }

    function appendFormattedTextToContentEditable(el, text, html = '') {
        const doc = ownerDocumentOf(el);
        clearEmptyEditableHtml(el);
        const alreadyHasText = !editableTextIsEmpty(el);
        const safeHtml = html ? sanitizeWedaSafeHtmlFragment(html, doc) : markdownToWedaSafeHtml(text);
        const htmlToInsert = (alreadyHasText ? '<br><br>' : '') + safeHtml;
        const plainText = (alreadyHasText ? '\n\n' : '') + (html ? htmlFragmentToPlainText(safeHtml, doc) : markdownInlineToPlainText(text));
        const beforeText = editorVisibleText(el);

        if (insertHtmlByCommand(el, htmlToInsert, plainText, beforeText)) {
            logEvent('info', 'rich_html_inserted_command', 'Résultat HTML inséré par commande WEDA.', {
                html_length: safeHtml.length,
                text_length: plainText.length
            });
            return;
        }

        if (pasteRichHtmlIntoContentEditable(el, htmlToInsert, plainText, beforeText)) {
            logEvent('info', 'rich_html_inserted_paste', 'Résultat HTML inséré par événement paste WEDA.', {
                html_length: safeHtml.length,
                text_length: plainText.length
            });
            return;
        }

        appendFormattedHtmlDirectly(el, htmlToInsert);
        logEvent('warning', 'rich_html_inserted_direct_fallback', 'Résultat HTML ajouté directement après refus des chemins collage.', {
            html_length: safeHtml.length,
            text_length: plainText.length
        });
    }

    function appendPlainTextToContentEditable(el, text) {
        const doc = ownerDocumentOf(el);
        clearEmptyEditableHtml(el);
        const alreadyHasText = !editableTextIsEmpty(el);
        if (alreadyHasText) {
            el.appendChild(doc.createElement('br'));
            el.appendChild(doc.createElement('br'));
        }

        const lines = String(text || '').replace(/\r\n?/g, '\n').split('\n');
        lines.forEach((line, index) => {
            el.appendChild(doc.createTextNode(line));
            if (index < lines.length - 1) el.appendChild(doc.createElement('br'));
        });
    }

    function dispatchEditableCommitEvents(el, text) {
        const win = ownerWindowOf(el);
        const InputEventCtor = win.InputEvent || window.InputEvent;
        try {
            if (InputEventCtor) {
                el.dispatchEvent(new InputEventCtor('beforeinput', {
                    bubbles: true,
                    cancelable: true,
                    inputType: 'insertFromPaste',
                    data: text
                }));
            }
        } catch (_) {}
        try {
            if (InputEventCtor) {
                el.dispatchEvent(new InputEventCtor('input', {
                    bubbles: true,
                    inputType: 'insertFromPaste',
                    data: text
                }));
            } else {
                el.dispatchEvent(new win.Event('input', { bubbles: true, cancelable: true }));
            }
        } catch (_) {
            try { el.dispatchEvent(new win.Event('input', { bubbles: true, cancelable: true })); } catch (_) {}
        }
        ['change', 'keyup', 'blur'].forEach(type => {
            try { el.dispatchEvent(new win.Event(type, { bubbles: true, cancelable: true })); } catch (_) {}
        });
    }

    function insertIntoTarget(targetInfo, text, html = '') {
        const target = targetInfo && targetInfo.element ? targetInfo.element : targetInfo;
        if (!target) return false;

        const win = ownerWindowOf(target);
        const doc = ownerDocumentOf(target);

        try { target.focus(); } catch (_) {}

        const hasContenteditable = !!(target.hasAttribute && target.hasAttribute('contenteditable'));
        const contenteditable = hasContenteditable ? String(target.getAttribute('contenteditable') || '').toLowerCase() : '';
        if (target.isContentEditable || contenteditable === 'true' || (hasContenteditable && contenteditable === '')) {
            try {
                appendFormattedTextToContentEditable(target, text, html);
            } catch (error) {
                logEvent('warning', 'formatted_import_fallback', 'Import HTML formaté impossible, fallback texte brut.', {
                    error: error && error.message ? error.message : String(error)
                });
                try {
                    appendPlainTextToContentEditable(target, text);
                } catch (_) {
                    target.textContent = text;
                }
            }
            dispatchEditableCommitEvents(target, text);
            try { doc.dispatchEvent(new win.Event('selectionchange', { bubbles: true })); } catch (_) {}
            return true;
        }

        if ('value' in target) {
            setNativeValue(target, text);
            return true;
        }

        return false;
    }

    function copyImportResultToClipboard(text, html = '') {
        if (html) {
            try {
                GM_setClipboard(sanitizeWedaSafeHtmlFragment(html), 'html');
                return 'html';
            } catch (error) {
                logEvent('warning', 'html_clipboard_fallback', 'Copie HTML refusée, fallback texte brut.', {
                    error: error && error.message ? error.message : String(error)
                });
            }
        }

        GM_setClipboard(text, 'text');
        return 'text';
    }

    function installEditableTracker() {
        getAccessibleDocumentsDeep().forEach(doc => {
            if (!doc || doc.__GEMMA_WEDA_ASSISTANT_EDITABLE_TRACKER__) return;
            doc.__GEMMA_WEDA_ASSISTANT_EDITABLE_TRACKER__ = true;

            ['focusin', 'mousedown', 'mouseup', 'keyup', 'input'].forEach(type => {
                doc.addEventListener(type, event => {
                    rememberEditableTarget(event.target, type);
                }, true);
            });

            doc.addEventListener('selectionchange', () => {
                try {
                    rememberEditableTarget(doc.activeElement, 'selectionchange');
                } catch (_) {}
            }, true);
        });
    }

    async function importLatestResult(options = {}) {
        const source = options && options.source ? String(options.source) : 'manual';
        const currentPatientId = extractPatDk(location.href);
        logEvent('info', 'import_start', 'Import WEDA demandé.', {
            currentPatientId,
            rememberedTarget: lastEditableTarget ? lastEditableTarget.description : null,
            source
        });
        const response = await requestJson(
            'GET',
            '/weda/latest-result?patient_id=' + encodeURIComponent(currentPatientId)
        );
        const request = response.request;

        if (!request || !request.result_text) {
            logEvent('warning', 'import_no_result', 'Aucun résultat préparé dans l’application.', {
                currentPatientId,
                response
            });
            showBadge('Aucun résultat préparé dans l’assistant local.', true);
            return { inserted: false, reason: 'no_result', request: null };
        }

        const resultHtml = String(request.result_html || request.resultHtml || '');
        if (request.patient_id && currentPatientId && !samePatient(request.patient_id, currentPatientId)) {
            logEvent('error', 'import_patient_mismatch', 'Import bloqué : patient différent.', {
                request_id: request.id,
                expected_patient_id: request.patient_id,
                current_patient_id: currentPatientId
            });
            await requestJson('POST', '/weda/import-status', {
                status: 'blocked_patient_mismatch',
                request_id: request.id,
                expected_patient_id: request.patient_id,
                current_patient_id: currentPatientId,
                page_url: location.href
            });
            showBadge(
                'Import bloqué : le patient WEDA actif ne correspond pas au résultat préparé.\n' +
                'Attendu : ' + request.patient_id + '\n' +
                'Actuel : ' + currentPatientId,
                true
            );
            return { inserted: false, reason: 'patient_mismatch', request };
        }

        const connectorImportKey = getConnectorImportKey(request, currentPatientId, source);
        const alreadyImported = getConnectorImportedRequest(connectorImportKey);
        if (alreadyImported) {
            logEvent('info', 'connector_duplicate_import_skipped', 'Import connecteur déjà effectué pour ce résultat.', {
                request_id: request.id,
                connectorImportKey,
                alreadyImported
            });
            return {
                inserted: true,
                reason: 'duplicate_import_already_done',
                duplicateSkipped: true,
                request,
                targetInfo: null,
                medicoLegalResult: null
            };
        }

        const importLock = acquireConnectorImportLock(connectorImportKey);
        if (connectorImportKey && !importLock) {
            logEvent('warning', 'connector_duplicate_import_in_progress', 'Import connecteur déjà en cours pour ce résultat.', {
                request_id: request.id,
                connectorImportKey
            });
            return {
                inserted: false,
                reason: 'duplicate_import_in_progress',
                duplicateSkipped: true,
                request,
                targetInfo: null,
                medicoLegalResult: null
            };
        }

        try {
            const requireInterrogatoire = source === 'connector_auto';
            const targetInfo = getEditableTarget({
                preferInterrogatoire: requireInterrogatoire,
                requireInterrogatoire
            });
            logEvent('info', 'import_target_resolved', 'Résolution du champ cible WEDA.', {
                request_id: request.id,
                target: targetInfo.target,
                reason: targetInfo.reason,
                rememberedReason: targetInfo.rememberedReason || '',
                rememberedAgeMs: targetInfo.rememberedAgeMs || 0,
                candidatesCount: targetInfo.candidatesCount || 0,
                candidates: targetInfo.candidates || []
            });

            const inserted = insertIntoTarget(targetInfo, request.result_text, resultHtml);
            const medicoLegalResult = inserted
                ? addMedicoLegalPhraseToClinicalExamField(targetInfo.element, { source, silent: !!(options && options.silent) })
                : null;
            let structuredWedaResult = null;
            if (inserted && source === 'connector_auto') {
                try {
                    structuredWedaResult = await runStructuredWedaAutomationFromText(request.result_text, {
                        source,
                        silent: !!(options && options.silent)
                    });
                } catch (error) {
                    structuredWedaResult = {
                        error: error && error.message ? error.message : String(error)
                    };
                    logEvent('error', 'structured_weda_automation_error', 'Erreur complétion structurée WEDA.', {
                        request_id: request.id,
                        source,
                        error: structuredWedaResult.error,
                        stack: error && error.stack ? String(error.stack).slice(0, 1200) : ''
                    });
                }
            }
            if (inserted) {
                markConnectorRequestImported(connectorImportKey, {
                    requestId: request.id || '',
                    patientId: currentPatientId || '',
                    pageUrl: location.href,
                    source
                });
            } else {
                copyImportResultToClipboard(request.result_text, resultHtml);
            }

            await requestJson('POST', '/weda/import-status', {
                status: inserted ? 'inserted_active_field' : 'copied_to_clipboard',
                request_id: request.id,
                current_patient_id: currentPatientId,
                page_url: location.href,
                target: targetInfo.target,
                target_reason: targetInfo.reason,
                result_format: resultHtml ? 'html' : 'text',
                medico_legal_clinical_exam: medicoLegalResult ? {
                    added: !!medicoLegalResult.added,
                    already_present: !!medicoLegalResult.alreadyPresent,
                    reason: medicoLegalResult.reason || '',
                    target: medicoLegalResult.targetInfo ? medicoLegalResult.targetInfo.target : null,
                    target_reason: medicoLegalResult.targetInfo ? medicoLegalResult.targetInfo.reason : ''
                } : null,
                structured_weda: structuredWedaResult ? {
                    fields_filled: structuredWedaResult.fields && Array.isArray(structuredWedaResult.fields.filled)
                        ? structuredWedaResult.fields.filled.map(result => result.name)
                        : [],
                    fields_detected: structuredWedaResult.fields && Array.isArray(structuredWedaResult.fields.detected)
                        ? structuredWedaResult.fields.detected.map(result => ({
                            name: result.name,
                            value: result.value,
                            status: result.status
                        }))
                        : [],
                    tags_detected: structuredWedaResult.tags && Array.isArray(structuredWedaResult.tags.tags)
                        ? structuredWedaResult.tags.tags
                        : [],
                    tags_added: structuredWedaResult.tags && Array.isArray(structuredWedaResult.tags.added)
                        ? structuredWedaResult.tags.added.map(result => result.tag)
                        : [],
                    corrections: structuredWedaResult.report && Array.isArray(structuredWedaResult.report.corrections)
                        ? structuredWedaResult.report.corrections
                        : [],
                    error: structuredWedaResult.error || ''
                } : null,
                source
            });

            logEvent(inserted ? 'info' : 'warning', inserted ? 'import_inserted' : 'import_copied_to_clipboard', inserted
                ? 'Résultat inséré dans le champ WEDA.'
                : 'Aucun champ fiable : résultat copié dans le presse-papiers.', {
                request_id: request.id,
                target: targetInfo.target,
                target_reason: targetInfo.reason,
                result_length: String(request.result_text || '').length,
                result_html_length: resultHtml.length,
                medicoLegalResult: medicoLegalResult ? {
                    added: !!medicoLegalResult.added,
                    alreadyPresent: !!medicoLegalResult.alreadyPresent,
                    reason: medicoLegalResult.reason || '',
                    target: medicoLegalResult.targetInfo ? medicoLegalResult.targetInfo.target : null,
                    targetReason: medicoLegalResult.targetInfo ? medicoLegalResult.targetInfo.reason : ''
                } : null,
                structuredWedaResult: structuredWedaResult ? {
                    fieldsFilled: structuredWedaResult.fields && Array.isArray(structuredWedaResult.fields.filled)
                        ? structuredWedaResult.fields.filled.map(result => result.name)
                        : [],
                    tagsAdded: structuredWedaResult.tags && Array.isArray(structuredWedaResult.tags.added)
                        ? structuredWedaResult.tags.added.map(result => result.tag)
                        : [],
                    error: structuredWedaResult.error || ''
                } : null,
                source
            });

            if (!options || !options.silent) {
                let successMessage = 'Résultat inséré dans le champ actif.';
                if (inserted && medicoLegalResult && medicoLegalResult.added) {
                    successMessage = 'Résultat inséré. Phrase ajoutée dans Examen Clinique.';
                } else if (inserted && medicoLegalResult && medicoLegalResult.alreadyPresent) {
                    successMessage = 'Résultat inséré. Phrase déjà présente dans Examen Clinique.';
                } else if (inserted && medicoLegalResult && !medicoLegalResult.added) {
                    successMessage = 'Résultat inséré. Phrase Examen Clinique non ajoutée : voir logs.';
                }
                showBadge(
                    inserted
                        ? successMessage
                        : 'Aucun champ actif fiable : résultat copié dans le presse-papiers.'
                );
            }
            return { inserted, reason: inserted ? 'inserted' : 'copied_to_clipboard', request, targetInfo, medicoLegalResult, structuredWedaResult };
        } finally {
            releaseConnectorImportLock(importLock);
        }
    }

    function normalizeShortcutName(value) {
        const text = String(value || '').trim().toLowerCase().replace(/\s+/g, '');
        const aliases = {
            pageup: 'PageUp',
            pagedown: 'PageDown',
            prior: 'PageUp',
            next: 'PageDown',
            insert: 'Insert',
            ins: 'Insert',
            home: 'Home',
            end: 'End',
            debut: 'Home',
            fin: 'End'
        };
        if (aliases[text]) return aliases[text];
        const fKey = text.match(/^f(6|7|8|9|10|11|12)$/i);
        if (fKey) return 'F' + fKey[1];
        return value ? String(value).trim() : '';
    }

    function eventMatchesConnectorKey(event, shortcutName) {
        const name = normalizeShortcutName(shortcutName);
        if (!name) return false;
        const key = String(event.key || '');
        const code = String(event.code || '');
        const which = Number(event.which || event.keyCode || 0);

        const keyCodes = {
            PageUp: 33,
            PageDown: 34,
            Insert: 45,
            Home: 36,
            End: 35,
            F6: 117,
            F7: 118,
            F8: 119,
            F9: 120,
            F10: 121,
            F11: 122,
            F12: 123
        };

        return key === name || code === name || which === keyCodes[name];
    }

    function normalizeFlyDictationShortcutName(value) {
        const text = String(value || '').trim();
        const compact = text.toLowerCase().replace(/\s+/g, '');
        const aliases = {
            '2': '²',
            square: '²',
            carre: '²',
            'carré': '²'
        };
        if (aliases[compact]) return aliases[compact];
        return normalizeShortcutName(text || '²') || '²';
    }

    function eventMatchesFlyDictationKey(event, shortcutName) {
        const name = normalizeFlyDictationShortcutName(shortcutName);
        if (!name) return false;
        const key = String(event.key || '');
        const code = String(event.code || '');
        const which = Number(event.which || event.keyCode || 0);

        if (name === '²') {
            return key === '²'
                || (key === 'Dead' && (code === 'Backquote' || code === 'IntlBackslash' || which === 222 || which === 223))
                || code === 'Backquote'
                || code === 'IntlBackslash'
                || which === 222
                || which === 223;
        }

        return eventMatchesConnectorKey(event, name);
    }

    async function refreshConnectorSettings() {
        try {
            const response = await requestJson('GET', '/settings');
            const appSettings = response && response.settings ? response.settings : {};
            const settings = appSettings.connector
                ? appSettings.connector
                : {};
            connectorSettings = {
                enabled: !!settings.enabled,
                start_key: normalizeShortcutName(settings.start_key || 'PageUp'),
                stop_key: normalizeShortcutName(settings.stop_key || 'PageDown'),
                document_now_key: normalizeShortcutName(settings.document_now_key || 'F8'),
                auto_return_home: settings.auto_return_home !== false
            };
            const flySettings = appSettings.fly_dictation || {};
            flyDictationSettings = {
                enabled: flySettings.enabled !== false,
                key: normalizeFlyDictationShortcutName(flySettings.key || '²')
            };
            return connectorSettings;
        } catch (error) {
            logEvent('warning', 'connector_settings_unavailable', 'Réglages connecteur indisponibles.', {
                error: error && error.message ? error.message : String(error)
            });
            return connectorSettings;
        }
    }

    function connectorPayloadFromWeda(trigger) {
        const patientPanelText = getPatientPanelText();
        return {
            trigger: String(trigger || ''),
            patient_id: extractPatDk(location.href),
            patient_identity: inferPatientIdentity(patientPanelText),
            page_url: location.href,
            page_title: document.title || '',
            is_patient_home: isWedaPatientHomePage(),
            is_consultation: isWedaConsultationPage()
        };
    }

    async function startConnectorWorkflow(trigger = 'shortcut') {
        if (!isWedaPatientHomePage()) {
            logEvent('warning', 'connector_start_wrong_page', 'Démarrage connecteur refusé hors accueil patient.', {
                href: location.href,
                trigger
            });
            showBadge('Connecteur WEDA : déclenche depuis l’accueil patient WEDA.', true);
            return;
        }

        const settings = await refreshConnectorSettings();
        if (!settings.enabled) {
            showBadge('Connecteur WEDA désactivé dans l’application.', true);
            return;
        }

        const payload = connectorPayloadFromWeda(trigger);
        showBadge('Connecteur WEDA : démarrage dictée...');
        logEvent('info', 'connector_start_request', 'Déclenchement connecteur WEDA.', payload);
        const response = await requestJson('POST', '/connector/start', payload);
        const job = response.job || {};
        if (job.status === 'disabled' || job.status === 'error') {
            showBadge(job.message || 'Connecteur WEDA non démarré.', true);
            return;
        }

        writePendingConnectorJob({
            jobId: job.id,
            phase: 'recording',
            patientId: payload.patient_id,
            patientIdentity: payload.patient_identity,
            sourceUrl: location.href,
            autoReturnHome: settings.auto_return_home,
            message: 'Dictée connecteur en cours.',
            ts: Date.now()
        });

        showBadge('Connecteur WEDA : dictée démarrée. Collecte contexte programmée...');
        sendContext({ source: 'connector_start', silent: false }).catch(error => {
            logEvent('error', 'connector_start_context_error', 'Collecte contexte connecteur en erreur.', {
                error: error && error.message ? error.message : String(error)
            });
            showBadge('Connecteur WEDA : contexte non envoyé. Les logs contiennent le détail.', true);
        });
    }

    async function stopConnectorWorkflow(trigger = 'shortcut') {
        const settings = await refreshConnectorSettings();
        if (!settings.enabled) {
            showBadge('Connecteur WEDA désactivé dans l’application.', true);
            return;
        }

        const payload = connectorPayloadFromWeda(trigger);
        if (isWedaPatientHomePage()) {
            try {
                await sendContext({ source: 'connector_stop', skipDelay: true, silent: true });
            } catch (error) {
                logEvent('warning', 'connector_stop_context_error', 'Capture contexte immédiate avant arrêt échouée.', {
                    error: error && error.message ? error.message : String(error)
                });
            }
        }

        showBadge('Connecteur WEDA : arrêt dictée et envoi LM Studio...');
        logEvent('info', 'connector_stop_request', 'Arrêt connecteur WEDA.', payload);
        const response = await requestJson('POST', '/connector/stop', payload);
        const job = response.job || {};
        if (!job.id || job.status === 'error') {
            showBadge(job.message || 'Connecteur WEDA : arrêt impossible.', true);
            return;
        }

        writePendingConnectorJob({
            jobId: job.id,
            phase: 'waiting_result',
            waitStartedAt: Date.now(),
            patientId: payload.patient_id || job.patient_id || '',
            patientIdentity: payload.patient_identity || job.patient_identity || '',
            sourceUrl: location.href,
            autoReturnHome: settings.auto_return_home,
            message: 'Attente du résultat LM Studio.',
            ts: Date.now()
        });
        await continueConnectorPendingJob('stop_shortcut');
    }

    async function waitForConnectorDocumentNow(job) {
        const waitStartedAt = Date.now();
        while (Date.now() - waitStartedAt <= CONNECTOR_RESULT_TIMEOUT_MS) {
            const response = await requestJson(
                'GET',
                '/connector/document-now/status?job_id=' + encodeURIComponent(job.id)
            );
            const serverJob = response.job || null;
            if (!serverJob) {
                await sleep(CONNECTOR_POLL_INTERVAL_MS);
                continue;
            }

            if (serverJob.status === 'ready' && serverJob.clipboard_copied === true) {
                showBadge('Document maintenant prêt à être collé : il est dans le presse-papiers.');
                logEvent(
                    'info',
                    'connector_document_now_ready',
                    'Document maintenant prêt à être collé.',
                    {
                        jobId: serverJob.id || job.id,
                        resultLength: serverJob.result_length || 0,
                        elapsedSeconds: serverJob.elapsed_seconds || 0
                    }
                );
                return true;
            }

            if (serverJob.status === 'error' || serverJob.status === 'disabled') {
                showBadge(
                    serverJob.message || 'Document maintenant : génération ou copie impossible.',
                    true
                );
                logEvent(
                    'error',
                    'connector_document_now_error',
                    'Document maintenant non disponible.',
                    {
                        jobId: serverJob.id || job.id,
                        status: serverJob.status || '',
                        error: serverJob.error || serverJob.message || ''
                    }
                );
                return false;
            }

            showBadge('Document maintenant : génération en cours dans DrFloW...');
            await sleep(CONNECTOR_POLL_INTERVAL_MS);
        }

        showBadge('Document maintenant : délai dépassé. Vérifie DrFloW.', true);
        logEvent(
            'error',
            'connector_document_now_timeout',
            'Délai dépassé en attente de Document maintenant.',
            { jobId: job.id || '' }
        );
        return false;
    }

    async function triggerConnectorDocumentNowWorkflow(trigger = 'shortcut') {
        if (connectorDocumentNowBusy) {
            showBadge('Document maintenant : une génération est déjà suivie.');
            return;
        }

        connectorDocumentNowBusy = true;
        try {
            const settings = await refreshConnectorSettings();
            if (!settings.enabled) {
                showBadge('Connecteur WEDA désactivé dans l’application.', true);
                return;
            }

            try {
                await sendContext({
                    source: 'connector_document_now',
                    skipDelay: true,
                    silent: true
                });
            } catch (error) {
                logEvent(
                    'warning',
                    'connector_document_now_context_error',
                    'Actualisation du contexte WEDA avant Document maintenant échouée.',
                    { error: error && error.message ? error.message : String(error) }
                );
            }

            const payload = connectorPayloadFromWeda(trigger);
            showBadge('Document maintenant : création du snapshot...');
            logEvent(
                'info',
                'connector_document_now_request',
                'Déclenchement Document maintenant depuis WEDA.',
                payload
            );
            const response = await requestJson('POST', '/connector/document-now', payload);
            const job = response.job || {};
            if (!job.id || job.status === 'error' || job.status === 'disabled') {
                showBadge(job.message || 'Document maintenant : démarrage impossible.', true);
                return;
            }
            await waitForConnectorDocumentNow(job);
        } finally {
            connectorDocumentNowBusy = false;
        }
    }

    async function waitForConnectorResult(job) {
        const waitStartedAt = Number(job.waitStartedAt || Date.now());
        updatePendingConnectorJob({ waitStartedAt, phase: 'waiting_result' });
        while (Date.now() - waitStartedAt <= CONNECTOR_RESULT_TIMEOUT_MS) {
            const response = await requestJson('GET', '/connector/status?job_id=' + encodeURIComponent(job.jobId));
            const serverJob = response.job || null;
            if (!serverJob) {
                await sleep(CONNECTOR_POLL_INTERVAL_MS);
                continue;
            }

            updatePendingConnectorJob({
                appStatus: serverJob.status || '',
                appMessage: serverJob.message || '',
                requestId: serverJob.request_id || '',
                patientId: serverJob.patient_id || job.patientId || '',
                patientIdentity: serverJob.patient_identity || job.patientIdentity || '',
                autoReturnHome: serverJob.auto_return_home !== undefined ? !!serverJob.auto_return_home : job.autoReturnHome
            });

            if (serverJob.status === 'result_ready') {
                const next = updatePendingConnectorJob({
                    phase: isWedaConsultationPage() ? 'import_result' : 'open_consultation',
                    message: 'Résultat prêt pour WEDA.',
                    resultReadyAt: Date.now()
                });
                showBadge('Connecteur WEDA : résultat prêt.');
                logEvent('info', 'connector_result_ready_seen', 'Résultat connecteur prêt côté application.', next);
                return true;
            }

            if (serverJob.status === 'error') {
                updatePendingConnectorJob({
                    phase: 'error',
                    message: serverJob.message || 'Erreur génération connecteur.',
                    error: serverJob.error || serverJob.message || ''
                });
                showBadge('Connecteur WEDA : erreur LM Studio. Voir logs.', true);
                return false;
            }

            showBadge('Connecteur WEDA : attente LM Studio...');
            await sleep(CONNECTOR_POLL_INTERVAL_MS);
        }

        updatePendingConnectorJob({
            phase: 'error',
            message: 'Timeout attente résultat LM Studio.',
            error: 'connector_result_timeout'
        });
        showBadge('Connecteur WEDA : délai dépassé en attente du résultat.', true);
        return false;
    }

    async function continueConnectorPendingJob(trigger = 'poll') {
        if (connectorWorkflowBusy) return;
        let job = readPendingConnectorJob();
        if (!job || job.phase === 'recording') return;

        connectorWorkflowBusy = true;
        try {
            for (let guard = 0; guard < 6; guard += 1) {
                job = readPendingConnectorJob();
                if (!job) return;

                if (job.phase === 'waiting_result') {
                    const ready = await waitForConnectorResult(job);
                    if (!ready) return;
                    continue;
                }

                if (job.phase === 'opening_consultation') {
                    if (isWedaConsultationPage()) {
                        updatePendingConnectorJob({ phase: 'import_result', message: 'Consultation WEDA détectée.' });
                        continue;
                    }
                    const requestedAt = Number(job.openRequestedAt || 0);
                    if (requestedAt && Date.now() - requestedAt < CONNECTOR_CONSULTATION_OPEN_TIMEOUT_MS + 5000) {
                        return;
                    }
                    updatePendingConnectorJob({ phase: 'open_consultation' });
                    continue;
                }

                if (job.phase === 'open_consultation' || job.phase === 'manual_open_consultation') {
                    if (isWedaConsultationPage()) {
                        updatePendingConnectorJob({ phase: 'import_result', message: 'Consultation WEDA détectée.' });
                        continue;
                    }
                    if (job.phase === 'manual_open_consultation') {
                        showBadge('Connecteur WEDA : ouvre la consultation, l’import reprendra automatiquement.', true);
                        return;
                    }
                    await openConsultationForConnector(job);
                    return;
                }

                if (job.phase === 'import_result') {
                    if (!isWedaConsultationPage()) {
                        updatePendingConnectorJob({ phase: 'open_consultation' });
                        continue;
                    }

                    const importResult = await importLatestResult({ source: 'connector_auto', silent: true });
                    if (importResult.duplicateSkipped && importResult.reason === 'duplicate_import_in_progress') {
                        return;
                    }
                    if (!importResult.inserted) {
                        updatePendingConnectorJob({
                            phase: 'manual_import',
                            message: 'Import automatique non confirmé.',
                            importReason: importResult.reason || ''
                        });
                        showBadge('Connecteur WEDA : import auto non confirmé, résultat copié si nécessaire.', true);
                        return;
                    }

                    updatePendingConnectorJob({
                        phase: 'return_home',
                        message: 'Résultat inséré, retour accueil.'
                    });
                    showBadge('Connecteur WEDA : résultat inséré.');
                    const shouldReturnHome = job.autoReturnHome !== false;
                    clearPendingConnectorJob();
                    if (shouldReturnHome) {
                        await returnHomeWedaConnector(job);
                    }
                    return;
                }

                if (job.phase === 'manual_import') {
                    if (isWedaConsultationPage()) {
                        showBadge('Connecteur WEDA : import manuel possible via le bouton du panneau.', true);
                    }
                    return;
                }

                if (job.phase === 'error') {
                    logEvent('warning', 'connector_pending_error', 'Job connecteur en erreur.', {
                        trigger,
                        job
                    });
                    return;
                }

                return;
            }
        } catch (error) {
            updatePendingConnectorJob({
                phase: 'error',
                message: error && error.message ? error.message : String(error),
                error: error && error.stack ? String(error.stack).slice(0, 1200) : String(error)
            });
            logEvent('error', 'connector_resume_error', 'Erreur automate connecteur WEDA.', {
                trigger,
                error: error && error.message ? error.message : String(error),
                stack: error && error.stack ? String(error.stack).slice(0, 1200) : ''
            });
            showBadge('Connecteur WEDA : erreur automate. Voir logs.', true);
        } finally {
            connectorWorkflowBusy = false;
        }
    }

    function installConnectorShortcutHandler() {
        if (connectorShortcutInstalled) return;
        connectorShortcutInstalled = true;

        document.addEventListener('keydown', event => {
            if (!connectorSettings || !connectorSettings.enabled) return;
            if (event.ctrlKey || event.altKey || event.metaKey) return;

            const isStart = eventMatchesConnectorKey(event, connectorSettings.start_key);
            const isStop = eventMatchesConnectorKey(event, connectorSettings.stop_key);
            const isDocumentNow = eventMatchesConnectorKey(event, connectorSettings.document_now_key);
            if (!isStart && !isStop && !isDocumentNow) return;

            const now = Date.now();
            if (now - connectorLastShortcutAt < CONNECTOR_SHORTCUT_COOLDOWN_MS) {
                event.preventDefault();
                event.stopPropagation();
                return;
            }
            connectorLastShortcutAt = now;

            event.preventDefault();
            event.stopPropagation();
            const action = isStart ? 'start' : (isStop ? 'stop' : 'document_now');
            const shortcutKey = isStart
                ? connectorSettings.start_key
                : (isStop ? connectorSettings.stop_key : connectorSettings.document_now_key);
            const trigger = `shortcut:${action}:${shortcutKey}`;
            logEvent('info', 'connector_shortcut', 'Raccourci connecteur WEDA détecté.', {
                action,
                trigger
            });

            Promise.resolve()
                .then(() => {
                    if (isStart) return startConnectorWorkflow(trigger);
                    if (isStop) return stopConnectorWorkflow(trigger);
                    return triggerConnectorDocumentNowWorkflow(trigger);
                })
                .catch(error => {
                    logEvent('error', 'connector_shortcut_error', 'Erreur raccourci connecteur.', {
                        action,
                        error: error && error.message ? error.message : String(error),
                        stack: error && error.stack ? String(error.stack).slice(0, 1200) : ''
                    });
                    showBadge('Connecteur WEDA : erreur raccourci. Voir logs.', true);
                });
        }, true);
    }

    function flyDictationPayload(trigger) {
        return {
            source: 'tampermonkey_weda',
            trigger: String(trigger || ''),
            key: flyDictationSettings && flyDictationSettings.key ? flyDictationSettings.key : '²',
            patient_id: extractPatDk(location.href),
            page_url: location.href,
            page_title: document.title || '',
            is_patient_home: isWedaPatientHomePage(),
            is_consultation: isWedaConsultationPage()
        };
    }

    async function sendFlyDictationCommand(action, trigger) {
        const response = await requestJson(
            'POST',
            '/fly-dictation/' + String(action || ''),
            flyDictationPayload(trigger)
        );
        return response && response.fly_dictation ? response.fly_dictation : null;
    }

    function stopFlyDictationFromWeda(trigger = 'shortcut:fly:keyup') {
        if (!flyDictationKeyDown) return;
        flyDictationKeyDown = false;
        Promise.resolve()
            .then(() => sendFlyDictationCommand('stop', trigger))
            .then(state => {
                logEvent('info', 'fly_dictation_stop_sent', 'Arrêt dictée à la volée envoyé.', {
                    trigger,
                    state
                });
                showBadge('Dictée à la volée : transcription...');
            })
            .catch(error => {
                logEvent('error', 'fly_dictation_stop_error', 'Erreur arrêt dictée à la volée.', {
                    trigger,
                    error: error && error.message ? error.message : String(error)
                });
                showBadge('Dictée à la volée : arrêt non confirmé. Voir logs.', true);
            });
    }

    function installFlyDictationShortcutHandler() {
        if (flyDictationShortcutInstalled) return;
        flyDictationShortcutInstalled = true;

        document.addEventListener('keydown', event => {
            if (!flyDictationSettings || !flyDictationSettings.enabled) return;
            if (event.ctrlKey || event.altKey || event.metaKey) return;
            if (!eventMatchesFlyDictationKey(event, flyDictationSettings.key)) return;

            event.preventDefault();
            event.stopPropagation();
            if (event.stopImmediatePropagation) event.stopImmediatePropagation();

            if (flyDictationKeyDown) return;
            flyDictationKeyDown = true;
            const trigger = 'shortcut:fly:keydown:' + (flyDictationSettings.key || '²');
            Promise.resolve()
                .then(() => sendFlyDictationCommand('start', trigger))
                .then(state => {
                    logEvent('info', 'fly_dictation_start_sent', 'Démarrage dictée à la volée envoyé.', {
                        trigger,
                        state
                    });
                    showBadge('Dictée à la volée : REC...');
                })
                .catch(error => {
                    logEvent('error', 'fly_dictation_start_error', 'Erreur démarrage dictée à la volée.', {
                        trigger,
                        error: error && error.message ? error.message : String(error)
                    });
                    showBadge('Dictée à la volée : démarrage impossible. Voir logs.', true);
                });
        }, true);

        document.addEventListener('keyup', event => {
            if (!flyDictationSettings || !flyDictationSettings.enabled) return;
            if (!eventMatchesFlyDictationKey(event, flyDictationSettings.key)) return;

            event.preventDefault();
            event.stopPropagation();
            if (event.stopImmediatePropagation) event.stopImmediatePropagation();
            stopFlyDictationFromWeda('shortcut:fly:keyup:' + (flyDictationSettings.key || '²'));
        }, true);

        window.addEventListener('blur', () => {
            stopFlyDictationFromWeda('window:blur');
        }, true);

        document.addEventListener('visibilitychange', () => {
            if (document.hidden) stopFlyDictationFromWeda('document:hidden');
        }, true);
    }

    function readPanelPosition() {
        try {
            const value = JSON.parse(localStorage.getItem(PANEL_POSITION_STORAGE_KEY) || '{}');
            const left = Number(value.left);
            const top = Number(value.top);
            if (!Number.isFinite(left) || !Number.isFinite(top)) return null;
            return { left, top };
        } catch (_) {
            return null;
        }
    }

    function savePanelPosition(panel) {
        try {
            const rect = panel.getBoundingClientRect();
            localStorage.setItem(PANEL_POSITION_STORAGE_KEY, JSON.stringify({
                left: Math.max(0, Math.round(rect.left)),
                top: Math.max(0, Math.round(rect.top))
            }));
        } catch (_) {}
    }

    function isPanelCollapsed() {
        try {
            return localStorage.getItem(PANEL_COLLAPSED_STORAGE_KEY) === '1';
        } catch (_) {
            return false;
        }
    }

    function setPanelCollapsed(panel, collapsed) {
        const body = document.getElementById(PANEL_BODY_ID);
        const button = document.getElementById(PANEL_COLLAPSE_ID);
        if (body) body.style.display = collapsed ? 'none' : 'grid';
        if (button) button.textContent = collapsed ? '+' : '-';
        panel.style.width = collapsed ? 'fit-content' : '208px';
        panel.style.minWidth = collapsed ? '0' : '';
        panel.style.maxWidth = collapsed ? 'calc(100vw - 28px)' : '';
        panel.style.padding = collapsed ? '6px 7px' : '8px';
        panel.style.gap = collapsed ? '0' : '7px';
        try {
            localStorage.setItem(PANEL_COLLAPSED_STORAGE_KEY, collapsed ? '1' : '0');
        } catch (_) {}
    }

    function installPanelDrag(panel, header) {
        let dragging = false;
        let startX = 0;
        let startY = 0;
        let startLeft = 0;
        let startTop = 0;

        header.addEventListener('mousedown', event => {
            if (event.button !== 0) return;
            if (event.target && event.target.closest && event.target.closest('button')) return;
            event.preventDefault();
            event.stopPropagation();
            const rect = panel.getBoundingClientRect();
            dragging = true;
            startX = event.clientX;
            startY = event.clientY;
            startLeft = rect.left;
            startTop = rect.top;
            panel.style.left = Math.round(rect.left) + 'px';
            panel.style.top = Math.round(rect.top) + 'px';
            panel.style.right = 'auto';
            panel.style.bottom = 'auto';
        }, true);

        document.addEventListener('mousemove', event => {
            if (!dragging) return;
            event.preventDefault();
            const maxLeft = Math.max(0, window.innerWidth - panel.offsetWidth);
            const maxTop = Math.max(0, window.innerHeight - panel.offsetHeight);
            const nextLeft = Math.max(0, Math.min(maxLeft, startLeft + event.clientX - startX));
            const nextTop = Math.max(0, Math.min(maxTop, startTop + event.clientY - startY));
            panel.style.left = Math.round(nextLeft) + 'px';
            panel.style.top = Math.round(nextTop) + 'px';
        }, true);

        document.addEventListener('mouseup', () => {
            if (!dragging) return;
            dragging = false;
            savePanelPosition(panel);
        }, true);
    }

    function makePanelHeaderButton(label) {
        const button = document.createElement('button');
        button.type = 'button';
        button.textContent = label;
        button.style.width = '22px';
        button.style.height = '22px';
        button.style.border = '0';
        button.style.borderRadius = '5px';
        button.style.background = '#e2e8f0';
        button.style.color = '#0f172a';
        button.style.font = '700 13px Arial, sans-serif';
        button.style.cursor = 'pointer';
        button.style.lineHeight = '1';
        return button;
    }

    function injectPanel() {
        if (document.getElementById(PANEL_ID)) return;

        const panel = document.createElement('div');
        panel.id = PANEL_ID;
        panel.style.position = 'fixed';
        panel.style.right = '14px';
        panel.style.bottom = '14px';
        panel.style.zIndex = '2147483647';
        panel.style.display = 'grid';
        panel.style.gap = '7px';
        panel.style.width = '208px';
        panel.style.padding = '8px';
        panel.style.background = '#fff';
        panel.style.border = '1px solid #cbd5e1';
        panel.style.borderRadius = '8px';
        panel.style.boxShadow = '0 10px 28px rgba(15,23,42,.28)';
        panel.style.font = '12px Arial, sans-serif';

        const savedPosition = readPanelPosition();
        if (savedPosition) {
            panel.style.left = savedPosition.left + 'px';
            panel.style.top = savedPosition.top + 'px';
            panel.style.right = 'auto';
            panel.style.bottom = 'auto';
        }

        const header = document.createElement('div');
        header.id = PANEL_HEADER_ID;
        header.style.display = 'flex';
        header.style.alignItems = 'center';
        header.style.gap = '6px';
        header.style.cursor = 'move';
        header.style.userSelect = 'none';

        const title = document.createElement('div');
        title.textContent = 'DrFloW';
        title.style.flex = '1';
        title.style.font = '700 12px Arial, sans-serif';
        title.style.color = '#0f172a';
        title.style.whiteSpace = 'nowrap';

        const rec = document.createElement('span');
        rec.id = PANEL_REC_ID;
        rec.textContent = 'REC';
        rec.style.display = 'none';
        rec.style.alignItems = 'center';
        rec.style.justifyContent = 'center';
        rec.style.padding = '2px 7px';
        rec.style.borderRadius = '999px';
        rec.style.background = '#dc2626';
        rec.style.color = '#fff';
        rec.style.font = '700 11px Arial, sans-serif';

        const collapseButton = makePanelHeaderButton(isPanelCollapsed() ? '+' : '-');
        collapseButton.id = PANEL_COLLAPSE_ID;

        header.appendChild(title);
        header.appendChild(rec);
        header.appendChild(collapseButton);

        const body = document.createElement('div');
        body.id = PANEL_BODY_ID;
        body.style.display = 'grid';
        body.style.gap = '6px';

        const contextButton = makeButton('Envoyer contexte', sendContext);
        const importButton = makeButton('Importer résultat', importLatestResult);
        const logsButton = makeButton('Copier logs', copyDebugLogs);
        body.appendChild(contextButton);
        body.appendChild(importButton);
        body.appendChild(logsButton);

        panel.appendChild(header);
        panel.appendChild(body);
        document.documentElement.appendChild(panel);

        collapseButton.addEventListener('click', event => {
            event.preventDefault();
            event.stopPropagation();
            setPanelCollapsed(panel, !isPanelCollapsed());
        }, true);
        installPanelDrag(panel, header);
        setPanelCollapsed(panel, isPanelCollapsed());
        syncConnectorRecordingIndicator(readPendingConnectorJob());
    }

    function makeButton(label, action) {
        const button = document.createElement('button');
        button.type = 'button';
        button.textContent = label;
        button.style.border = '0';
        button.style.borderRadius = '7px';
        button.style.padding = '8px 9px';
        button.style.background = '#12395f';
        button.style.color = '#fff';
        button.style.font = '700 12px Arial, sans-serif';
        button.style.cursor = 'pointer';
        button.addEventListener('mousedown', event => {
            event.preventDefault();
            event.stopPropagation();
        }, true);
        button.addEventListener('click', async event => {
            event.preventDefault();
            event.stopPropagation();
            try {
                await action();
            } catch (error) {
                logEvent('error', 'button_action_error', error && error.message ? error.message : String(error), {
                    button: label,
                    stack: error && error.stack ? String(error.stack).slice(0, 1200) : ''
                });
                showBadge(error && error.message ? error.message : String(error), true);
            }
        }, true);
        return button;
    }

    installEditableTracker();
    setInterval(installEditableTracker, 2500);
    setInterval(() => {
        try {
            rememberEditableTarget(getDeepActiveElement(), 'poll_active_element');
        } catch (_) {}
    }, 2000);

    logEvent('info', 'script_loaded', 'Pont Tampermonkey WEDA chargé.', {
        patient_id: extractPatDk(location.href)
    });
    injectPanel();
    installConnectorShortcutHandler();
    installFlyDictationShortcutHandler();
    refreshConnectorSettings();
    setInterval(refreshConnectorSettings, CONNECTOR_SETTINGS_REFRESH_MS);
    pollWedaContextRefreshRequest();
    setInterval(pollWedaContextRefreshRequest, CONTEXT_REFRESH_POLL_MS);
    setTimeout(() => continueConnectorPendingJob('load'), 600);
    setInterval(() => continueConnectorPendingJob('poll'), CONNECTOR_POLL_INTERVAL_MS);
})();
