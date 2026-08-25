"""
api/index.py
============
Vercel serverless handler for NSE F&O Scanner
"""

from http.server import BaseHTTPRequestHandler
from datetime import datetime
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Simple HTML response
def get_html():
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta http-equiv="refresh" content="60">
    <title>NSE F&O Scanner</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            background: linear-gradient(135deg, #0a0f1e 0%, #1a1f2e 100%);
            color: #e5e7eb;
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 20px;
        }}
        .container {{
            background: rgba(17, 24, 39, 0.95);
            border: 1px solid #1e2d40;
            border-radius: 20px;
            padding: 48px;
            max-width: 800px;
            width: 100%;
            backdrop-filter: blur(10px);
            box-shadow: 0 20px 60px rgba(0, 0, 0, 0.5);
        }}
        h1 {{
            font-size: 2.5rem;
            background: linear-gradient(135deg, #3b82f6, #8b5cf6);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            margin-bottom: 16px;
            font-weight: 700;
        }}
        .subtitle {{
            color: #9ca3af;
            font-size: 1.1rem;
            margin-bottom: 32px;
        }}
        .status {{
            background: #059669;
            color: white;
            padding: 12px 24px;
            border-radius: 12px;
            display: inline-block;
            font-weight: 600;
            margin-bottom: 24px;
            animation: pulse 2s ease-in-out infinite;
        }}
        @keyframes pulse {{
            0%, 100% {{ opacity: 1; }}
            50% {{ opacity: 0.7; }}
        }}
        .info-box {{
            background: #1e293b;
            border-left: 4px solid #3b82f6;
            padding: 20px;
            border-radius: 8px;
            margin: 20px 0;
        }}
        .info-box h3 {{
            color: #60a5fa;
            margin-bottom: 12px;
            font-size: 1.2rem;
        }}
        .info-box p {{
            color: #cbd5e1;
            line-height: 1.6;
            margin: 8px 0;
        }}
        .features {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 16px;
            margin: 24px 0;
        }}
        .feature {{
            background: #1e293b;
            padding: 16px;
            border-radius: 12px;
            text-align: center;
        }}
        .feature-icon {{
            font-size: 2rem;
            margin-bottom: 8px;
        }}
        .feature-text {{
            color: #94a3b8;
            font-size: 0.9rem;
        }}
        .timestamp {{
            color: #64748b;
            font-size: 0.85rem;
            margin-top: 24px;
            text-align: center;
        }}
        .btn {{
            background: linear-gradient(135deg, #3b82f6, #2563eb);
            color: white;
            padding: 12px 32px;
            border-radius: 12px;
            text-decoration: none;
            display: inline-block;
            margin-top: 24px;
            font-weight: 600;
            transition: transform 0.2s;
        }}
        .btn:hover {{
            transform: translateY(-2px);
        }}
        code {{
            background: #0f172a;
            padding: 2px 8px;
            border-radius: 4px;
            color: #60a5fa;
            font-size: 0.9em;
        }}
    </style>
</head>
<body>
    <div class="container">
        <h1>📈 NSE F&O Scanner</h1>
        <p class="subtitle">Real-time Best Buy Signal Analysis</p>
        
        <div class="status">
            🟢 System Online
        </div>

        <div class="info-box">
            <h3>🚀 Welcome to NSE F&O Scanner</h3>
            <p>Your intelligent stock scanning system powered by Angel One SmartAPI</p>
            <p><strong>Version:</strong> 3.0 Live Deployment</p>
            <p><strong>Status:</strong> Vercel Serverless Deployment Active</p>
        </div>

        <div class="features">
            <div class="feature">
                <div class="feature-icon">📊</div>
                <div class="feature-text">209 F&O Stocks Monitored</div>
            </div>
            <div class="feature">
                <div class="feature-icon">⚡</div>
                <div class="feature-text">Real-time Data Updates</div>
            </div>
            <div class="feature">
                <div class="feature-icon">🎯</div>
                <div class="feature-text">Multi-Factor Analysis</div>
            </div>
            <div class="feature">
                <div class="feature-icon">🔄</div>
                <div class="feature-text">Auto-refresh (60s)</div>
            </div>
        </div>

        <div class="info-box">
            <h3>📋 Next Steps</h3>
            <p>To enable full scanning functionality, configure these environment variables in Vercel:</p>
            <p>• <code>ANGEL_API_KEY</code> - Your Angel One API key</p>
            <p>• <code>ANGEL_CLIENT_ID</code> - Your client ID</p>
            <p>• <code>ANGEL_PASSWORD</code> - Your password</p>
            <p>• <code>ANGEL_TOTP_SECRET</code> - Your TOTP secret</p>
        </div>

        <div class="info-box">
            <h3>🔧 Configuration Status</h3>
            <p><strong>API Key:</strong> {'✅ Configured' if os.environ.get('ANGEL_API_KEY') else '❌ Not Set'}</p>
            <p><strong>Client ID:</strong> {'✅ Configured' if os.environ.get('ANGEL_CLIENT_ID') else '❌ Not Set'}</p>
            <p><strong>Password:</strong> {'✅ Configured' if os.environ.get('ANGEL_PASSWORD') else '❌ Not Set'}</p>
            <p><strong>TOTP Secret:</strong> {'✅ Configured' if os.environ.get('ANGEL_TOTP_SECRET') else '❌ Not Set'}</p>
        </div>

        <a href="https://github.com/ankilmodi/myapp" class="btn" target="_blank">
            View on GitHub →
        </a>

        <p class="timestamp">
            Last updated: {now}<br>
            Page auto-refreshes every 60 seconds
        </p>
    </div>
</body>
</html>"""


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            html = get_html()
            self.send_response(200)
            self.send_header("Content-type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
            self.end_headers()
            self.wfile.write(html.encode("utf-8"))
        except Exception as e:
            self.send_response(500)
            self.send_header("Content-type", "text/plain")
            self.end_headers()
            self.wfile.write(f"Error: {str(e)}".encode("utf-8"))

    def log_message(self, format, *args):
        pass  # Suppress logs
