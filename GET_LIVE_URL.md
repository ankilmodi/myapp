# 🚀 Get Your Live URL - Quick Steps

Your code is now on GitHub: **https://github.com/ankilmodi/myapp**

## ⚡ FASTEST METHOD: Render.com (5 Minutes)

### Step 1: Go to Render
Open: **https://render.com/**

### Step 2: Sign Up with GitHub
- Click "Get Started for Free"
- Sign up using your GitHub account (ankilmodi)

### Step 3: Create Web Service
1. Click **"New +"** button (top right)
2. Select **"Web Service"**
3. Click **"Connect account"** to link your GitHub
4. Find and select **"ankilmodi/myapp"** repository
5. Click **"Connect"**

### Step 4: Configure (Auto-filled from render.yaml)
Render will auto-detect your `render.yaml` file:
- **Name**: nse-fo-scanner
- **Region**: Singapore
- **Branch**: main
- **Build Command**: `pip install -r requirements.txt`
- **Start Command**: `python main.py`

Just click **"Apply"** or **"Create Web Service"**

### Step 5: Add Environment Variables
In the Render dashboard, go to **"Environment"** tab and add:

```
ANGEL_API_KEY = your_actual_api_key_here
ANGEL_CLIENT_ID = A123456 (your Angel One login ID)
ANGEL_PASSWORD = your_password_here
ANGEL_TOTP_SECRET = JBSWY3DPEHPK3PXP... (your TOTP secret)
```

### Step 6: Deploy! 🎉
- Click **"Save Changes"**
- Render will automatically deploy (takes 2-3 minutes)
- Your live URL will be: **https://nse-fo-scanner.onrender.com**

---

## 🌐 Alternative: Vercel (Fastest Serverless)

### Step 1: Install Vercel CLI
```powershell
npm install -g vercel
```

### Step 2: Deploy
```powershell
cd c:\xampp\htdocs\myapp
vercel
```

Follow the prompts and your app will be live at: **https://myapp-xxxxx.vercel.app**

### Step 3: Add Environment Variables
```powershell
vercel env add ANGEL_API_KEY
vercel env add ANGEL_CLIENT_ID
vercel env add ANGEL_PASSWORD
vercel env add ANGEL_TOTP_SECRET
```

### Step 4: Deploy to Production
```powershell
vercel --prod
```

---

## 🚂 Alternative: Railway.app

### Quick Steps:
1. Go to **https://railway.app/**
2. Sign in with GitHub
3. Click **"New Project"** → **"Deploy from GitHub repo"**
4. Select **ankilmodi/myapp**
5. Add environment variables in **"Variables"** tab
6. Click **"Settings"** → **"Generate Domain"**

Your live URL: **https://myapp.up.railway.app**

---

## 📊 What You'll Get

Once deployed, your live URL will show:

✅ **Real-time F&O Scanner Dashboard**
- Auto-refreshes every 60 seconds
- Top 20 buy signals with scores
- Live market data from Angel One API
- Multi-factor analysis (RSI, MACD, EMA, Volume, OI)

---

## 🔒 Important: Add Your Angel One Credentials

Don't forget to add these environment variables in your hosting platform:

```
ANGEL_API_KEY=your_api_key
ANGEL_CLIENT_ID=A123456
ANGEL_PASSWORD=your_password
ANGEL_TOTP_SECRET=your_totp_secret
```

**Get your credentials from:**
https://smartapi.angelbroking.com/

---

## ✅ Your App is Ready!

- ✅ Code pushed to GitHub: https://github.com/ankilmodi/myapp
- ✅ Ready for deployment to Render/Vercel/Railway
- ✅ Just add your Angel One credentials
- ✅ Your live URL will be ready in 5 minutes!

---

**Need help? The full deployment guide is in DEPLOYMENT_GUIDE.md**
