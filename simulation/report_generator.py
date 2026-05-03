"""
ATLAS Report Generator
Produces HTML + JSON backtest report from BacktestResult.
Saved to simulation/reports/backtest_YYYYMMDD_HHMMSS.html
"""

import json
from datetime import datetime, timezone
from pathlib import Path

from simulation.backtester import BacktestResult

REPORT_DIR = Path("simulation/reports")
REPORT_DIR.mkdir(parents=True, exist_ok=True)


def generate_report(result: BacktestResult, days: int = 30) -> str:
    """Generate HTML report and return file path."""
    ts_str = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    html_path = REPORT_DIR / f"backtest_{ts_str}.html"
    json_path = REPORT_DIR / f"backtest_{ts_str}.json"

    # Save JSON
    json_data = {
        "generated_at":    datetime.now(timezone.utc).isoformat(),
        "backtest_days":   days,
        "total_return":    result.total_return,
        "total_return_pct": result.total_return_pct,
        "sharpe_ratio":    result.sharpe_ratio,
        "max_drawdown":    result.max_drawdown,
        "max_drawdown_pct": result.max_drawdown_pct,
        "win_rate":        result.win_rate,
        "profit_factor":   result.profit_factor,
        "total_trades":    result.total_trades,
        "winning_trades":  result.winning_trades,
        "losing_trades":   result.losing_trades,
        "avg_win":         result.avg_win,
        "avg_loss":        result.avg_loss,
        "best_trade":      result.best_trade,
        "worst_trade":     result.worst_trade,
        "best_day":        result.best_day,
        "worst_day":       result.worst_day,
        "avg_hold_bars":   result.avg_hold_bars,
        "regime_breakdown": result.regime_trades,
        "dna_breakdown":   result.dna_trades,
        "daily_pnl":       result.daily_pnl,
    }
    json_path.write_text(json.dumps(json_data, indent=2))

    # Trade rows HTML
    trade_rows = ""
    for t in result.trades[-50:]:   # Last 50
        pnl_cls = "pos" if t.pnl_usd >= 0 else "neg"
        dir_cls = "long" if t.direction == "LONG" else "short"
        trade_rows += f"""<tr>
          <td>{t.entry_time.strftime('%m/%d %H:%M')}</td>
          <td class="{dir_cls}">{t.direction}</td>
          <td>${t.entry_price:,.2f}</td>
          <td>${t.exit_price:,.2f}</td>
          <td class="{pnl_cls}"><b>{'+' if t.pnl_usd>=0 else ''}${t.pnl_usd:.2f}</b></td>
          <td>{t.pnl_pct:+.3f}%</td>
          <td>{t.exit_reason}</td>
          <td>{t.regime}</td>
          <td>{t.strategy}</td>
          <td>{t.confidence:.2f}</td>
        </tr>"""

    # Regime rows
    regime_rows = ""
    for reg, stats in result.regime_trades.items():
        wr = stats['wins']/stats['trades'] if stats['trades'] > 0 else 0
        pnl_cls = "pos" if stats['pnl'] >= 0 else "neg"
        regime_rows += f"""<tr>
          <td><b>{reg.upper()}</b></td>
          <td>{stats['trades']}</td>
          <td>{stats['wins']}</td>
          <td>{wr*100:.0f}%</td>
          <td class="{pnl_cls}">{'+' if stats['pnl']>=0 else ''}${stats['pnl']:.2f}</td>
        </tr>"""

    # DNA rows
    dna_rows = ""
    for dna, stats in result.dna_trades.items():
        wr = stats['wins']/stats['trades'] if stats['trades'] > 0 else 0
        pnl_cls = "pos" if stats['pnl'] >= 0 else "neg"
        dna_rows += f"""<tr>
          <td><b>{dna}</b></td>
          <td>{stats['trades']}</td>
          <td>{stats['wins']}</td>
          <td>{wr*100:.0f}%</td>
          <td class="{pnl_cls}">{'+' if stats['pnl']>=0 else ''}${stats['pnl']:.2f}</td>
        </tr>"""

    # Equity chart data
    eq_labels = [t.strftime('%m/%d %H:%M') for t in result.timestamps]
    eq_values = result.equity_curve

    ret_cls   = "pos" if result.total_return >= 0 else "neg"
    grade     = "A" if result.sharpe_ratio > 1.5 else "B" if result.sharpe_ratio > 0.8 else "C" if result.sharpe_ratio > 0 else "D"

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>ATLAS Backtest Report</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4/dist/chart.umd.min.js"></script>
<style>
:root{{--bg:#0d0f1a;--surface:#141627;--surface2:#1c1f35;--accent:#7c6cfc;--accent2:#00d4aa;--text:#e8eaff;--muted:#6b7280;--border:#252840;--green:#00d4aa;--red:#ff6b6b;}}
*{{margin:0;padding:0;box-sizing:border-box;}}
body{{background:var(--bg);color:var(--text);font-family:'Inter',system-ui,sans-serif;padding:32px;}}
h1{{font-size:24px;background:linear-gradient(135deg,var(--accent),var(--accent2));-webkit-background-clip:text;-webkit-text-fill-color:transparent;margin-bottom:4px;}}
.subtitle{{color:var(--muted);font-size:14px;margin-bottom:24px;}}
.grade{{font-size:48px;font-weight:900;color:var(--accent);margin-bottom:16px;}}
.metrics{{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px;margin-bottom:24px;}}
.metric{{background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:16px;position:relative;overflow:hidden;}}
.metric::before{{content:'';position:absolute;top:0;left:0;right:0;height:2px;background:linear-gradient(90deg,var(--accent),var(--accent2));}}
.m-label{{font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:.05em;margin-bottom:6px;}}
.m-value{{font-size:22px;font-weight:700;}}
.pos{{color:var(--green);}}
.neg{{color:var(--red);}}
.card{{background:var(--surface);border:1px solid var(--border);border-radius:12px;overflow:hidden;margin-bottom:16px;}}
.card-hdr{{padding:14px 20px;border-bottom:1px solid var(--border);font-weight:600;font-size:14px;}}
.card-body{{padding:20px;}}
table{{width:100%;border-collapse:collapse;font-size:13px;}}
th{{text-align:left;padding:8px 10px;color:var(--muted);font-size:11px;text-transform:uppercase;border-bottom:1px solid var(--border);}}
td{{padding:8px 10px;border-bottom:1px solid var(--border);}}
tr:last-child td{{border-bottom:none;}}
tr:hover td{{background:var(--surface2);}}
.long{{color:var(--green);font-weight:700;}}
.short{{color:var(--red);font-weight:700;}}
.chart-wrap{{height:300px;}}
</style>
</head>
<body>
<h1>⚡ ATLAS Backtest Report</h1>
<div class="subtitle">ETH/USD 15-minute | {days}-day simulation | Generated {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}</div>
<div class="grade">Grade: {grade}</div>

<div class="metrics">
  <div class="metric"><div class="m-label">Total Return</div><div class="m-value {ret_cls}">{'+' if result.total_return>=0 else ''}${result.total_return:.2f}<br><small style="font-size:14px">{result.total_return_pct:+.2f}%</small></div></div>
  <div class="metric"><div class="m-label">Sharpe Ratio</div><div class="m-value {'pos' if result.sharpe_ratio>0 else 'neg'}">{result.sharpe_ratio:.3f}</div></div>
  <div class="metric"><div class="m-label">Max Drawdown</div><div class="m-value neg">-${result.max_drawdown:.2f}<br><small style="font-size:14px">-{result.max_drawdown_pct:.2f}%</small></div></div>
  <div class="metric"><div class="m-label">Win Rate</div><div class="m-value {'pos' if result.win_rate>=0.5 else 'neg'}">{result.win_rate*100:.1f}%</div></div>
  <div class="metric"><div class="m-label">Profit Factor</div><div class="m-value {'pos' if result.profit_factor>=1 else 'neg'}">{result.profit_factor:.3f}</div></div>
  <div class="metric"><div class="m-label">Total Trades</div><div class="m-value">{result.total_trades}<br><small style="font-size:13px;color:var(--green)">{result.winning_trades}W</small> / <small style="font-size:13px;color:var(--red)">{result.losing_trades}L</small></div></div>
  <div class="metric"><div class="m-label">Avg Win / Loss</div><div class="m-value"><span class="pos">${result.avg_win:.2f}</span> / <span class="neg">${abs(result.avg_loss):.2f}</span></div></div>
  <div class="metric"><div class="m-label">Best / Worst Day</div><div class="m-value"><span class="pos">${result.best_day:.2f}</span> / <span class="neg">${result.worst_day:.2f}</span></div></div>
  <div class="metric"><div class="m-label">Avg Hold (bars)</div><div class="m-value">{result.avg_hold_bars:.1f} bars<br><small style="font-size:12px;color:var(--muted)">{result.avg_hold_bars*15/60:.1f}h avg</small></div></div>
</div>

<div class="card">
  <div class="card-hdr">📈 Equity Curve</div>
  <div class="card-body"><div class="chart-wrap"><canvas id="eqChart"></canvas></div></div>
</div>

<div style="display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-bottom:16px">
  <div class="card">
    <div class="card-hdr">🌍 By Market Regime</div>
    <div class="card-body">
      <table><thead><tr><th>Regime</th><th>Trades</th><th>Wins</th><th>WR</th><th>P&amp;L</th></tr></thead>
      <tbody>{regime_rows}</tbody></table>
    </div>
  </div>
  <div class="card">
    <div class="card-hdr">🧬 By Strategy DNA</div>
    <div class="card-body">
      <table><thead><tr><th>DNA</th><th>Trades</th><th>Wins</th><th>WR</th><th>P&amp;L</th></tr></thead>
      <tbody>{dna_rows}</tbody></table>
    </div>
  </div>
</div>

<div class="card">
  <div class="card-hdr">📋 Trade Log (last 50)</div>
  <div class="card-body" style="overflow-x:auto">
    <table><thead><tr><th>Time</th><th>Dir</th><th>Entry</th><th>Exit</th><th>P&amp;L</th><th>P&amp;L%</th><th>Reason</th><th>Regime</th><th>DNA</th><th>Conf</th></tr></thead>
    <tbody>{trade_rows}</tbody></table>
  </div>
</div>

<script>
const ctx = document.getElementById('eqChart').getContext('2d');
new Chart(ctx, {{
  type: 'line',
  data: {{
    labels: {json.dumps(eq_labels)},
    datasets: [{{
      label: 'Equity ($)',
      data: {json.dumps([round(v,2) for v in eq_values])},
      borderColor: '#7c6cfc',
      backgroundColor: 'rgba(124,108,252,0.08)',
      fill: true,
      tension: 0.3,
      pointRadius: 0,
      borderWidth: 2,
    }}]
  }},
  options: {{
    responsive: true, maintainAspectRatio: false,
    plugins: {{legend:{{display:false}}}},
    scales: {{
      x: {{ticks:{{color:'#6b7280',maxTicksLimit:10}},grid:{{color:'#252840'}}}},
      y: {{ticks:{{color:'#6b7280',callback: v=>'$'+v.toLocaleString()}},grid:{{color:'#252840'}}}}
    }}
  }}
}});
</script>
</body></html>"""

    html_path.write_text(html, encoding="utf-8")
    return str(html_path)


def print_summary(result: BacktestResult):
    """Print clean console summary."""
    w = result.winning_trades
    l = result.losing_trades
    wr = result.win_rate * 100
    ret_sign = "+" if result.total_return >= 0 else ""

    print(f"\n{'='*60}")
    print(f"  ATLAS Backtest Results")
    print(f"{'='*60}")
    print(f"  Return:        {ret_sign}${result.total_return:.2f} ({result.total_return_pct:+.2f}%)")
    print(f"  Sharpe Ratio:  {result.sharpe_ratio:.3f}")
    print(f"  Max Drawdown:  -${result.max_drawdown:.2f} (-{result.max_drawdown_pct:.2f}%)")
    print(f"  Win Rate:      {wr:.1f}% ({w}W / {l}L / {result.total_trades} total)")
    print(f"  Profit Factor: {result.profit_factor:.3f}")
    print(f"  Avg Win:       +${result.avg_win:.2f}")
    print(f"  Avg Loss:      -${abs(result.avg_loss):.2f}")
    print(f"  Best Trade:    +${result.best_trade:.2f}")
    print(f"  Worst Trade:   ${result.worst_trade:.2f}")
    print(f"  Best Day:      +${result.best_day:.2f}")
    print(f"  Worst Day:     ${result.worst_day:.2f}")
    print(f"  Avg Hold:      {result.avg_hold_bars:.1f} bars ({result.avg_hold_bars*15/60:.1f}h)")
    print(f"\n  By Regime:")
    for reg, s in result.regime_trades.items():
        wr_r = s['wins']/s['trades']*100 if s['trades'] else 0
        sign = "+" if s['pnl'] >= 0 else ""
        print(f"    {reg:10s}  {s['trades']:3d} trades  {wr_r:.0f}% WR  {sign}${s['pnl']:.2f}")
    print(f"\n  By Strategy DNA:")
    for dna, s in result.dna_trades.items():
        wr_d = s['wins']/s['trades']*100 if s['trades'] else 0
        sign = "+" if s['pnl'] >= 0 else ""
        print(f"    {dna:15s}  {s['trades']:3d} trades  {wr_d:.0f}% WR  {sign}${s['pnl']:.2f}")
    print(f"{'='*60}\n")
