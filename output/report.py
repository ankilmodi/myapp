"""
report.py
=========
Rich CLI table display + HTML report generator for screener results.
"""

import csv
import os
from datetime import datetime
from typing import Optional

import pandas as pd
from loguru import logger

# ── Rich console ───────────────────────────────────────────────
try:
    from rich.console import Console
    from rich.table import Table
    from rich import box
    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False
    logger.warning("rich not installed – falling back to plain text output.")

console = Console() if RICH_AVAILABLE else None


# ─────────────────────────────────────────
# CLI Table
# ─────────────────────────────────────────
def print_rich_table(df: pd.DataFrame, title: str = "🏆 NSE F&O Best Buy Scanner"):
    """Print a beautiful Rich table to the terminal."""
    if not RICH_AVAILABLE:
        _print_plain_table(df, title)
        return

    table = Table(
        title=f"\n{title}",
        box=box.ROUNDED,
        show_header=True,
        header_style="bold cyan",
        border_style="bright_blue",
        title_style="bold magenta",
    )

    table.add_column("Rank", style="bold white", justify="center", width=5)
    table.add_column("Stock Ticker", style="bold yellow", width=14)
    table.add_column("Current Price (₹)", style="white", justify="right", width=18)
    table.add_column("RSI Indicators", justify="right", width=15)
    table.add_column("Smart Money (SMC) Signal", justify="center", width=26)
    table.add_column("Action Verdict", justify="center", width=22)
    table.add_column("top Loss", style="bold red", justify="right", width=12)
    table.add_column("Target 1 (1M)", style="bold green", justify="right", width=14)
    table.add_column("Target 2 (1M)", style="bold green", justify="right", width=14)
    table.add_column("Target 3 (1M)", style="bold green", justify="right", width=14)
    table.add_column("Score", style="bold", justify="center", width=8)

    for rank, row in df.iterrows():
        score = row.get("score", 0)
        smc = row.get("smc_signal", "RETAIL CONSOLIDATION")
        action = row.get("action_verdict", "HOLD")

        # Color the score
        if score >= 80:
            score_style = "[bold green]"
        elif score >= 60:
            score_style = "[bold yellow]"
        elif score >= 40:
            score_style = "[bold blue]"
        else:
            score_style = "[bold red]"

        # SMC style
        if "INSTITUTIONAL" in smc:
            smc_style = "[bold cyan]INSTITUTIONAL BUY FLOW[/]"
        else:
            smc_style = "[dim white]RETAIL CONSOLIDATION[/]"

        # Action style
        if "BUY" in action:
            action_style = "[bold green]BUY / ACCUMULATE[/]"
        elif "SELL" in action:
            action_style = "[bold red]SELL / BOOK PROFIT[/]"
        else:
            action_style = "[bold yellow]HOLD[/]"

        table.add_row(
            str(rank),
            str(row.get("symbol", "")),
            f"₹{row.get('ltp', 0):,.2f}",
            f"{row.get('rsi', 0):.2f}",
            smc_style,
            action_style,
            f"₹{row.get('stop_loss', 0):,.2f}",
            f"₹{row.get('target_1', 0):,.2f}",
            f"₹{row.get('target_2', 0):,.2f}",
            f"₹{row.get('target_3', 0):,.2f}",
            f"{score_style}{score:.1f}[/]",
        )

    console.print(table)


def _print_plain_table(df: pd.DataFrame, title: str):
    """Fallback plain text table."""
    print(f"\n{'='*120}")
    print(f"  {title}")
    print(f"  Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*120}")
    print(
        f"{'Rank':>5} {'Stock Ticker':>14} {'Current Price':>15} {'RSI':>8} "
        f"{'SMC Signal':>25} {'Action Verdict':>22} {'top Loss':>12} "
        f"{'Target 1':>12} {'Target 2':>12} {'Target 3':>12}"
    )
    print("-" * 140)
    for rank, row in df.iterrows():
        print(
            f"{rank:>5} {row['symbol']:>14} {row['ltp']:>13.2f} {row['rsi']:>8.2f} "
            f"{row.get('smc_signal', 'N/A'):>25} {row.get('action_verdict', 'HOLD'):>22} "
            f"₹{row.get('stop_loss', 0):>10.2f} "
            f"₹{row.get('target_1', 0):>10.2f} ₹{row.get('target_2', 0):>10.2f} ₹{row.get('target_3', 0):>10.2f}"
        )
    print(f"{'='*120}\n")


# ─────────────────────────────────────────
# Summary Banner
# ─────────────────────────────────────────
def print_summary(stats: dict, timestamp: Optional[str] = None):
    """Print a summary panel."""
    ts = timestamp or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if RICH_AVAILABLE:
        from rich.panel import Panel
        summary = (
            f"[bold]Scan Time:[/] {ts}\n"
            f"[bold]Total Screened:[/] {stats.get('total_screened', 0)}\n"
            f"[bold green]🔥 Strong Buy:[/] {stats.get('strong_buy', 0)}\n"
            f"[bold yellow]✅ Buy:[/] {stats.get('buy', 0)}\n"
            f"[bold blue]⚠️  Watch:[/] {stats.get('watch', 0)}\n"
            f"[bold red]❌ Avoid:[/] {stats.get('avoid', 0)}\n"
            f"[bold]Avg Score:[/] {stats.get('avg_score', 0):.1f}/100\n"
            f"[bold magenta]🏆 Top Pick:[/] {stats.get('top_symbol', 'N/A')} "
            f"({stats.get('top_score', 0):.1f}/100)"
        )
        console.print(Panel(summary, title="📊 Scanner Summary", border_style="green"))
    else:
        print(f"\nScan: {ts}")
        for k, v in stats.items():
            print(f"  {k}: {v}")


# ─────────────────────────────────────────
# Save CSV
# ─────────────────────────────────────────
def save_csv(df: pd.DataFrame, path: str = "output/results.csv"):
    """Save results to CSV."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    export_df = df[[
        "symbol", "ltp", "rsi", "smc_signal", "action_verdict",
        "stop_loss", "target_1", "target_2", "target_3", "score", "grade"
    ]].copy()
    export_df.columns = [
        "Stock Ticker", "Current Price (₹)", "RSI Indicators", "Smart Money (SMC) Signal",
        "Action Verdict", "top Loss", "Target 1 (1M)", "Target 2 (1M)", "Target 3 (1M)", "Score", "Grade"
    ]
    export_df.to_csv(path, index_label="rank")
    logger.info(f"CSV saved → {path}")


# ─────────────────────────────────────────
# HTML Report
# ─────────────────────────────────────────
def save_html_report(df: pd.DataFrame, stats: dict, path: str = "output/dashboard.html"):
    """Generate a styled HTML report/dashboard."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Build table rows
    rows_html = ""
    for rank, row in df.iterrows():
        score = row.get("score", 0)
        if score >= 80:
            row_class = "strong-buy"
        elif score >= 60:
            row_class = "buy"
        elif score >= 40:
            row_class = "watch"
        else:
            row_class = "avoid"

        smc = row.get("smc_signal", "RETAIL CONSOLIDATION")
        smc_class = "smc-institutional" if "INSTITUTIONAL" in smc else "smc-retail"
        
        action = row.get("action_verdict", "HOLD")
        if "BUY" in action:
            action_class = "action-buy"
        elif "SELL" in action:
            action_class = "action-sell"
        else:
            action_class = "action-hold"

        rows_html += f"""
        <tr class="{row_class}">
            <td>{rank}</td>
            <td><strong>{row.get('symbol', '')}</strong></td>
            <td>₹{row.get('ltp', 0):,.2f}</td>
            <td>{row.get('rsi', 0):.2f}</td>
            <td><span class="badge {smc_class}">{smc}</span></td>
            <td><span class="badge {action_class}">{action}</span></td>
            <td class="stop-loss">₹{row.get('stop_loss', 0):,.2f}</td>
            <td class="target">₹{row.get('target_1', 0):,.2f}</td>
            <td class="target">₹{row.get('target_2', 0):,.2f}</td>
            <td class="target">₹{row.get('target_3', 0):,.2f}</td>
            <td><span class="score-badge">{score:.1f}</span></td>
            <td>{row.get('grade', '')}</td>
        </tr>"""

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta http-equiv="refresh" content="60">
    <title>NSE F&O Best Buy Scanner | Angel One</title>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap" rel="stylesheet">
    <style>
        :root {{
            --bg: #0a0f1e; --card: #111827; --border: #1e2d40;
            --accent: #3b82f6; --green: #10b981; --yellow: #f59e0b;
            --red: #ef4444; --text: #e5e7eb; --sub: #9ca3af;
            --cyan: #06b6d4;
        }}
        * {{ margin:0; padding:0; box-sizing:border-box; }}
        body {{ font-family:'Inter',sans-serif; background:var(--bg); color:var(--text);
                min-height:100vh; }}

        /* ─── Header ─── */
        header {{
            background: linear-gradient(135deg,#1e3a5f,#0a1628);
            padding: 24px 32px;
            border-bottom: 1px solid var(--border);
            display: flex; justify-content: space-between; align-items: center;
        }}
        header h1 {{ font-size:1.6rem; font-weight:700; }}
        header h1 span {{ color: var(--accent); }}
        .timestamp {{ font-size:.8rem; color:var(--sub); }}
        .live-badge {{
            background: #10b98133; color: var(--green);
            padding: 4px 12px; border-radius: 20px; font-size:.75rem; font-weight:600;
            border: 1px solid var(--green); animation: pulse 2s infinite;
        }}
        @keyframes pulse {{ 0%,100%{{opacity:1}} 50%{{opacity:.5}} }}

        /* ─── Stats Cards ─── */
        .stats-grid {{
            display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
            gap: 16px; padding: 24px 32px;
        }}
        .stat-card {{
            background: var(--card); border: 1px solid var(--border);
            border-radius: 12px; padding: 20px; text-align: center;
        }}
        .stat-card .label {{ font-size:.75rem; color:var(--sub); margin-bottom:8px; text-transform:uppercase; letter-spacing:.05em; }}
        .stat-card .value {{ font-size:2rem; font-weight:700; }}
        .stat-card.green .value {{ color:var(--green); }}
        .stat-card.yellow .value {{ color:var(--yellow); }}
        .stat-card.blue .value {{ color:var(--accent); }}
        .stat-card.red .value {{ color:var(--red); }}

        /* ─── Table ─── */
        .table-wrap {{ padding: 0 32px 40px; overflow-x:auto; }}
        .section-title {{
            font-size:1.1rem; font-weight:600; margin-bottom:16px;
            padding: 16px 0 8px; border-bottom:1px solid var(--border);
        }}
        table {{ width:100%; border-collapse:collapse; font-size:.85rem; }}
        thead th {{
            background:#0d1829; padding:12px 16px; text-align:left;
            color:var(--sub); font-weight:500; text-transform:uppercase;
            font-size:.7rem; letter-spacing:.08em; position:sticky; top:0;
        }}
        tbody tr {{ border-bottom:1px solid #ffffff0a; transition:background .15s; }}
        tbody tr:hover {{ background:#ffffff08; }}
        tbody td {{ padding:12px 16px; }}

        /* Row classes */
        .strong-buy {{ border-left: 3px solid var(--green); }}
        .buy {{ border-left: 3px solid var(--accent); }}
        .watch {{ border-left: 3px solid var(--yellow); }}
        .avoid {{ border-left: 3px solid var(--red); }}

        .score-badge {{
            background: #3b82f620; color:var(--accent); font-weight:700;
            padding:3px 10px; border-radius:20px; font-size:.85rem;
        }}
        .strong-buy .score-badge {{ background:#10b98120; color:var(--green); }}
        .avoid .score-badge {{ background:#ef444420; color:var(--red); }}
        .watch .score-badge {{ background:#f59e0b20; color:var(--yellow); }}

        /* Badges */
        .badge {{
            display: inline-block;
            padding: 4px 10px;
            border-radius: 12px;
            font-size: 0.7rem;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.03em;
        }}
        .smc-institutional {{
            background: rgba(6, 182, 212, 0.15);
            color: var(--cyan);
            border: 1px solid rgba(6, 182, 212, 0.3);
        }}
        .smc-retail {{
            background: rgba(156, 163, 175, 0.15);
            color: var(--sub);
            border: 1px solid rgba(156, 163, 175, 0.3);
        }}
        .action-buy {{
            background: rgba(16, 185, 129, 0.15);
            color: var(--green);
            border: 1px solid rgba(16, 185, 129, 0.3);
        }}
        .action-hold {{
            background: rgba(245, 158, 11, 0.15);
            color: var(--yellow);
            border: 1px solid rgba(245, 158, 11, 0.3);
        }}
        .action-sell {{
            background: rgba(239, 68, 68, 0.15);
            color: var(--red);
            border: 1px solid rgba(239, 68, 68, 0.3);
        }}
        
        .stop-loss {{
            color: #f87171;
            font-weight: 600;
        }}
        .target {{
            color: #34d399;
            font-weight: 600;
        }}

        /* Legend */
        .legend {{
            display:flex; gap:24px; padding:8px 32px 20px; flex-wrap:wrap;
        }}
        .leg {{ display:flex; align-items:center; gap:8px; font-size:.8rem; color:var(--sub); }}
        .leg-dot {{ width:12px; height:12px; border-radius:50%; }}

        footer {{
            text-align:center; padding:20px; color:var(--sub); font-size:.75rem;
            border-top:1px solid var(--border);
        }}
    </style>
</head>
<body>

<header>
    <div>
        <h1>📈 NSE F&O <span>Best Buy</span> Scanner</h1>
        <div class="timestamp">Last Updated: {timestamp} | Auto-refresh: 60s</div>
    </div>
    <span class="live-badge">⬤ LIVE</span>
</header>

<!-- Stats -->
<div class="stats-grid">
    <div class="stat-card"><div class="label">Total Screened</div><div class="value">{stats.get('total_screened', 0)}</div></div>
    <div class="stat-card green"><div class="label">🔥 Strong Buy</div><div class="value">{stats.get('strong_buy', 0)}</div></div>
    <div class="stat-card blue"><div class="label">✅ Buy</div><div class="value">{stats.get('buy', 0)}</div></div>
    <div class="stat-card yellow"><div class="label">⚠️ Watch</div><div class="value">{stats.get('watch', 0)}</div></div>
    <div class="stat-card red"><div class="label">❌ Avoid</div><div class="value">{stats.get('avoid', 0)}</div></div>
    <div class="stat-card"><div class="label">Avg Score</div><div class="value">{stats.get('avg_score', 0):.1f}</div></div>
    <div class="stat-card green"><div class="label">🏆 Top Pick</div>
        <div class="value" style="font-size:1.2rem">{stats.get('top_symbol','N/A')}</div></div>
</div>

<!-- Legend -->
<div class="legend">
    <div class="leg"><div class="leg-dot" style="background:#10b981"></div>Strong Buy (80-100)</div>
    <div class="leg"><div class="leg-dot" style="background:#3b82f6"></div>Buy (60-79)</div>
    <div class="leg"><div class="leg-dot" style="background:#f59e0b"></div>Watch (40-59)</div>
    <div class="leg"><div class="leg-dot" style="background:#ef4444"></div>Avoid (0-39)</div>
</div>

<!-- Table -->
<div class="table-wrap">
    <div class="section-title">📊 Ranked Stock List — Best Buy Formula (Score/100)</div>
    <table>
        <thead>
            <tr>
                <th>#</th>
                <th>Stock Ticker</th>
                <th>Current Price (₹)</th>
                <th>RSI Indicators</th>
                <th>Smart Money (SMC) Signal</th>
                <th>Action Verdict</th>
                <th>top Loss</th>
                <th>Target 1 (1M)</th>
                <th>Target 2 (1M)</th>
                <th>Target 3 (1M)</th>
                <th>Score</th>
                <th>Grade</th>
            </tr>
        </thead>
        <tbody>
            {rows_html}
        </tbody>
    </table>
</div>

<footer>
    🤖 Angel One SmartAPI + NSE F&O Best Buy Scanner &nbsp;|&nbsp;
    Formula: RSI(20) + MACD(20) + EMA(15) + Volume(15) + OI(15) + Supertrend(10) + 52W(5) = 100pts
    &nbsp;|&nbsp; <strong>Not financial advice.</strong>
</footer>
</body>
</html>"""

    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    logger.success(f"HTML dashboard saved → {path}")
    return path
