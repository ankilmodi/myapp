# 🚀 Deployment Guide - Get Your Live Link

This guide will help you deploy your NSE F&O Scanner and get a live URL.

---

## Option 1: Render.com (Recommended - Free) ⭐

### Step 1: Push to GitHub
```bash
cd c:\xampp\htdocs\myapp
git add .
git commit -m "Ready for deployment"
git push origin main
```

### Step 2: Deploy on Render
1. Go to https://render.com/
2. Sign up/Login with GitHub
3. Click **"New +"** → **"Web Service"**
4. Connect your GitHub repository
5. Render will auto-detect the `render.yaml` configuration

### Step 3: Add Environment Variables
In Render dashboard, go to **Environment** tab and add:

```
ANGEL_API_KEY=your_actual_api_key_here
ANGEL_CLIENT_ID=A123456
ANGEL_PASSWORD=your_password_here
ANGEL_TOTP_SECRET=JBSWY3DPEHPK3PXP...
```

### Step 4: Deploy
- Click **"Create Web Service"**
- Wait 2-3 minutes for deployment
- Your live link will be: `https://nse-fo-scanner.onrender.com`

---

## Option 2: Vercel (Serverless - Free)

### Step 1: Install Vercel CLI
```bash
npm install -g vercel
```

### Step 2: Deploy
```bash
cd c:\xampp\htdocs\myapp
vercel
```

### Step 3: Add Environment Variables
```bash
vercel env add ANGEL_API_KEY
vercel env add ANGEL_CLIENT_ID
vercel env add ANGEL_PASSWORD
vercel env add ANGEL_TOTP_SECRET
```

### Step 4: Deploy to Production
```bash
vercel --prod
```

Your live link will be: `https://your-project.vercel.app`

---

## Option 3: Railway.app (Easy Deploy - Free)

### Step 1: Push to GitHub
```bash
cd c:\xampp\htdocs\myapp
git add .
git commit -m "Deploy to Railway"
git push origin main
```

### Step 2: Deploy on Railway
1. Go to https://railway.app/
2. Sign up with GitHub
3. Click **"New Project"** → **"Deploy from GitHub repo"**
4. Select your repository

### Step 3: Add Environment Variables
In Railway dashboard, go to **Variables** tab:

```
PORT=3000
ANGEL_API_KEY=your_actual_api_key
ANGEL_CLIENT_ID=A123456
ANGEL_PASSWORD=your_password
ANGEL_TOTP_SECRET=your_totp_secret
```

### Step 4: Get Your Link
- Railway will auto-deploy
- Click **"Settings"** → **"Generate Domain"**
- Your live link will be: `https://your-app.up.railway.app`

---

## Option 4: Heroku (Reliable - Free Tier Available)

### Step 1: Install Heroku CLI
Download from: https://devcenter.heroku.com/articles/heroku-cli

### Step 2: Login and Create App
```bash
heroku login
cd c:\xampp\htdocs\myapp
heroku create nse-fo-scanner
```

### Step 3: Set Environment Variables
```bash
heroku config:set ANGEL_API_KEY=your_api_key
heroku config:set ANGEL_CLIENT_ID=A123456
heroku config:set ANGEL_PASSWORD=your_password
heroku config:set ANGEL_TOTP_SECRET=your_totp_secret
```

### Step 4: Deploy
```bash
git push heroku main
```

Your live link will be: `https://nse-fo-scanner.herokuapp.com`

---

## Option 5: PythonAnywhere (Simple - Free)

### Step 1: Sign Up
Go to https://www.pythonanywhere.com/ and create a free account

### Step 2: Upload Code
- Go to **Files** tab
- Upload your project files
- Or use Git to clone your repository

### Step 3: Create Web App
1. Go to **Web** tab
2. Click **"Add a new web app"**
3. Choose **Manual configuration** → **Python 3.10**
4. Set working directory: `/home/yourusername/myapp`
5. Edit WSGI file to point to your app

### Step 4: Set Environment Variables
In **Web** tab, add environment variables in **virtualenv** section

Your live link will be: `https://yourusername.pythonanywhere.com`

---

## 🔒 Security Tips

1. **Never commit credentials** to GitHub
   - Add `config/config.yaml` to `.gitignore` (already done)
   - Use environment variables only

2. **Use Environment Variables**
   ```bash
   # Instead of hardcoding in config.yaml, use:
   export ANGEL_API_KEY=your_key
   export ANGEL_CLIENT_ID=your_id
   export ANGEL_PASSWORD=your_password
   export ANGEL_TOTP_SECRET=your_secret
   ```

3. **Rotate TOTP Secret** periodically for security

---

## 📊 After Deployment

Once deployed, your live link will show:
- ✅ Real-time F&O stock scanner
- ✅ Auto-refreshing dashboard (every 60 seconds)
- ✅ Top 20 buy signals with scores
- ✅ Multi-factor analysis (RSI, MACD, EMA, Volume, OI)

### Access Your Dashboard
```
https://your-live-link.com/
```

The dashboard will automatically refresh with new data every 60 seconds!

---

## 🛠️ Quick Deployment Commands

### For Render (Recommended):
```bash
git add .
git commit -m "Deploy to Render"
git push origin main
# Then connect on Render.com dashboard
```

### For Vercel:
```bash
vercel --prod
```

### For Railway:
```bash
git add .
git commit -m "Deploy to Railway"
git push origin main
# Then connect on Railway.app dashboard
```

---

## Need Help?

If you face any issues:
1. Check deployment logs in your hosting platform dashboard
2. Verify environment variables are set correctly
3. Ensure your Angel One API credentials are valid
4. Check if TOTP secret is correctly configured

---

**Your scanner is ready to go live! 🚀**
