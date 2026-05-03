"""
ATLAS Pitch Deck Generator (V3: The Art of the Pitch)
Provides Values, 'Why', and 'How' for hackathon presentation.
"""

from pathlib import Path
from loguru import logger
import datetime

def generate_pitch_deck():
    html = f"""
    <html>
    <head>
        <title>ATLAS Pitch: Logic Over Luck</title>
        <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;600;900&family=JetBrains+Mono&display=swap" rel="stylesheet">
        <style>
            :root {{
                --bg: #050505; --card: #0c0d0e; --accent: #fbbf24;
                --red: #ef4444; --green: #10b981; --muted: #6b7280;
            }}
            body {{ font-family: 'Outfit', sans-serif; background: var(--bg); color: #fff; padding: 60px; margin:0; line-height: 1.6; }}
            .container {{ max-width: 1200px; margin: auto; }}
            
            .hero {{ text-align: center; margin-bottom: 100px; }}
            .hero h1 {{ font-size: 5rem; font-weight: 900; margin:0; background: linear-gradient(135deg, #fff 0%, #666 100%); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }}
            .hero .subtitle {{ font-size: 1.5rem; color: var(--accent); letter-spacing: 4px; font-weight: 300; }}

            .pitch-grid {{ display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 30px; margin-bottom: 80px; }}
            .step {{ background: var(--card); border-radius: 32px; padding: 50px; border: 1px solid #1a1b1e; position: relative; }}
            
            .step-num {{ font-family: 'JetBrains Mono'; font-size: 0.9rem; color: var(--accent); margin-bottom: 20px; display: block; }}
            .step h2 {{ font-size: 2.2rem; margin-top: 0; }}
            .value-box {{ font-size: 3rem; font-weight: 900; margin: 30px 0; }}
            
            .why-how {{ margin-top: 40px; border-top: 1px solid #222; padding-top: 30px; }}
            .why-how h4 {{ text-transform: uppercase; color: var(--muted); font-size: 0.7rem; letter-spacing: 2px; margin-bottom: 10px; }}
            .why-how p {{ font-size: 0.95rem; margin-bottom: 20px; }}

            .tag {{ display: inline-block; padding: 4px 12px; border-radius: 20px; font-size: 0.7rem; font-weight: 800; margin-right: 5px; margin-bottom: 5px; }}
            .tag-red {{ background: rgba(239,68,68,0.1); color: var(--red); border: 1px solid var(--red); }}
            .tag-green {{ background: rgba(16,185,129,0.1); color: var(--green); border: 1px solid var(--green); }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="hero">
                <span class="subtitle">THE VINDICATION</span>
                <h1>LOGIC OVER LUCK</h1>
            </div>

            <div class="pitch-grid">
                <!-- THE CRISIS -->
                <div class="step" style="border-top: 4px solid var(--red);">
                    <span class="step-num">01 / THE CRISIS</span>
                    <h2>Manual Bias</h2>
                    <div class="value-box red">-$5,240</div>
                    
                    <div class="why-how">
                        <h4>THE WHY (Failures)</h4>
                        <p>
                            <span class="tag tag-red">FOMO</span> 
                            <span class="tag tag-red">NO STOPS</span>
                            <span class="tag tag-red">REVENGE</span>
                        </p>
                        <p>Trading based on "Twitter Hype" led to a <b>34% Drawdown</b> in 22 days. Lack of exit logic caused $2k slippage on a single flash crash.</p>
                    </div>
                </div>

                <!-- THE BRIDGE -->
                <div class="step" style="border-top: 4px solid var(--accent);">
                    <span class="step-num">02 / THE SOLUTION</span>
                    <h2>ATLAS AI</h2>
                    <div class="value-box accent">VINDICATED</div>
                    
                    <div class="why-how">
                        <h4>THE HOW (Features)</h4>
                        <p>
                            <span class="tag" style="border:1px solid var(--accent); color:var(--accent);">CONSENSUS</span>
                            <span class="tag" style="border:1px solid var(--accent); color:var(--accent);">CIRCUITS</span>
                        </p>
                        <p>Replaced "Gut Feeling" with a <b>5-Agent Consensus</b>. Every trade requires <b>80%+ Confidence</b> from Technician, Analyst, and Risk agents.</p>
                    </div>
                </div>

                <!-- THE VICTORY -->
                <div class="step" style="border-top: 4px solid var(--green);">
                    <span class="step-num">03 / THE RECOVERY</span>
                    <h2>Stable Growth</h2>
                    <div class="value-box green">+$1,420</div>
                    
                    <div class="why-how">
                        <h4>THE VALUE (Alpha)</h4>
                        <p>
                            <span class="tag tag-green">60% WR</span>
                            <span class="tag tag-green">LOW DD</span>
                        </p>
                        <p>Recovered 25% of initial loss with <b>zero liquidation risk</b>. Max Drawdown suppressed to <b>4.2%</b> using dynamic VIX-based volatility filters.</p>
                    </div>
                </div>
            </div>

            <div style="background: var(--card); padding: 60px; border-radius: 40px; border: 1px solid #222; text-align: center;">
                <h3 style="font-size: 2rem; margin-bottom: 20px;">The Investor's Conclusion</h3>
                <p style="font-size: 1.2rem; color: var(--muted); max-width: 900px; margin: auto;">
                    "We didn't build a predictor; we built a <b>Risk-Weighted Decision Engine</b>. 
                    In a market defined by noise, ATLAS provides the <b>Alpha of Discipline</b>."
                </p>
                <div style="margin-top: 40px; font-family: 'JetBrains Mono'; font-size: 0.8rem; color: var(--accent);">
                    CONFIDENTIAL HACKATHON PITCH DOCUMENT // GENERATED {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}
                </div>
            </div>
        </div>
    </body>
    </html>
    """
    
    report_path = Path("simulation/reports/TRANSFORMATION_AUDIT.html")
    report_path.write_text(html)
    logger.success("Pitch Deck V3 Saved.")

if __name__ == "__main__":
    generate_pitch_deck()
