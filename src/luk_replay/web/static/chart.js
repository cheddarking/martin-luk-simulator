/* Single-series close chart with a full data table and pointer crosshair. */
(function () {
  const NS = 'http://www.w3.org/2000/svg';
  const width = 800;
  const height = 270;
  const left = 48;
  const right = 18;
  const top = 20;
  const bottom = 34;

  function node(name, attributes = {}) {
    const element = document.createElementNS(NS, name);
    Object.entries(attributes).forEach(([key, value]) => element.setAttribute(key, String(value)));
    return element;
  }

  function format(value) {
    return Number(value).toFixed(2);
  }

  function renderChart(series) {
    const svg = document.getElementById('price-chart');
    if (!svg) return;
    svg.replaceChildren();
    const tooltip = document.getElementById('chart-tooltip');
    const values = (series || []).map(item => Number(item.close));
    if (!values.length || values.some(n => !Number.isFinite(n))) return;
    const smallest = Math.min(...values);
    const largest = Math.max(...values);
    const margin = Math.max((largest - smallest) * .12, .05);
    const floor = smallest - margin;
    const ceiling = largest + margin;
    const w = width - left - right;
    const h = height - top - bottom;
    const x = index => left + (series.length === 1 ? w / 2 : w * index / (series.length - 1));
    const y = value => top + h * (ceiling - value) / (ceiling - floor);
    for (let i = 0; i <= 3; i++) {
      const value = floor + (ceiling - floor) * i / 3;
      const yy = y(value);
      svg.append(node('line', {x1: left, x2: width-right, y1: yy, y2: yy, class: 'chart-grid'}));
      const label = node('text', {x: left-8, y: yy+4, 'text-anchor': 'end', class: 'chart-label'});
      label.textContent = format(value);
      svg.append(label);
    }
    const path = values.map((value, index) => `${index ? 'L' : 'M'}${x(index).toFixed(2)},${y(value).toFixed(2)}`).join(' ');
    svg.append(node('path', {d: path, class: 'chart-line'}));
    const final = values.length - 1;
    svg.append(node('circle', {cx: x(final), cy: y(values[final]), r: 4, class: 'chart-dot'}));
    const line = node('line', {x1: x(0), x2: x(0), y1: top, y2: height-bottom, class: 'chart-crosshair'});
    line.style.display = 'none';
    svg.append(line);
    const overlay = node('rect', {x: left, y: top, width: w, height: h, class: 'chart-overlay', tabindex: 0,
                                   'aria-label': 'Explore observed close values; full table below'});
    svg.append(overlay);
    function show(index) {
      const item = series[index];
      line.style.display = '';
      line.setAttribute('x1', x(index));
      line.setAttribute('x2', x(index));
      if (!tooltip) return;
      tooltip.hidden = false;
      tooltip.replaceChildren();
      const value = document.createElement('strong');
      value.textContent = '$' + format(item.close);
      const time = document.createElement('span');
      time.textContent = ' ' + new Date(item.timestamp).toLocaleString();
      tooltip.append(value, time);
      tooltip.style.left = Math.min(x(index) / width * svg.clientWidth, svg.clientWidth - 160) + 'px';
      tooltip.style.top = '12px';
    }
    overlay.addEventListener('pointermove', event => {
      const box = svg.getBoundingClientRect();
      const relative = (event.clientX - box.left) / box.width;
      const nearest = Math.min(series.length - 1, Math.max(0,
        Math.round((relative * width - left) / w * (series.length - 1))));
      show(nearest);
    });
    overlay.addEventListener('pointerleave', () => {
      line.style.display = 'none';
      if (tooltip) tooltip.hidden = true;
    });
    overlay.addEventListener('focus', () => show(0));
    overlay.addEventListener('blur', () => { line.style.display = 'none'; if (tooltip) tooltip.hidden = true; });
    overlay.addEventListener('keydown', event => {
      if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return;
      event.preventDefault();
      const current = Number(overlay.dataset.index || 0);
      const next = Math.min(series.length - 1, Math.max(0, current + (event.key === 'ArrowRight' ? 1 : -1)));
      overlay.dataset.index = String(next);
      show(next);
    });
  }
  window.ReplayChart = { render: renderChart };
}());
