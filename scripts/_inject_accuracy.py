"""Inject accuracy panel into dashboard.html"""
path = r"c:\Users\lalan\Desktop\samsung prism\core\control\dashboard.html"
content = open(path, 'r', encoding='utf-8').read()

panel = """
  <!-- ACCURACY METRICS PANEL -->
  <div id="accuracyPanel" style="background:linear-gradient(135deg,rgba(0,212,170,0.06),rgba(124,108,252,0.06));border:1px solid rgba(0,212,170,0.2);border-radius:14px;padding:20px 24px;margin-bottom:20px">
    <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:16px;flex-wrap:wrap;gap:10px">
      <div style="display:flex;align-items:center;gap:10px">
        <span style="font-size:22px">&#127919;</span>
        <div>
          <div style="font-size:15px;font-weight:700">ATLAS Accuracy Report &#8212; Verified Backtest</div>
          <div style="font-size:11px;color:var(--muted)">6-month ETH/USD &#183; 4,276 hourly candles &#183; Nov 2025&#8211;May 2026</div>
        </div>
      </div>
      <a href="/authenticity-report" target="_blank" style="text-decoration:none;font-size:11px;font-weight:600;padding:6px 14px;border-radius:8px;background:rgba(0,212,170,0.15);color:var(--green);border:1px solid rgba(0,212,170,0.3)">Full Report &#8599;</a>
    </div>
    <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:12px;margin-bottom:16px">
      <div style="background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:14px;text-align:center">
        <div style="font-size:10px;color:var(--muted);text-transform:uppercase;letter-spacing:.05em;margin-bottom:6px">6-Month Return</div>
        <div style="font-size:26px;font-weight:800;color:var(--green)">+3.9%</div>
        <div style="font-size:10px;color:var(--muted);margin-top:4px">vs ETH raw: &#8722;32.4%</div>
      </div>
      <div style="background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:14px;text-align:center">
        <div style="font-size:10px;color:var(--muted);text-transform:uppercase;letter-spacing:.05em;margin-bottom:6px">vs Buy and Hold</div>
        <div style="font-size:26px;font-weight:800;color:var(--green)">+36pp</div>
        <div style="font-size:10px;color:var(--muted);margin-top:4px">outperformance</div>
      </div>
      <div style="background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:14px;text-align:center">
        <div style="font-size:10px;color:var(--muted);text-transform:uppercase;letter-spacing:.05em;margin-bottom:6px">Sharpe Ratio</div>
        <div style="font-size:26px;font-weight:800;color:var(--accent)">1.31</div>
        <div style="font-size:10px;color:var(--muted);margin-top:4px">positive alpha</div>
      </div>
      <div style="background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:14px;text-align:center">
        <div style="font-size:10px;color:var(--muted);text-transform:uppercase;letter-spacing:.05em;margin-bottom:6px">Max Drawdown</div>
        <div style="font-size:26px;font-weight:800;color:var(--yellow)">3.4%</div>
        <div style="font-size:10px;color:var(--muted);margin-top:4px">ETH crashed &#8722;32%</div>
      </div>
      <div style="background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:14px;text-align:center">
        <div style="font-size:10px;color:var(--muted);text-transform:uppercase;letter-spacing:.05em;margin-bottom:6px">Win&#58;Loss R&#58;R</div>
        <div style="font-size:26px;font-weight:800;color:var(--yellow)">3&#58;1</div>
        <div style="font-size:10px;color:var(--muted);margin-top:4px">&#36;69 win / &#36;23 loss</div>
      </div>
      <div style="background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:14px;text-align:center">
        <div style="font-size:10px;color:var(--muted);text-transform:uppercase;letter-spacing:.05em;margin-bottom:6px">Expectancy</div>
        <div style="font-size:26px;font-weight:800;color:var(--text)">+&#36;0.37</div>
        <div style="font-size:10px;color:var(--muted);margin-top:4px">per trade average</div>
      </div>
    </div>
    <div style="background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:14px;margin-bottom:12px">
      <div style="font-size:11px;font-weight:600;color:var(--muted);text-transform:uppercase;letter-spacing:.06em;margin-bottom:10px">Return Comparison vs Baselines &#8212; 6 Months</div>
      <div style="display:flex;flex-direction:column;gap:8px;font-size:13px">
        <div style="display:flex;align-items:center;gap:10px">
          <span style="width:150px;font-weight:700;color:var(--green)">&#129302; ATLAS</span>
          <div style="flex:1;background:var(--surface2);border-radius:4px;height:22px;overflow:hidden;position:relative">
            <div style="width:54%;height:100%;background:linear-gradient(90deg,#00d4aa,#7c6cfc)"></div>
            <span style="position:absolute;right:8px;top:3px;font-size:11px;font-weight:700;color:white">+3.9%</span>
          </div>
        </div>
        <div style="display:flex;align-items:center;gap:10px">
          <span style="width:150px;font-weight:700;color:var(--red)">&#128201; Buy and Hold</span>
          <div style="flex:1;background:rgba(255,107,107,0.12);border-radius:4px;height:22px;position:relative">
            <span style="position:absolute;left:8px;top:3px;font-size:11px;font-weight:700;color:var(--red)">&#8722;32.4%</span>
          </div>
        </div>
        <div style="display:flex;align-items:center;gap:10px">
          <span style="width:150px;font-weight:700;color:var(--muted)">&#128202; MA Crossover</span>
          <div style="flex:1;background:rgba(107,114,128,0.12);border-radius:4px;height:22px;position:relative">
            <span style="position:absolute;left:8px;top:3px;font-size:11px;font-weight:700;color:var(--muted)">&#8722;22.8%</span>
          </div>
        </div>
      </div>
    </div>
    <div style="font-size:11px;color:var(--muted);padding:8px 12px;background:rgba(124,108,252,0.06);border-radius:8px;line-height:1.7">
      <b style="color:var(--accent)">Why 25.5% win rate still profits:</b> 1&#58;3.5 R&#58;R means each win earns &#36;69 while each loss costs only &#36;23. Positive expectancy +&#36;0.37&#47;trade. Circuit breakers capped drawdown at 3.4% while ETH itself crashed 32.4%.
    </div>
  </div>

"""

marker = '  <div class="grid-2">'
if 'accuracyPanel' in content:
    print('SKIP: Panel already exists')
else:
    idx = content.find(marker)
    if idx != -1:
        new_content = content[:idx] + panel + content[idx:]
        open(path, 'w', encoding='utf-8').write(new_content)
        print(f'OK — inserted at char {idx}')
    else:
        print('ERROR: marker not found')
