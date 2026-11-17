/* Local inspector only: no order entry, network destinations or third-party assets. */
(function () {
  const byId = id => document.getElementById(id);
  const view = document.body.dataset.view;
  const notice = byId('notice');
  const showNotice = text => { if (notice) notice.textContent = text; };

  function row(parent, values) {
    const tr = document.createElement('tr');
    values.forEach(value => {
      const td = document.createElement('td');
      td.textContent = String(value);
      tr.append(td);
    });
    parent.append(tr);
  }

  function decisionItem(parent, decision, asLink = false) {
    const li = document.createElement('li');
    if (decision.accepted) li.classList.add('approved');
    const time = document.createElement('time');
    time.dateTime = decision.as_of;
    time.textContent = new Date(decision.as_of).toLocaleString();
    const label = document.createElement('strong');
    label.textContent = decision.reason;
    const description = document.createElement('p');
    description.textContent = decision.description;
    li.append(time, label, description);
    if (decision.evidence && decision.evidence.length) {
      const evidence = document.createElement('p');
      evidence.textContent = decision.evidence.join(' · ');
      li.append(evidence);
    }
    parent.append(li);
  }

  function renderSummary(summary) {
    const container = byId('summary');
    if (!container) return;
    container.replaceChildren();
    [['Decisions', summary.decisions], ['Entries', summary.entries],
     ['Exits', summary.exits], ['Net result', '£' + summary.net_pnl_gbp]].forEach(([label, value]) => {
      const item = document.createElement('div');
      const name = document.createElement('span');
      const number = document.createElement('strong');
      name.textContent = label;
      number.textContent = value;
      item.append(name, number);
      container.append(item);
    });
  }

  function renderSession(payload) {
    const section = byId('run-view');
    if (section) section.hidden = false;
    renderSummary(payload.summary);
    const label = byId('source-kind');
    if (label) label.textContent = payload.timeframe === 'daily'
      ? payload.summary.symbol + ' · cached daily prices · ' + payload.source_kind +
        ' · adjustment: ' + payload.adjustment +
        ' · provider prices, simulated fills (not actual broker executions)'
      : 'User-supplied minute-price CSV; assumptions and rights remain your responsibility.';
    const chartRange = byId('chart-range');
    if (chartRange) chartRange.textContent = payload.series.length +
      (payload.timeframe === 'daily' ? ' completed trading days' : ' completed bars');
    window.ReplayChart.render(payload.series);
    const body = byId('price-rows');
    if (body) {
      body.replaceChildren();
      payload.series.forEach(item => row(body, [payload.timeframe === 'daily'
        ? item.timestamp.slice(0, 10) : new Date(item.timestamp).toLocaleString(),
        item.open, item.high, item.low, item.close, item.volume]));
    }
    const list = byId('decisions');
    if (list) {
      list.replaceChildren();
      payload.decisions.forEach(item => decisionItem(list, item));
    }
    const count = byId('decision-count');
    if (count) count.textContent = payload.decisions.length + ' observations';
    if (section) section.scrollIntoView({behavior: 'smooth', block: 'start'});
  }

  async function getJson(url, options) {
    const response = await fetch(url, options);
    const result = await response.json();
    if (!response.ok) throw new Error(typeof result.detail === 'string' ? result.detail : 'Check the CSV and try again.');
    return result;
  }

  async function loadCatalog(query = '') {
    try {
      const data = await getJson('/api/history?q=' + encodeURIComponent(query) + '&limit=100');
      const ready = byId('history-ready');
      const empty = byId('history-empty');
      if (data.count && ready && empty) {
        ready.hidden = false;
        empty.hidden = true;
        const options = byId('history-symbols');
        options.replaceChildren();
        data.symbols.forEach(record => {
          const option = document.createElement('option');
          option.value = record.symbol;
          option.label = record.first_date + ' to ' + record.last_date;
          options.append(option);
        });
        const stock = byId('history-symbol');
        if (!stock.value && data.symbols.length) stock.value = data.symbols[0].symbol;
        const coverage = byId('coverage-note');
        if (coverage && data.symbols.length) {
          const active = data.symbols.find(item => item.symbol === stock.value) || data.symbols[0];
          coverage.textContent = active.first_date + ' to ' + active.last_date +
            ' · ' + active.source + ' · ' + active.adjustment +
            (active.complete_six_years ? ' · six-year coverage' : ' · partial history');
        }
      } else if (empty && ready && !query) {
        empty.hidden = false;
        ready.hidden = true;
      }
    } catch (error) { showNotice('Could not read the private local price cache: ' + error.message); }
  }

  async function loadHistory(event) {
    event.preventDefault();
    const symbol = byId('history-symbol').value.trim().toUpperCase();
    if (!/^[A-Z][A-Z0-9.^-]{0,14}$/.test(symbol)) {
      showNotice('Enter a ticker already held in the private daily cache.');
      return;
    }
    const params = new URLSearchParams();
    if (byId('start-date').value) params.set('start_date', byId('start-date').value);
    if (byId('end-date').value) params.set('end_date', byId('end-date').value);
    showNotice('Replaying cached daily prices…');
    try {
      const suffix = params.toString() ? '?' + params : '';
      const payload = await getJson('/api/history/' + encodeURIComponent(symbol) +
                                    '/replay' + suffix, {method: 'POST'});
      renderSession(payload);
      showNotice('Daily replay saved locally. The prices are cached; fills and P&L are modeled.');
    } catch (error) { showNotice('Daily replay failed: ' + error.message); }
  }

  async function loadRecorded() {
    const runId = document.body.dataset.runId;
    if (!runId) return;
    try {
      const events = [];
      let offset = 0;
      let total = 1;
      const maxDisplayed = 20000;
      while (offset < total && offset < maxDisplayed) {
        const url = '/api/runs/' + encodeURIComponent(runId) + '/events?limit=1000&offset=' + offset;
        const response = await getJson(url);
        if (!response.events.length) throw new Error('The run ended before its stated event count.');
        events.push(...response.events);
        offset += response.events.length;
        total = response.total;
      }
      if (offset < total) {
        showNotice('Displaying the first ' + offset + ' of ' + total +
                   ' events. This browser view is capped; inspect later events through the paged API.');
      }
      const prices = events.filter(event => event.kind === 'BAR_COMPLETED').map(event => ({
        timestamp: event.as_of, close: event.details.close_usd
      }));
      window.ReplayChart.render(prices);
      const body = byId('price-rows');
      if (body) prices.forEach(item => row(body, [new Date(item.timestamp).toLocaleString(), item.close]));
      const list = byId('decisions');
      if (list) events.filter(event => ['SETUP', 'REJECTION', 'EXIT'].includes(event.kind))
        .forEach(event => decisionItem(list, {as_of: event.as_of, accepted: event.kind === 'SETUP',
          reason: event.reason, description: event.details.explanation || event.kind,
          evidence: event.details.evidence ? [event.details.evidence] : []}));
    } catch (error) { showNotice('Could not open local run: ' + error.message); }
  }

  if (view === 'home') {
    loadCatalog();
    byId('history-ready').addEventListener('submit', loadHistory);
    byId('history-symbol').addEventListener('change', () => loadCatalog(byId('history-symbol').value));
    let lookupTimer;
    byId('history-symbol').addEventListener('input', () => {
      clearTimeout(lookupTimer);
      lookupTimer = setTimeout(() => loadCatalog(byId('history-symbol').value), 250);
    });
  }
  if (view === 'recorded') loadRecorded();
}());
