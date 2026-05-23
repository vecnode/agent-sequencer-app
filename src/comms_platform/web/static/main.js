const feed      = document.getElementById('feed');
const empty     = document.getElementById('empty');
const dot       = document.getElementById('dot');
const connLabel = document.getElementById('conn-label');
const statCount = document.getElementById('stat-count');
const statOscIn = document.getElementById('stat-osc-in');
const statOscOut = document.getElementById('stat-osc-out');
const statClients = document.getElementById('stat-clients');
const btnAgentOn = document.getElementById('btn-agent-on');
const btnAgentOff = document.getElementById('btn-agent-off');
const btnBroadcastOn = document.getElementById('btn-broadcast-on');
const btnBroadcastOff = document.getElementById('btn-broadcast-off');
const btnRunExampleToe = document.getElementById('btn-run-example-toe');
const btnCheckTd = document.getElementById('btn-check-td');
const btnSendTdTestData = document.getElementById('btn-send-td-test-data');
const btnCheckOllama = document.getElementById('btn-check-ollama');
const userInputText = document.getElementById('user-input-text');
const btnUserInputSend = document.getElementById('btn-user-input-send');
const agentStatus = document.getElementById('agent-status');
const agentBroadcast = document.getElementById('agent-broadcast');
const tdLaunchStatus = document.getElementById('td-launch-status');
const tdSendStatus = document.getElementById('td-send-status');
const ollamaStatus = document.getElementById('ollama-status');
const ollamaModelCount = document.getElementById('ollama-model-count');
const ollamaModelSelect = document.getElementById('ollama-model-select');
const terminalFeed = document.getElementById('terminal-feed');
const themeToggle = document.getElementById('theme-toggle');
const themeDropdown = document.getElementById('theme-dropdown');
const themeCurrentLabel = document.getElementById('theme-current-label');
const themeOptions = document.querySelectorAll('.theme-option');
const tabs = document.querySelectorAll('.tabs .tab');
const tabPanels = {
	dashboard: document.getElementById('panel-dashboard'),
	incoming: document.getElementById('panel-incoming'),
};

let count   = 0;
let paused  = false;
const MAX_ROWS = 200;
const TERMINAL_MAX_ROWS = 400;
const THEME_STORAGE_KEY = 'comms-platform-theme';

function closeThemeDropdown() {
	themeDropdown.hidden = true;
	themeToggle.setAttribute('aria-expanded', 'false');
}

function openThemeDropdown() {
	themeDropdown.hidden = false;
	themeToggle.setAttribute('aria-expanded', 'true');
}

function applyTheme(themeName) {
	const normalizedTheme = themeName === 'light' ? 'light' : 'dark';
	document.documentElement.setAttribute('data-theme', normalizedTheme);
	document.body.setAttribute('data-theme', normalizedTheme);
	document.documentElement.style.colorScheme = normalizedTheme;
	themeCurrentLabel.textContent = normalizedTheme === 'light' ? 'Light' : 'Dark';
	themeOptions.forEach((option) => {
		const isActive = option.dataset.theme === normalizedTheme;
		option.classList.toggle('active', isActive);
		option.setAttribute('aria-pressed', String(isActive));
	});
	try {
		localStorage.setItem(THEME_STORAGE_KEY, normalizedTheme);
	} catch (_) {}
}

function getSavedTheme() {
	try {
		const storedTheme = localStorage.getItem(THEME_STORAGE_KEY);
		return storedTheme === 'light' ? 'light' : 'dark';
	} catch (_) {
		return 'dark';
	}
}

themeToggle.addEventListener('click', (event) => {
	event.stopPropagation();
	if (themeDropdown.hidden) {
		openThemeDropdown();
		return;
	}
	closeThemeDropdown();
});

themeOptions.forEach((option) => {
	option.addEventListener('click', (event) => {
		event.stopPropagation();
		applyTheme(option.dataset.theme);
		closeThemeDropdown();
	});
});

document.addEventListener('click', (event) => {
	if (!themeDropdown.hidden && !event.target.closest('.theme-menu')) {
		closeThemeDropdown();
	}
});

document.addEventListener('keydown', (event) => {
	if (event.key === 'Escape' && !themeDropdown.hidden) {
		closeThemeDropdown();
	}
});

applyTheme(getSavedTheme());

function forceTerminalScroll() {
	terminalFeed.scrollTop = terminalFeed.scrollHeight;
	requestAnimationFrame(() => {
		terminalFeed.scrollTop = terminalFeed.scrollHeight;
	});
}

const terminalObserver = new MutationObserver(() => {
	forceTerminalScroll();
});
terminalObserver.observe(terminalFeed, { childList: true });

function inferTerminalTagClass(text) {
	const normalized = String(text || '').trim();
	if (normalized.startsWith('>')) return 'terminal-log-system';
	if (normalized.startsWith('[OLLAMA]')) return 'terminal-log-ollama';
	if (normalized.startsWith('[HUMAN]')) return 'terminal-log-human';
	if (normalized.startsWith('[AGENT]')) return 'terminal-log-agent';
	if (normalized.startsWith('[TD]')) return 'terminal-log-td';
	if (normalized.startsWith('[STREAM]')) return 'terminal-log-stream';
	return '';
}

function pushTerminalLine(text, className = '') {
	const row = document.createElement('div');
	const inferredClass = inferTerminalTagClass(text);
	const classes = ['terminal-line'];
	if (className) classes.push(className);
	if (inferredClass && inferredClass !== className) classes.push(inferredClass);
	row.className = classes.join(' ');
	row.textContent = text;
	terminalFeed.appendChild(row);

	while (terminalFeed.children.length > TERMINAL_MAX_ROWS) {
		terminalFeed.removeChild(terminalFeed.firstChild);
	}
	forceTerminalScroll();
}

function setActiveTab(tabName) {
	tabs.forEach((tab) => {
		tab.classList.toggle('active', tab.dataset.tab === tabName);
	});
	Object.entries(tabPanels).forEach(([key, panel]) => {
		panel.classList.toggle('active', key === tabName);
	});
}

tabs.forEach((tab) => {
	tab.addEventListener('click', () => {
		setActiveTab(tab.dataset.tab);
	});
});

// ── Status polling ──────────────────────────────────────────────
async function pollStatus() {
	try {
		const res  = await fetch('/api/status');
		const json = await res.json();
		statClients.textContent = json.sse_clients;
		statOscIn.textContent = json.osc_input;
		statOscOut.textContent = json.osc_output;
		setAgentUi(
			Boolean(json.agent_running),
			Boolean(json.agent_broadcast)
		);
	} catch (_) {}
}
pollStatus();
setInterval(pollStatus, 1000);

// ── SSE ─────────────────────────────────────────────────────────
function connect() {
	const source = new EventSource('/events');

	source.onopen = () => {
		dot.className       = 'dot connected';
		connLabel.textContent = 'connected';
	};

	source.onerror = () => {
		dot.className       = 'dot disconnected';
		connLabel.textContent = 'reconnecting…';
	};

	source.onmessage = (e) => {
		const data = JSON.parse(e.data);

		if (data.kind === 'log') {
			const level = String(data.level || 'INFO').toUpperCase();
			const line = data.text || `[${level}] ${data.logger || 'app'}: ${data.message || ''}`;
			pushTerminalLine(line, `terminal-log-${level.toLowerCase()}`);
			return;
		}

		if (paused) return;

		// Mirror stream events into the dashboard terminal panel.
		const signalAddr = data.address || '/unknown';
		const signalSource = data.source || 'unknown';
		const signalParams = Array.isArray(data.params) ? data.params : [data.params];
		pushTerminalLine(
			`[STREAM] ${signalAddr} ${JSON.stringify(signalParams)} (${signalSource})`,
			'terminal-log-stream'
		);

		count++;
		statCount.textContent = count;

		if (empty.parentNode === feed) feed.removeChild(empty);

		const row        = document.createElement('div');
		row.className    = 'message';

		const now        = new Date();
		const ts         = now.toTimeString().slice(0, 8) + '.' + String(now.getMilliseconds()).padStart(3, '0');
		const params     = Array.isArray(data.params) ? data.params : [data.params];
		const paramStr   = params.map(p => JSON.stringify(p)).join('  ');
		const protocol   = data.protocol || 'stream';
		const direction  = data.direction || 'inbound';
		const source     = data.source || 'unknown';

		row.innerHTML = `
			<span class="msg-time">${ts}</span>
			<span class="msg-addr">[${escHtml(direction)}/${escHtml(protocol)}] ${escHtml(data.address)}</span>
			<span class="msg-params">${escHtml(paramStr)}</span>
			<span class="msg-meta">${escHtml(source)}</span>
		`;

		feed.prepend(row);

		// Trim excess rows
		while (feed.children.length > MAX_ROWS) {
			feed.removeChild(feed.lastChild);
		}
	};
}

connect();

// ── Controls ────────────────────────────────────────────────────
document.getElementById('btn-clear').addEventListener('click', () => {
	feed.innerHTML = '';
	feed.appendChild(empty);
	count = 0;
	statCount.textContent = 0;
});

const btnPause = document.getElementById('btn-pause');
btnPause.addEventListener('click', () => {
	paused = !paused;
	btnPause.textContent     = paused ? 'resume' : 'pause';
	btnPause.style.borderColor = paused ? 'var(--accent)' : '';
	btnPause.style.color       = paused ? 'var(--accent)' : '';
});

function escHtml(str) {
	return String(str)
		.replace(/&/g, '&amp;')
		.replace(/</g, '&lt;')
		.replace(/>/g, '&gt;');
}

function setAgentUi(isRunning, isBroadcastEnabled) {
	agentStatus.textContent = isRunning ? 'ON' : 'OFF';
	agentStatus.className = isRunning ? 'agent-status-on' : 'agent-status-off';
	agentBroadcast.textContent = isBroadcastEnabled ? 'ON' : 'OFF';
	agentBroadcast.className = isBroadcastEnabled ? 'agent-status-on' : 'agent-status-off';
	btnAgentOn.disabled = isRunning;
	btnAgentOff.disabled = !isRunning;
	btnBroadcastOn.disabled = isBroadcastEnabled;
	btnBroadcastOff.disabled = !isBroadcastEnabled;
}

async function toggleAgent(url) {
	btnAgentOn.disabled = true;
	btnAgentOff.disabled = true;
	try {
		await fetch(url, { method: 'POST' });
		await pollStatus();
	} catch (_) {
		await pollStatus();
	}
}

async function toggleBroadcast(url) {
	btnBroadcastOn.disabled = true;
	btnBroadcastOff.disabled = true;
	try {
		await fetch(url, { method: 'POST' });
		await pollStatus();
	} catch (_) {
		await pollStatus();
	}
}

function setTdLaunchStatus(state, klass) {
	tdLaunchStatus.textContent = state;
	tdLaunchStatus.className = klass;
}

async function runExampleToe() {
	btnRunExampleToe.disabled = true;
	setTdLaunchStatus('LAUNCHING', 'agent-status-on');
	try {
		const res = await fetch('/api/touchdesigner/run-example', { method: 'POST' });
		if (!res.ok) {
			pushTerminalLine('[TD] ERROR launching example1.toe', 'terminal-log-error');
			throw new Error('launch failed');
		}
		pushTerminalLine('[TD] example1.toe launch requested', 'terminal-log-info');
		setTdLaunchStatus('RUNNING', 'agent-status-on');
	} catch (_) {
		pushTerminalLine('[TD] ERROR launch failed', 'terminal-log-error');
		setTdLaunchStatus('ERROR', 'agent-status-off');
	} finally {
		btnRunExampleToe.disabled = false;
	}
}

async function checkTdProcesses() {
	btnCheckTd.disabled = true;
	pushTerminalLine('[TD] Checking for running TouchDesigner processes...', 'terminal-log-info');
	try {
		const res = await fetch('/api/touchdesigner/processes');
		const json = await res.json();
		if (!(res.ok && json.ok)) {
			pushTerminalLine(`[TD] ERROR checking processes (${json.error || 'request failed'})`, 'terminal-log-error');
			return;
		}

		if (!json.running || !Array.isArray(json.processes) || json.processes.length === 0) {
			pushTerminalLine('[TD] No TouchDesigner process is currently running', 'terminal-log-warning');
			return;
		}

		pushTerminalLine(`[TD] Found ${json.count} TouchDesigner process(es):`, 'terminal-log-info');
		json.processes.forEach((processInfo) => {
			const name = processInfo.name || 'unknown';
			const pid = processInfo.pid || 'n/a';
			pushTerminalLine(`[TD] - ${name} (PID ${pid})`, 'terminal-log-info');
		});
	} catch (err) {
		pushTerminalLine(`[TD] ERROR checking processes (${err})`, 'terminal-log-error');
	} finally {
		btnCheckTd.disabled = false;
	}
}

function setTdSendStatus(state, klass) {
	tdSendStatus.textContent = state;
	tdSendStatus.className = klass;
}

async function sendTdTestData() {
	btnSendTdTestData.disabled = true;
	setTdSendStatus('SENDING', 'agent-status-on');
	try {
		const res = await fetch('/api/touchdesigner/send-test-data', { method: 'POST' });
		const json = await res.json();
		if (res.ok && json.ok) {
			pushTerminalLine('[TD] Test data sent successfully', 'terminal-log-info');
			setTdSendStatus('SENT', 'agent-status-on');
		} else {
			pushTerminalLine(`[TD] ERROR sending test data (${json.error || 'request failed'})`, 'terminal-log-error');
			setTdSendStatus('ERROR', 'agent-status-off');
		}
	} catch (_) {
		pushTerminalLine('[TD] ERROR sending test data (network/unknown)', 'terminal-log-error');
		setTdSendStatus('ERROR', 'agent-status-off');
	} finally {
		btnSendTdTestData.disabled = false;
	}
}

function setOllamaStatus(isUp, modelCount) {
	ollamaStatus.textContent = isUp ? 'ONLINE' : 'OFFLINE';
	ollamaStatus.className = isUp ? 'agent-status-on' : 'agent-status-off';
	ollamaModelCount.textContent = String(modelCount ?? 0);
}

function populateOllamaModels(models) {
	ollamaModelSelect.innerHTML = '';
	if (!Array.isArray(models) || models.length === 0) {
		ollamaModelSelect.disabled = true;
		const option = document.createElement('option');
		option.value = '';
		option.textContent = 'No models loaded';
		ollamaModelSelect.appendChild(option);
		return;
	}

	ollamaModelSelect.disabled = false;
	models.forEach((modelName) => {
		const option = document.createElement('option');
		option.value = String(modelName);
		option.textContent = String(modelName);
		ollamaModelSelect.appendChild(option);
	});
}

async function checkOllamaStatus() {
	btnCheckOllama.disabled = true;
	setOllamaStatus(false, 0);
	pushTerminalLine('[OLLAMA] Checking service status...', 'terminal-log-info');
	try {
		const res = await fetch('/api/ollama/status');
		const json = await res.json();
		const isUp = Boolean(res.ok && json.ok);
		setOllamaStatus(isUp, json.models_count || 0);
		populateOllamaModels(json.models || []);
		if (isUp) {
			pushTerminalLine(`[OLLAMA] ONLINE (${json.models_count || 0} models)`, 'terminal-log-info');
		} else {
			pushTerminalLine(`[OLLAMA] OFFLINE (${json.error || 'unknown error'})`, 'terminal-log-error');
		}
	} catch (err) {
		setOllamaStatus(false, 0);
		populateOllamaModels([]);
		pushTerminalLine(`[OLLAMA] OFFLINE (${err})`, 'terminal-log-error');
	} finally {
		btnCheckOllama.disabled = false;
	}
}

async function sendUserInputToAgent() {
	const text = userInputText.value.trim();
	if (!text) {
		return;
	}

	btnUserInputSend.disabled = true;
	userInputText.disabled = true;
	pushTerminalLine(`[HUMAN] ${text}`, 'terminal-log-info');

	try {
		const res = await fetch('/api/agent/message', {
			method: 'POST',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify({ text }),
		});
		const json = await res.json();
		if (res.ok && json.ok) {
			pushTerminalLine(`[AGENT] ${json.reply}`, 'terminal-log-info');
			userInputText.value = '';
		} else {
			pushTerminalLine(`[AGENT] ERROR (${json.error || 'request failed'})`, 'terminal-log-error');
		}
	} catch (err) {
		pushTerminalLine(`[AGENT] ERROR (${err})`, 'terminal-log-error');
	} finally {
		userInputText.disabled = false;
		btnUserInputSend.disabled = false;
		userInputText.focus();
	}
}

btnAgentOn.addEventListener('click', () => toggleAgent('/api/agent/start'));
btnAgentOff.addEventListener('click', () => toggleAgent('/api/agent/stop'));
btnBroadcastOn.addEventListener('click', () => toggleBroadcast('/api/agent/broadcast/on'));
btnBroadcastOff.addEventListener('click', () => toggleBroadcast('/api/agent/broadcast/off'));
btnRunExampleToe.addEventListener('click', runExampleToe);
btnCheckTd.addEventListener('click', checkTdProcesses);
btnSendTdTestData.addEventListener('click', sendTdTestData);
btnCheckOllama.addEventListener('click', checkOllamaStatus);
btnUserInputSend.addEventListener('click', sendUserInputToAgent);
userInputText.addEventListener('keydown', (e) => {
	if (e.key === 'Enter' && !e.shiftKey) {
		e.preventDefault();
		sendUserInputToAgent();
	}
});

checkOllamaStatus();
